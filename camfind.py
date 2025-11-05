#!/usr/bin/env python3
import random
import requests
import socket
import ipaddress
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import sys

try:
    with open('webhook.txt', 'r') as f:
        WEBHOOK_URL = f.read().strip()
    if not WEBHOOK_URL:
        print("Error: webhook.txt is empty!")
        sys.exit(1)
except FileNotFoundError:
    print("Error: webhook.txt not found!")
    print("Please create webhook.txt with your Discord webhook URL")
    sys.exit(1)
except Exception as e:
    print(f"Error reading webhook.txt: {e}")
    sys.exit(1)

MAX_THREADS = 100
TIMEOUT = 5
DELAY_BETWEEN_CHECKS = 0.1

COMMON_PORTS = [80, 8080, 81, 554, 555, 37777, 8000, 9000, 10000]
COMMON_PATHS = [
    "/",
    "/login",
    "/index.html",
    "/live/view.html",
    "/video.cgi",
    "/snapshot.cgi",
    "/cgi-bin/viewer.cgi",
    "/mjpeg",
    "/h264",
    "/camera/status",
    "/video.live",
    "/view.shtml"
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
]

def generate_random_ip():
    """Generate a random public IP address"""
    while True:
        ip = ".".join(str(random.randint(0, 255)) for _ in range(4))
        if is_valid_public_ip(ip):
            return ip

def is_valid_public_ip(ip):
    """Check if IP address is valid and public (not private/reserved)"""
    try:
        ip_obj = ipaddress.ip_address(ip)
        return not (ip_obj.is_private or 
                   ip_obj.is_reserved or 
                   ip_obj.is_loopback or 
                   ip_obj.is_multicast or 
                   ip_obj.is_link_local or
                   ip_obj.is_unspecified)
    except ValueError:
        return False

def check_port(ip, port):
    """Check if a port is open on the IP"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(TIMEOUT)
        result = sock.connect_ex((ip, port))
        sock.close()
        return result == 0
    except:
        return False

def check_camera_interface(ip, port, path):
    """Check if a interface exists at the given URL"""
    url = f"http://{ip}:{port}{path}"
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=TIMEOUT, allow_redirects=True)
        
        camera_indicators = [
            "camera", "video", "live", "stream", "ipcam", "mjpeg",
            "webcam", "dvr", "nvr", "snapshot", "login"
        ]
        
        content = response.text.lower()
        status_code = response.status_code
        
        if status_code == 200:
            if any(keyword in content for keyword in ["ip camera", "network camera", "webcam", "dvr", "nvr"]):
                return True, url, status_code
            
            if any(indicator in content for indicator in camera_indicators):
                if "login" in content or "<video" in content or "stream" in content or "rtsp://" in content:
                    return True, url, status_code
                    
                if "password" in content and ("username" in content or "user" in content):
                    return True, url, status_code
                    
    except requests.exceptions.RequestException:
        pass
    except Exception:
        pass
    return False, None, None

def send_to_discord(webhook_url, ip, port, url, status_code):
    """Send findings to Discord webhook as embed with URL only"""
    try:
        color = random.randint(0, 0xFFFFFF)
        data = {
            "embeds": [{
                "title": "Interface Found",
                "description": f"[Open Interface]({url})",
                "color": color,
                "fields": [
                    {
                        "name": "IP Address",
                        "value": ip,
                        "inline": True
                    },
                    {
                        "name": "Port",
                        "value": str(port),
                        "inline": True
                    }
                ],
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            }]
        }
        response = requests.post(webhook_url, json=data, timeout=10)
        if response.status_code == 204:
            print(f"[+] Successfully sent to Discord: {url}")
        else:
            print(f"[-] Failed to send to Discord: {response.status_code}")
    except Exception as e:
        print(f"[-] Error sending to Discord: {e}")

def scan_ip(ip):
    """Scan a single IP for interfaces"""
    print(f"[!] Scanning IP: {ip}")
    
    for port in COMMON_PORTS:
        if check_port(ip, port):
            print(f"  [+] Port {port} open on {ip}")
            
            for path in COMMON_PATHS:
                is_camera, url, status = check_camera_interface(ip, port, path)
                if is_camera:
                    print(f"    [INTERFACE] Found at: {url}")
                    send_to_discord(WEBHOOK_URL, ip, port, url, status)
                    return True
    return False

def main():
    """Main function to continuously scan random IPs for interfaces"""
    print("=" * 60)
    print("IP INTERFACE SCANNER")
    print("=" * 60)
    print(f"Webhook URL loaded from webhook.txt")
    print(f"Threads: {MAX_THREADS}")
    print(f"Target ports: {COMMON_PORTS}")
    print("Press Ctrl+C to stop the scanner")
    print("=" * 60)
    
    cameras_found = 0
    
    try:
        with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
            futures = {executor.submit(scan_ip, generate_random_ip()): generate_random_ip() 
                      for _ in range(MAX_THREADS)}
            
            while True:
                for future in as_completed(futures):
                    ip = futures[future]
                    try:
                        result = future.result()
                        if result:
                            cameras_found += 1
                            print(f"[TOTAL INTERFACES FOUND: {cameras_found}]")
                    except Exception as e:
                        print(f"Error scanning {ip}: {e}")
                    
                    del futures[future]
                    new_ip = generate_random_ip()
                    futures[executor.submit(scan_ip, new_ip)] = new_ip
                
                time.sleep(DELAY_BETWEEN_CHECKS)
                
    except KeyboardInterrupt:
        print(f"\n\n[!] Scanner stopped by user")
        print(f"[+] Total interfaces found: {cameras_found}")
        print("Goodbye!")
        sys.exit(0)
    except Exception as e:
        print(f"\n[!] Unexpected error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
