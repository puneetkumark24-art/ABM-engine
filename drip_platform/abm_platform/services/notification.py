"""Module 21 — Notification Engine: in-app inbox + preferences + quiet hours.
NOT-001: quiet hours respected for non-urgent. NOT-002: urgent bypasses.
Channel adapters beyond in_app (Slack/WhatsApp/email) plug in later behind
the same send() surface."""
from __future__ import annotations
from datetime import datetime
from sqlalchemy.orm import Session
import models_ext as mx


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
