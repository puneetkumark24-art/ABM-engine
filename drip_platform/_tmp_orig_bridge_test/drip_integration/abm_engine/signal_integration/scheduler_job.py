from __future__ import annotations

import os
from pathlib import Path


def job_signal_v2_collect() -> dict:
    """Signal-only job. It cannot import or invoke DRIP delivery code."""
    from signal_engine.cli import main

    signal_db = Path(os.environ.get("SIGNAL_V2_DB", "signal_engine.db"))
    return_code = main(["--db", str(signal_db), "collect-live"])
    return {"ok": return_code == 0, "return_code": return_code, "db": str(signal_db)}


def register_signal_jobs(scheduler) -> None:
    """Register only collection; caller owns scheduler lifecycle/timezone."""
    from apscheduler.triggers.cron import CronTrigger

    scheduler.add_job(
        job_signal_v2_collect,
        CronTrigger(hour="0,6,12,18"),
        id="signal_v2_collect",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        job_capture_page_watches,
        CronTrigger(minute="*/30"),
        id="signal_v2_page_watches",
        replace_existing=True,
        misfire_grace_time=1800,
    )


def job_capture_page_watches() -> dict:
    """Poll only explicitly configured public watch URLs."""
    from signal_engine.capture import CaptureService
    from signal_engine.cli import fetch_public_feed
    from signal_engine.db import connect, initialize

    signal_db = Path(os.environ.get("SIGNAL_V2_DB", "signal_engine.db"))
    con = connect(signal_db)
    initialize(con)
    capture = CaptureService(con)
    results = []
    for row in con.execute("SELECT id,url FROM page_watch_targets WHERE enabled=1 ORDER BY id").fetchall():
        try:
            results.append({"id": row["id"], "ok": True, **capture.record_page(row["id"], fetch_public_feed(row["url"]))})
        except Exception as exc:
            con.execute("UPDATE page_watch_targets SET last_error=? WHERE id=?", (str(exc)[:500], row["id"]))
            con.commit()
            results.append({"id": row["id"], "ok": False, "error": str(exc)})
    con.close()
    return {"checked": len(results), "results": results}
