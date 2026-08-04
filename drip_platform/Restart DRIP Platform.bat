@echo off
REM ============================================================
REM  Restart DRIP OS  --  stops the old server, starts the new one
REM
REM  Use this instead of "Start DRIP Platform.bat" after any code
REM  change. The whole dashboard UI is embedded inside
REM  routers/os_shell.py, a Python module that uvicorn reads once at
REM  import -- so editing files changes nothing on screen until the
REM  process actually restarts. Leaving the old window running is
REM  why updated code can look like "no changes".
REM
REM  Localhost only. Real outreach stays disabled (dry-run).
REM ============================================================
cd /d "%~dp0"
title DRIP OS - restart

echo.
echo  [1/3] Stopping anything already listening on port 8000...
set FOUND=0
for /f "tokens=5" %%a in ('netstat -ano ^| findstr /R /C:":8000 .*LISTENING"') do (
    echo        stopping PID %%a
    taskkill /F /PID %%a >nul 2>&1
    set FOUND=1
)
if "%FOUND%"=="0" echo        nothing was running.
timeout /t 2 /nobreak >nul

echo  [2/3] Starting the DRIP API on http://127.0.0.1:8000 ...
start "DRIP API" cmd /k python -m uvicorn main:app --host 127.0.0.1 --port 8000

echo  [3/3] Opening the new Growth Operations screen...
REM give uvicorn a moment to bind before the browser asks for the page
start "" cmd /c "timeout /t 6 >nul && start http://127.0.0.1:8000/#growth"

echo.
echo  ------------------------------------------------------------
echo   DRIP OS      http://127.0.0.1:8000/
echo   New screens  #growth   (Home ^> Growth Operations)
echo                #signalreview  (Signal Command Center)
echo.
echo   If the page still looks old, press Ctrl+F5 in the browser --
echo   that forces a reload instead of using the cached page.
echo.
echo   This machine only. Close the "DRIP API" window to stop it.
echo  ------------------------------------------------------------
echo.
pause
