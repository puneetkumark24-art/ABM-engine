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

REM start the API + operator console on localhost only. Binding 0.0.0.0
REM exposes the dev server (dry-run auth, default secrets in most local
REM setups) to the whole office network; keep it to this machine unless a
REM deliberate, authenticated production deployment says otherwise.
start "DRIP API" cmd /k python -m uvicorn main:app --host 127.0.0.1 --port 8000

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
echo This machine only. To share with the team, deploy it properly behind
echo real auth (AUTH_ENFORCED=true, a non-default JWT_SECRET, HTTPS) rather
echo than exposing this dev server on the office network.
echo.
echo Close the two server windows to stop the platform.
