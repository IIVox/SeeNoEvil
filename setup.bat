@echo off
cd /d "%~dp0"
echo Installing required libraries...
python -m ensurepip
python -m pip install --upgrade pip
python -m pip install requests
echo Done.
pause
