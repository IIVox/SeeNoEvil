#!/usr/bin/env python3
"""
"""

import os
import sys
import shlex
import subprocess
import threading
import time
import json
from typing import Dict, Optional
import ctypes

STD_OUTPUT_HANDLE = -11
ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
_ANSI_RED = "\x1b[31m"
_ANSI_RESET = "\x1b[0m"

def enable_ansi_colors():
    """Enable ANSI color sequences in Windows 10+ terminal."""
    try:
        handle = ctypes.windll.kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
        mode = ctypes.c_uint()
        if ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            ctypes.windll.kernel32.SetConsoleMode(
                handle, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING
            )
    except Exception:
        pass

enable_ansi_colors()

sys.stdout.write(_ANSI_RED)
sys.stdout.flush()

DB_PATH = "db.txt"
WEBHOOK_PATH = "webhook.txt"

try:
    import requests
    from requests.exceptions import RequestException
except Exception:
    print("Missing dependency: requests. Install with: pip install requests")
    raise

class Agent:
    def __init__(self, id_: int, popen: subprocess.Popen, launch_cmd: str):
        self.id = id_
        self.popen = popen
        self.launch_cmd = launch_cmd
        self.started_at = time.time()
        self.stopped_at = None

    def is_alive(self):
        return self.popen.poll() is None

    def terminate(self):
        if not self.is_alive():
            return
        try:
            self.popen.terminate()
            try:
                self.popen.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.popen.kill()
        except Exception as e:
            print(f"err terminating agent {self.id}: {e}")
        finally:
            self.stopped_at = time.time()

