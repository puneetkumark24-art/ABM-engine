"""Module 11 — Email Delivery Engine: send queue + normalized event pipeline.
DEL-safety: the ONLY registered transport is dry_run — it records instead of
sending. Real SMTP/Mandrill adapters get registered here later, and even then
every enqueue passes the KSA send-window and suppression checks.
DEL-003: bounce/complaint => immediate suppression. Idempotent by message_id
and by provider_event_id on webhook ingest."""
from __future__ import annotations
from datetime import datetime
from sqlalchemy.orm import Session
import models_ext as mx
from sequences.send_window import is_within_send_window
from abm_platform.events import Event, publish

_TRANSPORTS = {}


def register_transport(name: str, fn) -> None:
    """fn(send_request) -> provider_message_id (or raises)."""
    _TRANSPORTS[name] = fn


def _dry_run_transport(req: "mx.SendRequest") -> str:
    """Records the send; delivers nothing. This is the default and only
    built-in transport — no email can leave the system through it."""
    return f"dryrun-{req.message_id}"


register_transport("dry_run", _dry_run_transport)


def enqueue(db: Session, message_id: str, to_email: str, subject: str, body: str,
            transport: str = "dry_run", respect_send_window: bool = False) -> mx.SendRequest:
    """Idempotent by message_id. respect_send_window defaults False for dry_run
    (nothing real is sent); real transports must pass True."""
    existing = db.query(mx.SendRequest).filter_by(message_id=message_id).first()
    if existing:
        return existing

    req = mx.SendRequest(message_id=message_id, to_email=to_email,
                         subject=subject, body=body, transport=transport)
    if transport != "dry_run" and respect_send_window:
        allowed, reason = is_within_send_window()
        if not allowed:
            req.status = "blocked"; req.detail = f"send window: {reason}"
            db.add(req); db.commit()
            return req

    fn = _TRANSPORTS.get(transport)
    if fn is None:
        req.status = "failed"; req.detail = f"unknown transport {transport}"
        db.add(req); db.commit()
        return req

    db.add(req); db.flush()
    try:
        provider_id = fn(req)
        req.status = "sent"; req.sent_at = datetime.utcnow(); req.attempts = 1
        db.add(mx.DeliveryEvent(message_id=message_id, event_type="delivered",
                                provider=transport, provider_event_id=provider_id))
        publish(Event("email.event.delivered", key=message_id, payload={"to": to_email}))
    except Exception as e:
        req.status = "failed"; req.detail = str(e); req.attempts = 1
    db.commit()
    return req


def ingest_webhook(db: Session, events: list[dict]) -> dict:
    """Normalize provider events (Mandrill-shaped): [{id, message_id, type, ts}].
    Dedup by provider_event_id (webhook replays are no-ops).
    bounce/complaint/unsub => suppress + flip message status."""
    from . import marketing  # late import to avoid cycle
    accepted = duplicates = 0
    seen_batch: set[str] = set()   # dedup within this batch (rows not yet committed)
    for ev in events:
        pid = ev.get("id") or f"{ev.get('message_id')}:{ev.get('type')}:{ev.get('ts')}"
        if pid in seen_batch or db.query(mx.DeliveryEvent).filter_by(provider_event_id=pid).first():
            duplicates += 1
            continue
        seen_batch.add(pid)
        etype = ev.get("type", "delivered")
        de = mx.DeliveryEvent(message_id=ev.get("message_id"), event_type=etype,
                              provider=ev.get("provider", "webhook"),
                              provider_event_id=pid, meta=ev)
        db.add(de); accepted += 1

        msg = db.query(mx.EmailMessage).filter_by(id=ev.get("message_id")).first()
        if msg:
            if etype in ("open",):
                msg.status = "opened"
            elif etype in ("click",):
                msg.status = "clicked"
            elif etype in ("bounce", "hard_bounce"):
                msg.status = "bounced"
                if msg.to_email:
                    marketing.suppress(db, msg.to_email, reason="bounce")
            elif etype in ("complaint", "spam"):
                msg.status = "complained"
                if msg.to_email:
                    marketing.suppress(db, msg.to_email, reason="complaint")
            elif etype in ("unsub",):
                msg.status = "unsub"
                if msg.to_email:
                    marketing.suppress(db, msg.to_email, reason="unsub")
        publish(Event(f"email.event.{etype}", key=ev.get("message_id"), payload=ev))
    db.commit()
    return {"accepted": accepted, "duplicates": duplicates}


def message_events(db: Session, message_id: str) -> list[dict]:
    evs = db.query(mx.DeliveryEvent).filter_by(message_id=message_id).order_by(mx.DeliveryEvent.occurred_at).all()
    return [{"type": e.event_type, "provider": e.provider, "at": e.occurred_at} for e in evs]
