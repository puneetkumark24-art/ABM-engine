"""Module 17 — Analytics Engine: event-sourced metrics.
ANL-002: rollups are reproducible from metric_events. Subscribes to the bus so
every platform event lands in the metric store automatically."""
from __future__ import annotations
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
import models_ext as mx
from abm_platform import events as bus_mod
from database import SessionLocal

_WIRED = False


def ingest(db: Session, event_type: str, subject_type: str | None = None,
           subject_id: str | None = None, props: dict | None = None,
           occurred_at: datetime | None = None) -> mx.MetricEvent:
    me = mx.MetricEvent(event_type=event_type, subject_type=subject_type,
                        subject_id=subject_id, props=props or {},
                        occurred_at=occurred_at or datetime.utcnow())
    db.add(me); db.commit()
    return me


def wire_to_bus(event_types: list[str] | None = None) -> None:
    """Subscribe an ingester to the platform event bus. Each event becomes a
    metric_event in its own short-lived session (bus handlers must not share
    the caller's transaction)."""
    global _WIRED
    if _WIRED:
        return
    types = event_types or [
        "signal.created", "email.campaign.sent", "email.event.delivered",
        "email.event.open", "email.event.click", "email.event.bounce",
        "form.submitted", "linkedin.action.sent", "linkedin.reply.received",
        "email.suppressed",
    ]

    def handler(ev: "bus_mod.Event"):
        s = SessionLocal()
        try:
            ingest(s, ev.type, subject_id=ev.key, props=ev.payload,
                   occurred_at=ev.occurred_at)
        finally:
            s.close()

    for t in types:
        bus_mod.subscribe(t, handler)
    _WIRED = True


def query(db: Session, event_type: str | None = None, since_days: int = 30,
          group_by: str = "event_type") -> dict:
    """Counts grouped by event_type or day. Reproducible from raw events."""
    since = datetime.utcnow() - timedelta(days=since_days)
    q = db.query(mx.MetricEvent).filter(mx.MetricEvent.occurred_at >= since)
    if event_type:
        q = q.filter(mx.MetricEvent.event_type == event_type)
    rows = q.all()
    out: dict[str, int] = {}
    for r in rows:
        key = r.event_type if group_by == "event_type" else r.occurred_at.strftime("%Y-%m-%d")
        out[key] = out.get(key, 0) + 1
    return {"since_days": since_days, "total": len(rows), "groups": out}


def funnel(db: Session, steps: list[str], since_days: int = 30) -> list[dict]:
    """Simple funnel: distinct subjects reaching each step's event type."""
    since = datetime.utcnow() - timedelta(days=since_days)
    result = []
    prev = None
    for step in steps:
        subjects = {r.subject_id for r in db.query(mx.MetricEvent)
                    .filter(mx.MetricEvent.event_type == step,
                            mx.MetricEvent.occurred_at >= since).all() if r.subject_id}
        conv = (len(subjects) / prev * 100.0) if prev else 100.0
        result.append({"step": step, "count": len(subjects), "conversion_pct": round(conv, 1)})
        prev = len(subjects) or 1
    return result