# --- Controller ---
class Controller:
    def __init__(self, script_name="camfind.py"):
        self.script = script_name
        self.next_id = 1
        self.agents: Dict[int, Agent] = {}
        self.lock = threading.Lock()
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()

    def _monitor_loop(self):
        while True:
            time.sleep(1)
            with self.lock:
                for aid, agent in list(self.agents.items()):
                    if not agent.is_alive() and agent.stopped_at is None:
                        agent.stopped_at = time.time()              
                    elif not agent.is_alive() and agent.stopped_at is not None:
                        if time.time() - agent.stopped_at > 5:
                            self.agents.pop(aid, None)

    def _abs_script(self):
        return os.path.abspath(self.script)

    def _spawn_process(self):
        python_exe = sys.executable
        script_path = self._abs_script()
        launch_cmd = f'"{python_exe}" "{script_path}"'

        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            p = subprocess.Popen(
                [python_exe, script_path],
                startupinfo=startupinfo,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL
            )
            return p, launch_cmd + " (background)"

        if sys.platform == "darwin":
            p = subprocess.Popen(
                [python_exe, script_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL
            )
            return p, launch_cmd + " (background)"

        p = subprocess.Popen(
            [python_exe, script_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL
        )
        return p, launch_cmd + " (background)"

    def start(self, amount: int):
        started = []
        with self.lock:
            for _ in range(amount):
                p, cmd = self._spawn_process()
                aid = self.next_id
                self.next_id += 1
                self.agents[aid] = Agent(aid, p, cmd)
                started.append(aid)
        print(f"started agents: {started}")

    def list_agents(self):
        with self.lock:
            if not self.agents:
                print("no agents")
                return
            print(f"{'ID':>3} {'PID':>6} {'STATUS':>8} {'UPTIME(s)':>10} COMMAND")
            for aid, agent in sorted(self.agents.items()):
                pid = agent.popen.pid if agent.popen else "N/A"
                status = "alive" if agent.is_alive() else "exited"
                uptime = (time.time() - agent.started_at) if agent.started_at else 0
                print(f"{aid:3} {pid:6} {status:8} {int(uptime):10} {agent.launch_cmd}")

    def kill(self, aid: int):
        with self.lock:
            agent = self.agents.get(aid)
            if not agent:
                print(f"no agent {aid}")
                return
            agent.terminate()
        del self.agents[aid]
        if not self.agents:
            self.next_id = 1
        print(f"killed agent {aid} (pid={agent.popen.pid})")

    def kill_all(self):
        with self.lock:
            for aid, agent in list(self.agents.items()):
                if agent.is_alive():
                    agent.terminate()
            self.agents.clear()
            self.next_id = 1
            print("all agents terminated")

    def restart(self, aid: int):
        with self.lock:
            agent = self.agents.get(aid)
            if not agent:
                print(f"no agent {aid}")
                return
            if agent.is_alive():
                agent.terminate()
            p, cmd = self._spawn_process()
            new_agent = Agent(aid, p, cmd)
            self.agents[aid] = new_agent
            print(f"restarted agent {aid} -> pid {p.pid}")

    def remove(self, aid: int):
        with self.lock:
            if aid in self.agents:
                del self.agents[aid]
                print(f"removed agent {aid}")
            else:
                print(f"no agent {aid}")

    def add_url(self, url: str, notes: str, author: Optional[str] = None):
        entry = {"url": url.strip(), "notes": notes.strip(), "ts": int(time.time())}
        if author:
            entry["by"] = author
        with open(DB_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        print("added.")

    def read_db(self):
        entries = []
        if not os.path.exists(DB_PATH):
            return entries
        with open(DB_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except Exception:
                    continue
        return entries

    def set_webhook(self, url: str):
        with open(WEBHOOK_PATH, "w", encoding="utf-8") as f:
            f.write(url.strip())
        print("webhook saved.")

    def show_webhook(self):
        if not os.path.exists(WEBHOOK_PATH):
            print("no webhook set")
            return None
        with open(WEBHOOK_PATH, "r", encoding="utf-8") as f:
            w = f.read().strip()
        print("webhook:", w)
        return w

    def _post_webhook_requests(self, webhook_url: str, payload: dict, max_retries: int = 2, timeout: int = 10):
        """
        Post payload to webhook_url using requests with realistic headers.
        Retries a small number of times on network errors or on 403 to allow transient blocking.
        Returns (status_code_or_None, response_text_or_error).
        """
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/117.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Content-Type": "application/json",
        }
        for attempt in range(1, max_retries + 1):
            try:
                resp = requests.post(webhook_url, json=payload, headers=headers, timeout=timeout)
                text = resp.text
                code = resp.status_code
                if code == 403 and attempt < max_retries:
                    time.sleep(1)
                    continue
                return code, text
            except RequestException as e:
                err = str(e)
                if attempt < max_retries:
                    time.sleep(1)
                    continue
                return None, err
        return None, "retry-failed"

    def send_urls(self, webhook_url: str = None, clear_after_send: bool = False):
        if webhook_url is None:
            webhook_url = self.show_webhook()
            if not webhook_url:
                print("set webhook first with 'set webhook' or provide it now.")
                return
        entries = self.read_db()
        if not entries:
            print("db.txt is empty.")
            return

        chunk_size = 8
        chunks = [entries[i : i + chunk_size] for i in range(0, len(entries), chunk_size)]
        failures = 0
        for idx, chunk in enumerate(chunks, 1):
            embeds = []
            for e in chunk:
                title = e.get("url") or "(no url)"
                desc = e.get("notes") or ""
                by = e.get("by")
                if by:
                    desc = f"Added by: {by}\n\n{desc}" if desc else f"Added by: {by}"
                if len(title) > 256:
                    title = title[:253] + "..."
                if len(desc) > 3968:
                    desc = desc[:3965] + "..."
                embeds.append({"title": title, "description": desc})
            payload = {"embeds": embeds}
            status, body = self._post_webhook_requests(webhook_url, payload, max_retries=2, timeout=10)
            if status is None or (isinstance(status, int) and status >= 400):
                print(f"chunk {idx}/{len(chunks)} failed. status={status} resp={body}")
                failures += 1
            else:
                print(f"chunk {idx}/{len(chunks)} sent. status={status}")
            time.sleep(1)

        if failures == 0:
            print("all sent.")
            if clear_after_send:
                try:
                    os.remove(DB_PATH)
                    print("db cleared.")
                except Exception:
                    pass
        else:
            print(f"{failures} chunks failed. db preserved.")

def prompt_input(prompt):
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt):
        return ""

def repl(controller: Controller):
    helptext = """commands:
 start N         - start N agents
 list            - list agents
 kill ID         - terminate agent ID
 kill all        - terminate all agents
 restart ID      - restart agent ID
 remove ID       - remove agent from controller (does not kill)
 add url         - interactively add a URL + notes to db.txt
 send urls       - send db.txt to Discord webhook (uses saved webhook if any)
 set webhook     - save webhook URL for send urls
 show webhook    - show saved webhook
 help            - this text
 exit / quit     - kill all and exit
"""
    print("""
 .|'''.|                  '|.   '|'         '||''''|            ||  '||  
 ||..  '    ....    ....   |'|   |    ...    ||  .    .... ... ...   ||  
  ''|||.  .|...|| .|...||  | '|. |  .|  '|.  ||''|     '|.  |   ||   ||  
.     '|| ||      ||       |   |||  ||   ||  ||         '|.|    ||   ||  
|'....|'   '|...'  '|...' .|.   '|   '|..|' .||.....|    '|    .||. .||. 
                                                                         
                                                                         
    """)
    while True:
        try:
            cmd = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            controller.kill_all()
            break
        if not cmd:
            continue
        parts = cmd.split()
        a = parts[0].lower()
        if a == "help":
            print(helptext)
            continue
        if a in ("exit", "quit"):
            controller.kill_all()
            break
        if a == "start":
            if len(parts) < 2:
                print("usage: start N")
                continue
            try:
                n = int(parts[1])
                if n <= 0:
                    raise ValueError
            except ValueError:
                print("N must be a positive integer")
                continue
            controller.start(n)
            continue
        if a == "list":
            controller.list_agents()
            continue
        if a == "kill":
            if len(parts) < 2:
                print("usage: kill ID | kill all")
                continue
            if parts[1] == "all":
                controller.kill_all()
                continue
            try:
                aid = int(parts[1])
            except ValueError:
                print("ID must be integer")
                continue
            controller.kill(aid)
            continue
        if a == "restart":
            if len(parts) < 2:
                print("usage: restart ID")
                continue
            try:
                aid = int(parts[1])
            except ValueError:
                print("ID must be integer")
                continue
            controller.restart(aid)
            continue
        if a == "remove":
            if len(parts) < 2:
                print("usage: remove ID")
                continue
            try:
                aid = int(parts[1])
            except ValueError:
                print("ID must be integer")
                continue
            controller.remove(aid)
            continue
        if a == "add" and len(parts) >= 2 and parts[1].lower() == "url":
            url = prompt_input("URL: ").strip()
            if not url:
                print("aborted.")
                continue
            notes = prompt_input("Notes (optional): ").strip()
            author = prompt_input("Author (optional): ").strip()
            controller.add_url(url, notes, author if author else None)
            continue
        if a == "send" and len(parts) >= 2 and parts[1].lower() == "urls":
            w = controller.show_webhook()
            if not w:
                supplied = prompt_input("No webhook saved. Enter webhook URL now (or blank to cancel): ").strip()
                if not supplied:
                    print("cancelled.")
                    continue
                controller.set_webhook(supplied)
                w = supplied
            ans = prompt_input("Clear db after successful send? (y/N): ").strip().lower()
            clear = ans == "y"
            controller.send_urls(webhook_url=w, clear_after_send=clear)
            continue
        if a == "set" and len(parts) >= 2 and parts[1].lower() == "webhook":
            url = prompt_input("Webhook URL: ").strip()
            if not url:
                print("aborted.")
                continue
            controller.set_webhook(url)
            continue
        if a == "show" and len(parts) >= 2 and parts[1].lower() == "webhook":
            controller.show_webhook()
            continue
        print("unknown command. type 'help'.")

if __name__ == "__main__":
    if not os.path.exists("camfind.py"):
        print("warning: camfind.py not found in current directory. Controller will still run but starting agents will fail.")
    ctrl = Controller(script_name="camfind.py")
    repl(ctrl)
