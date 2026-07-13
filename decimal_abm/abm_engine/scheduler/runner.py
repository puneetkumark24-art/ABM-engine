"""
abm_engine/scheduler/runner.py
────────────────────────────────
All scheduled jobs.

Jobs:
  Every 1h    → Quick intelligence check (SAMA + leadership)
  Every 6h    → Full intelligence check (all sources)
  Daily 9AM   → Generate drafts for contacts due outreach
  Every 30min → Send approved drafts (after human review)
  Every 15min → Reply check + human alert (WhatsApp + Email)
  Monday 8AM  → Scoring re-run + weekly KPI report
"""
from __future__ import annotations
import os, signal, sys
from datetime import datetime
from pathlib import Path
from loguru import logger
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron       import CronTrigger
from dotenv import load_dotenv

# Explicit path — see abm_engine/__main__.py for why plain load_dotenv() doesn't work here.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from ..database.db        import init_db, get_unnotified_events, mark_events_notified
from ..core.orchestrator  import Orchestrator, _make_notifier
from ..signals.monitor    import SignalMonitor
from ..scoring.engine     import ScoringEngine
from ..reporting.kpi      import KPIReporter


def job_signal_quick():
    logger.info("⏰ Quick intelligence check")
    try:
        result = SignalMonitor(os.environ.get("ANTHROPIC_API_KEY","")).run_quick()
        if result.get("total",0) > 0:
            from ..database.db import get_recent_signals
            if any(s["priority"]=="P1" for s in get_recent_signals(hours=1)):
                job_scoring()
    except Exception as e:
        logger.error("Quick intelligence check failed: {}", e)


def job_signal_full():
    logger.info("⏰ Full intelligence check")
    try:
        SignalMonitor(os.environ.get("ANTHROPIC_API_KEY","")).run_full()
    except Exception as e:
        logger.error("Full intelligence check failed: {}", e)


def job_generate_drafts():
    logger.info("⏰ Draft generation job")
    try:
        Orchestrator().generate_drafts()
    except Exception as e:
        logger.exception("Draft generation crashed: {}", e)
        _make_notifier().engine_error(str(e))


def job_send_approved():
    """Runs every 30 min — sends drafts approved in the dashboard."""
    try:
        result = Orchestrator().send_approved_drafts()
        if result.get("sent",0) > 0:
            logger.info("Sent {} approved drafts", result["sent"])
    except Exception as e:
        logger.error("Send approved drafts failed: {}", e)


def job_reply_check():
    events = get_unnotified_events()
    if not events:
        return
    notifier   = _make_notifier()
    notify_ids = []
    for ev in events:
        if ev["event_type"] in ("email_reply","linkedin_reply"):
            notifier.reply_received(
                contact_name  = ev.get("full_name","Unknown"),
                institution   = ev.get("institution",""),
                role          = ev.get("role",""),
                touch_number  = ev.get("touch_id",0),
                channel       = "email" if "email" in ev["event_type"] else "linkedin",
                reply_snippet = (ev.get("raw_content") or "")[:300],
            )
        notify_ids.append(ev["id"])
    mark_events_notified(notify_ids)


def job_scoring():
    try:
        ScoringEngine().run()
    except Exception as e:
        logger.error("Scoring failed: {}", e)


def job_weekly_report():
    try:
        KPIReporter().run()
    except Exception as e:
        logger.error("Weekly report failed: {}", e)


def start_scheduler():
    init_db()
    start_hour   = int(os.environ.get("SCHEDULER_START_HOUR", 9))
    start_minute = int(os.environ.get("SCHEDULER_START_MINUTE", 0))
    tz           = os.environ.get("SCHEDULER_TIMEZONE", "Asia/Riyadh")

    scheduler = BlockingScheduler(timezone=tz)

    scheduler.add_job(job_signal_quick, CronTrigger(minute=0),
        id="signal_quick", misfire_grace_time=3600)
    scheduler.add_job(job_signal_full, CronTrigger(hour="0,6,12,18"),
        id="signal_full",  misfire_grace_time=3600)
    scheduler.add_job(job_generate_drafts, CronTrigger(hour=start_hour, minute=start_minute),
        id="generate_drafts", misfire_grace_time=3600)
    scheduler.add_job(job_send_approved, CronTrigger(minute="*/30"),
        id="send_approved")
    scheduler.add_job(job_reply_check, CronTrigger(minute="*/15"),
        id="reply_check")
    scheduler.add_job(job_scoring, CronTrigger(day_of_week="mon", hour=8),
        id="scoring", misfire_grace_time=3600)
    scheduler.add_job(job_weekly_report, CronTrigger(day_of_week="mon", hour=8, minute=5),
        id="weekly_report", misfire_grace_time=3600)

    def shutdown(signum, frame):
        scheduler.shutdown(); sys.exit(0)
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    logger.info("ABM Engine scheduler started | Drafts generated: {:02d}:{:02d} {} | Sends: every 30min | Intelligence: every hour",
        start_hour, start_minute, tz)
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")
