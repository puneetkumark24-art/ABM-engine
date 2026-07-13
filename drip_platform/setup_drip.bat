@echo off
REM Double-click this on Windows, or run it from cmd/PowerShell.
cd /d "%~dp0"
pip install -r requirements.txt
python setup_and_run.py
pause
