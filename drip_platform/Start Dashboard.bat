@echo off
title DRIP Dashboard
cd /d "%~dp0"

echo Starting DRIP dashboard...
echo (this window is the server — closing it stops the dashboard)
echo.

start "" cmd /c "timeout /t 3 >nul && start http://127.0.0.1:5050"

python dashboard\app.py

echo.
echo The dashboard stopped. If that was unexpected, scroll up to see the error above.
pause
