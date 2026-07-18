@echo off
REM ============================================================
REM  Start DRIP Platform - one button for everything.
REM  Starts the API+console (port 8000) and the BD contact
REM  dashboard (port 5050), then opens the platform home page.
REM  Right-click this file -> Send to -> Desktop (create shortcut)
REM  to get your desktop button.
REM ============================================================
cd /d "%~dp0"

REM keep DB schema in sync with the code (idempotent, additive-only)
python sync_db.py

REM start the API + operator console on ALL interfaces so colleagues on the
REM office network can reach it at http://<your-LAN-IP>:8000
start "DRIP API" cmd /k python -m uvicorn main:app --host 0.0.0.0 --port 8000

REM start the BD contact dashboard
start "DRIP BD Dashboard" cmd /k python dashboard\app.py

REM give the servers a moment, then open the platform home
timeout /t 5 /nobreak >nul
start http://127.0.0.1:8000/

echo.
echo DRIP OS starting:
echo   DRIP OS   http://127.0.0.1:8000/    (one app - sign in under Settings)
echo   BD Dash   http://127.0.0.1:5050     (transition; being absorbed into the OS)
echo.
echo Team access on the office network:
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do echo   http://%%a:8000/  (trim spaces)
echo   (first time: allow python through Windows Firewall when prompted,
echo    Private networks only)
echo.
echo Close the two server windows to stop the platform.
