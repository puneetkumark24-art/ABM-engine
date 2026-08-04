@echo off
REM ============================================================
REM DRIP Signal Engine v2 -- autonomous capture + decipher cycle
REM ============================================================
REM Runs the full shadow-mode pipeline unattended:
REM   -1. catalog-sync     -- read every active organization from the REAL
REM                            Postgres database and add any NOT already one
REM                            of the original static 11 banks as a
REM                            signal_engine account (scripts\signal_v2_catalog_sync.py).
REM                            This is what lets the engine scale past 11
REM                            institutions toward 500+ -- add a bank to the
REM                            real `organizations` table once, and it shows
REM                            up here automatically on the next cycle.
REM    0a. watch-seed-official -- give every account (including newly synced
REM                            ones) a default official-site homepage watch.
REM    0b. watch-import     -- (re)load config\verified_watch_targets.csv, so
REM                            any new bank newsroom/careers/procurement URL
REM                            added to that file is picked up automatically
REM                            on the next run, with no manual step needed.
REM                            Idempotent -- re-importing existing rows is a
REM                            harmless no-op (ON CONFLICT DO UPDATE).
REM   1. watch-check-all   -- re-check all watched pages, record page_changed
REM                            observations for anything that actually changed
REM   2. collect-live      -- pull enabled live RSS/news/regulator sources
REM   3. capture-audit     -- refresh 360-degree coverage gap alerts
REM   4. quality-backfill  -- score any observation missing a quality record
REM   5. quality-audit     -- recompute the quality-calibration gate
REM   6. capture-coverage  -- snapshot the 360 coverage numbers into the log
REM
REM This does NOT export anything into the real Postgres `signals` table and
REM does NOT touch outreach/sequences/SendGrid in any way -- promotion out of
REM the shadow database stays a deliberate, human-run step
REM (scripts\signal_v2_export_cli.py --apply), unchanged from the original
REM integration boundary. This script only fills the shadow review queue.
REM
REM Safe to run unattended and safe to run concurrently with the API server --
REM it only touches signal_engine.db, never Postgres.
REM ============================================================

setlocal
cd /d "%~dp0.."

if not exist logs mkdir logs
set LOGFILE=logs\signal_pipeline.log

echo. >> "%LOGFILE%"
echo ==================================================================== >> "%LOGFILE%"
echo RUN START %date% %time% >> "%LOGFILE%"
echo ==================================================================== >> "%LOGFILE%"

echo [-1/6] catalog-sync (Postgres organizations -^> signal_engine accounts) >> "%LOGFILE%"
python scripts\signal_v2_catalog_sync.py >> "%LOGFILE%" 2>&1

echo [0a/6] watch-seed-official (homepage watch for every account) >> "%LOGFILE%"
python -m signal_engine.cli watch-seed-official >> "%LOGFILE%" 2>&1

echo [0b/6] watch-import (refresh from config\verified_watch_targets.csv) >> "%LOGFILE%"
python -m signal_engine.cli watch-import --file config\verified_watch_targets.csv >> "%LOGFILE%" 2>&1

echo [1/6] watch-check-all >> "%LOGFILE%"
python -m signal_engine.cli watch-check-all >> "%LOGFILE%" 2>&1

echo [2/6] collect-live >> "%LOGFILE%"
python -m signal_engine.cli collect-live >> "%LOGFILE%" 2>&1

echo [3/6] capture-audit >> "%LOGFILE%"
python -m signal_engine.cli capture-audit >> "%LOGFILE%" 2>&1

echo [4/6] quality-backfill >> "%LOGFILE%"
python -m signal_engine.cli quality-backfill >> "%LOGFILE%" 2>&1

echo [5/6] quality-audit >> "%LOGFILE%"
python -m signal_engine.cli quality-audit >> "%LOGFILE%" 2>&1

echo [6/6] capture-coverage >> "%LOGFILE%"
python -m signal_engine.cli capture-coverage >> "%LOGFILE%" 2>&1

echo RUN END %date% %time% >> "%LOGFILE%"

endlocal
