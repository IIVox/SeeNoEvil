@echo off
cd /d "%~dp0"
echo Installing required libraries...
python -m ensurepip
python -m pip install --upgrade pip
python -m pip install requests
python -m pip install beautifulsoup4
python3 -m ensurepip
python3 -m pip install --upgrade pip
python3 -m pip install requests
python3 -m pip install beautifulsoup4
echo Done.
pause
