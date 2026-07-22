"""Module 21 — Notification Engine: in-app inbox + preferences + quiet hours.
NOT-001: quiet hours respected for non-urgent. NOT-002: urgent bypasses.

AI Intelligence Layer Sprint 6 wires the "Channel adapters beyond in_app
plug in later" promise this docstring always made: send() now dispatches
to a registered external channel adapter (Slack, email) when one exists
for the requested channel, using the exact same pluggable-adapter
convention as every other seam in this codebase (delivery.register_transport,
ai_gen.register_model, llm_core's provider adapters) — register_channel()
below, inert by default. The in_app row is ALWAYS written first and stays
the source of truth (the inbox never depends on an external channel
succeeding); external delivery outcome is recorded in payload['_external']
rather than a schema migration, since it's diagnostic metadata, not a new
first-class fact about the notification."""
from __future__ import annotations
from datetime import datetime
from sqlalchemy.orm import Session
import models_ext as mx

# pluggable channel adapters: name -> fn(notification) -> provider_ref (str, raises on failure)
_CHANNEL_ADAPTERS: dict[str, object] = {}


def register_channel(name: str, fn) -> None:
    _CHANNEL_ADAPTERS[name] = fn


def get_prefs(db: Session, user: str) -> mx.NotifyPref:
    p = db.query(mx.NotifyPref).filter_by(user=user).first()
    if p is None:
        p = mx.NotifyPref(user=user)
        db.add(p); db.commit()
    return p


def set_quiet_hours(db: Session, user: str, start_hour: int, end_hour: int) -> mx.NotifyPref:
    p = get_prefs(db, user)
    p.quiet_hours = {"start": start_hour, "end": end_hour}
    db.commit()
    return p


def _in_quiet_hours(prefs: mx.NotifyPref, now: datetime | None = None) -> bool:
    qh = prefs.quiet_hours or {}
    if "start" not in qh:
        return False
    h = (now or datetime.utcnow()).hour
    s, e = qh["start"], qh["end"]
    return (s <= h or h < e) if s > e else (s <= h < e)


def send(db: Session, user: str, kind: str, payload: dict | None = None,
         channel: str = "in_app", priority: str = "med",
         now: datetime | None = None) -> mx.Notification:
    prefs = get_prefs(db, user)
    n = mx.Notification(user=user, kind=kind, channel=channel,
                        payload=payload or {}, priority=priority)
    if priority != "urgent" and _in_quiet_hours(prefs, now):   # NOT-001/002
        n.status = "pending"        # held; a digest/flush job delivers later
    else:
        n.status = "sent"
    db.add(n); db.commit()

    # external channel dispatch — best-effort, never blocks the in_app write
    # above (which already committed) and never raises out of send().
    if n.status == "sent" and channel != "in_app":
        fn = _CHANNEL_ADAPTERS.get(channel)
        if fn is None:
            n.payload = {**(n.payload or {}), "_external": {"delivered": False, "reason": f"no adapter registered for '{channel}'"}}
        else:
            try:
                ref = fn(n)
                n.payload = {**(n.payload or {}), "_external": {"delivered": True, "provider_ref": ref}}
            except Exception as e:  # noqa: BLE001
                n.payload = {**(n.payload or {}), "_external": {"delivered": False, "reason": str(e)[:300]}}
        db.add(n); db.commit()
    return n


def inbox(db: Session, user: str, unread_only: bool = False) -> list[mx.Notification]:
    q = db.query(mx.Notification).filter_by(user=user)
    if unread_only:
        q = q.filter(mx.Notification.status.in_(["sent", "pending"]))
    return q.order_by(mx.Notification.created_at.desc()).all()


def mark_read(db: Session, notification_id: str) -> mx.Notification:
    n = db.get(mx.Notification, notification_id)
    if n:
        n.status = "read"; n.read_at = datetime.utcnow(); db.commit()
    return n


def flush_pending(db: Session, user: str) -> int:
    """Deliver held (quiet-hours) notifications — call from a morning tick."""
    held = db.query(mx.Notification).filter_by(user=user, status="pending").all()
    for n in held:
        n.status = "sent"
    db.commit()
    return len(held)
