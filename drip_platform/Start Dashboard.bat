@echo off
title DRIP Dashboard
cd /d "%~dp0"

REM This file used to launch ONLY the legacy Flask contact-CRUD app on port
REM 5050 -- which has none of the pipeline UI (Signal Review, Approvals,
REM Sequences/Enrollments, AI Decisions, Account 360). That's the most
REM likely reason it looked like none of this work was "in the dashboard":
REM this shortcut was opening the wrong app. It now starts the real thing,
REM same as "Start DRIP Platform.bat".

echo Starting DRIP OS (the real dashboard, port 8000)...
echo (this window is the server -- closing it stops the platform)
echo.

python sync_db.py

start "" cmd /c "timeout /t 4 >nul && start http://127.0.0.1:8000/"

python -m uvicorn main:app --host 127.0.0.1 --port 8000

echo.
echo The server stopped. If that was unexpected, scroll up to see the error above.
pause
