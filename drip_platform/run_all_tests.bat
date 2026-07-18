@echo off
REM run_all_tests.bat — runs every suite in its OWN python process.
REM Needed because several suites pin their own DATABASE_URL at import time;
REM a single shared pytest process caches the first one and corrupts the rest.
setlocal enabledelayedexpansion
cd /d "%~dp0"
set PASS=0
set FAIL=0
set FAILED=
for %%f in (tests\test_*.py) do (
    echo ================ %%f ================
    python "%%f"
    if !errorlevel! neq 0 (
        set /a FAIL+=1
        set FAILED=!FAILED! %%f
    ) else (
        set /a PASS+=1
    )
)
echo.
echo ==========================================
echo   Suites passed: %PASS%   failed: %FAIL%
if defined FAILED echo   Failing:%FAILED%
echo ==========================================
endlocal
