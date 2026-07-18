"""
scheduler_main.py — the beat loop (P0-B runtime).

Periodically, in one place, drives the autonomous engine:
  * enqueue due sequence steps  (fast; workers do the heavy AI/send)
  * relay the transactional outbox to the bus
  * retry failed sends (backoff)
  * fire scheduled email campaigns (KSA-window aware)
  * provision next month's event partition

Single instance (leader) — safe to run one replica. If you run more, the
SKIP-LOCKED claim + idempotent enqueue keep it correct, but one is intended.
"""
import os
import sys
import time
import traceback
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal, engine  # noqa: E402
from sqlalchemy import text  # noqa: E402
from abm_platform.services import orchestrator_async, jobs, delivery_ext, marketing_ext, pipeline_jobs  # noqa: E402

TICK = float(os.environ.get("SCHEDULER_TICK", "15"))
RESPECT_WINDOW = os.environ.get("RESPECT_SEND_WINDOW", "true").lower() == "true"


_EVENT_TABLES = ["metric_events", "delivery_events", "web_events"]


def _monthly_partition(db):
    """Provision current+next month partitions for every event firehose table
    (Postgres). Cheap + idempotent; keeps the partition runway ahead of time."""
    if engine.dialect.name != "postgresql":
        return
    try:
        for t in _EVENT_TABLES:
            db.execute(text("SELECT create_event_partition(:t, now()::date)"), {"t": t})
            db.execute(text("SELECT create_event_partition(:t, (now() + interval '1 month')::date)"), {"t": t})
        db.commit()
    except Exception:
        db.rollback()


_last_collect = None
_last_audit_purge = None
AUDIT_RETENTION_DAYS = int(os.environ.get("AUDIT_RETENTION_DAYS", "365"))


def _hourly_extras(db):
    """Final wave: pull due signal collectors (hourly) + purge expired audit
    rows (daily) — closing the 'refinery with no wells' and 'unbounded
    audit growth' audit findings inside the existing beat loop."""
    global _last_collect, _last_audit_purge
    now = datetime.utcnow()
    out = {}
    if _last_collect is None or (now - _last_collect).total_seconds() >= 3600:
        try:
            from abm_platform.services import collectors
            out["collectors"] = collectors.run_due(db).get("ran", 0)
            _last_collect = now
        except Exception:
            db.rollback()
    if _last_audit_purge is None or (now - _last_audit_purge).total_seconds() >= 86400:
        try:
            from abm_platform.services import security_compliance
            import models_audit
            out["audit_purged"] = security_compliance.purge_expired(
                db, models_audit.AuditEvent, "at", AUDIT_RETENTION_DAYS)
            _last_audit_purge = now
        except Exception:
            db.rollback()
    return out


def tick():
    db = SessionLocal()
    try:
        s = orchestrator_async.schedule_due_steps(db, respect_send_window=RESPECT_WINDOW)
        rl = pipeline_jobs.schedule_engagement_rollups(db)   # close the feedback loop async
        o = jobs.relay_outbox(db)
        r = delivery_ext.retry_failed(db)
        c = marketing_ext.run_scheduled(db, respect_send_window=RESPECT_WINDOW)
        _monthly_partition(db)
        ex = _hourly_extras(db)
        print(f"[scheduler] {datetime.utcnow().isoformat()} "
              f"due={s.get('due')} steps_enq={s.get('enqueued')} "
              f"rollups_enq={rl.get('enqueued')} "
              f"outbox={o.get('published')} retried={r.get('retried')} "
              f"campaigns_fired={c.get('fired')} extras={ex}", flush=True)
    finally:
        db.close()


def main():
    print(f"[scheduler] up; tick={TICK}s window={RESPECT_WINDOW}", flush=True)
    while True:
        try:
            tick()
        except Exception:
            traceback.print_exc()
        time.sleep(TICK)


if __name__ == "__main__":
    main()
