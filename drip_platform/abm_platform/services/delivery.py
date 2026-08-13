"""Module 11 — Email Delivery Engine: send queue + normalized event pipeline.
DEL-safety: the ONLY registered transport is dry_run — it records instead of
sending. Real SMTP/Mandrill adapters get registered here later, and even then
every enqueue passes the KSA send-window and suppression checks.
DEL-003: bounce/complaint => immediate suppression. Idempotent by message_id
and by provider_event_id on webhook ingest."""
from __future__ import annotations
from datetime import datetime, timedelta
from sqlalchemy import func
from sqlalchemy.orm import Session
import models_ext as mx
from sequences.send_window import is_within_send_window
from abm_platform.events import Event, publish
from .email_events import ALIASES, CANONICAL, normalize
from models_tenant import BOOTSTRAP_TENANT_ID

_TRANSPORTS = {}


class AmbiguousDeliveryError(RuntimeError):
    """Provider may have accepted the message; automatic retry could duplicate it."""


# Anything older than this is not a real delivery timestamp -- it is a unit
# scale error (milliseconds read as seconds), a placeholder, or a corrupted
# field. Accepting it silently drops the event out of every analytics window,
# so the event exists in the table and is invisible in every report.
_MIN_PLAUSIBLE_EVENT = datetime(2000, 1, 1)


def _provider_occurred_at(value) -> datetime:
    """Parse provider Unix/ISO timestamps; implausible values use receipt time."""
    now = datetime.utcnow()
    if isinstance(value, (int, float)):
        try:
            parsed = datetime.utcfromtimestamp(value)
        except (OverflowError, OSError, ValueError):
            return now
        if parsed < _MIN_PLAUSIBLE_EVENT or parsed > now + timedelta(days=1):
            return now
        return parsed
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(
                value.strip().replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return now
        if parsed < _MIN_PLAUSIBLE_EVENT or parsed > now + timedelta(days=1):
            return now
        return parsed
    return now


def register_transport(name: str, fn) -> None:
    """fn(send_request) -> provider_message_id (or raises)."""
    _TRANSPORTS[name] = fn


def _dry_run_transport(req: "mx.SendRequest") -> str:
    """Records the send; delivers nothing. This is the default and only
    built-in transport — no email can leave the system through it."""
    return f"dryrun-{req.message_id}"


register_transport("dry_run", _dry_run_transport)


def bind_provider_message(db: Session, provider: str, provider_message_id: str,
                          message_id: str, tenant_id: str | None = None) -> mx.ProviderMessageMap:
    """Create the PII-free provider routing record used by public webhooks."""
    from database import current_tenant_var
    tenant_id = tenant_id or current_tenant_var.get() or BOOTSTRAP_TENANT_ID
    existing = db.query(mx.ProviderMessageMap).filter_by(
        provider=provider, provider_message_id=str(provider_message_id)).first()
    if existing:
        if existing.message_id != message_id or existing.tenant_id != tenant_id:
            raise ValueError("provider message id is already bound to another message")
        return existing
    mapping = mx.ProviderMessageMap(provider=provider,
        provider_message_id=str(provider_message_id), message_id=message_id,
        tenant_id=tenant_id)
    db.add(mapping)
    return mapping


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
    if transport != "dry_run":
        # Establish a durable intent before crossing the network boundary. If
        # the process dies after provider acceptance, recovery sees `sending`
        # and does not automatically issue a duplicate live message.
        req.status = "sending"
        db.commit()
    try:
        provider_id = fn(req)
        req.status = "sent"; req.sent_at = datetime.utcnow(); req.attempts = 1
        req.provider_message_id = provider_id or None
        if transport != "dry_run" and provider_id:
            bind_provider_message(db, transport, provider_id, message_id)
        # A provider accepting a message is not proof that the recipient's MTA
        # delivered it.  Dry-run is explicitly marked synthetic; live adapters
        # wait for a provider webhook before recording ``delivered``.
        event_type = "simulated_delivered" if transport == "dry_run" else "accepted"
        req.detail = f"provider_message_id={provider_id}"
        db.add(mx.DeliveryEvent(message_id=message_id, event_type=event_type,
                                provider=transport, provider_event_id=provider_id,
                                meta={"synthetic": transport == "dry_run"}))
        publish(Event(f"email.event.{event_type}", key=message_id,
                      payload={"to": to_email}))
    except AmbiguousDeliveryError as e:
        req.status = "unknown"; req.detail = str(e); req.attempts = 1
    except Exception as e:
        req.status = "failed"; req.detail = str(e); req.attempts = 1
    db.commit()
    return req


def ingest_webhook(db: Session, events: list[dict]) -> dict:
    """Normalize provider events (Mandrill-shaped): [{id, message_id, type, ts}].
    Dedup by provider_event_id (webhook replays are no-ops).
    bounce/complaint/unsub => suppress + flip message status."""
    from . import marketing  # late import to avoid cycle
    accepted = duplicates = rejected = 0
    touched_orgs: set[str] = set()
    soft_bounce_emails: set[str] = set()
    seen_batch: set[str] = set()   # dedup within this batch (rows not yet committed)
    for ev in events:
        if not isinstance(ev, dict):
            rejected += 1
            continue
        message_id = ev.get("message_id")
        provider_message_id = ev.get("provider_message_id")
        if provider_message_id:
            route = (db.query(mx.ProviderMessageMap).filter_by(
                provider=ev.get("provider", "webhook"),
                provider_message_id=str(provider_message_id)).first())
            if route is None or (message_id and route.message_id != message_id):
                rejected += 1
                continue
            if db.bind.dialect.name == "postgresql":
                from sqlalchemy import text
                db.execute(text("SELECT set_config('app.current_tenant', :t, true)"),
                           {"t": route.tenant_id})
            message_id = route.message_id
            ev = {**ev, "message_id": message_id}
        etype = normalize(ev.get("type"))
        msg = db.query(mx.EmailMessage).filter_by(id=message_id).first() if message_id else None
        if msg is None or etype not in CANONICAL:
            rejected += 1
            continue
        pid = ev.get("id") or f"{ev.get('message_id')}:{ev.get('type')}:{ev.get('ts')}"
        if pid in seen_batch or db.query(mx.DeliveryEvent).filter_by(provider_event_id=pid).first():
            duplicates += 1
            continue
        seen_batch.add(pid)
        de = mx.DeliveryEvent(message_id=ev.get("message_id"), event_type=etype,
                              provider=ev.get("provider", "webhook"),
                              provider_event_id=pid, meta=ev,
                              occurred_at=_provider_occurred_at(ev.get("ts")))
        db.add(de); accepted += 1

        if msg:
            de.meta = {**ev, "to": ev.get("to") or msg.to_email}
            person = db.get(__import__("models").Person, msg.person_id)
            if person and person.current_org_id:
                touched_orgs.add(person.current_org_id)
            if etype == "accepted":
                msg.status = "sent"
            elif etype == "delivered":
                msg.status = "delivered"
            elif etype == "open":
                msg.status = "opened"
            elif etype == "click":
                msg.status = "clicked"
            elif etype == "soft_bounce":
                msg.status = "bounced"
                if msg.to_email:
                    soft_bounce_emails.add(msg.to_email.lower())
            elif etype == "hard_bounce":
                msg.status = "bounced"
                if msg.to_email:
                    marketing.suppress(db, msg.to_email, reason="hard_bounce")
                if person:
                    person.do_not_contact = True
            elif etype == "complaint":
                msg.status = "complained"
                if msg.to_email:
                    marketing.suppress(db, msg.to_email, reason="complaint")
                if person:
                    person.do_not_contact = True
                    person.consent_status = "denied"
            elif etype == "unsubscribe":
                msg.status = "unsub"
                if msg.to_email:
                    marketing.suppress(db, msg.to_email, reason="unsub")
                if person:
                    person.do_not_contact = True
                    person.consent_status = "denied"
        publish(Event(f"email.event.{etype}", key=ev.get("message_id"), payload=ev))
    # Evaluate after the entire provider batch is flushed; otherwise the third
    # event can be invisible depending on SQLAlchemy's flush timing.
    db.flush()
    for email in soft_bounce_emails:
        if _soft_bounce_count(db, email) >= 3:
            marketing.suppress(db, email, reason="repeated_soft_bounce")
    db.commit()
    from . import engagement
    for org_id in touched_orgs:
        engagement.rollup_org(db, org_id)
    return {"accepted": accepted, "duplicates": duplicates,
            "rejected": rejected, "accounts_rescored": len(touched_orgs)}


# Every raw provider value that normalizes to soft_bounce. Kept explicit so the
# count can be done in SQL: the packaged implementation loaded EVERY delivery
# event from the last 30 days into Python and filtered in a loop, once per
# soft-bounced address in the batch. At this platform's stated scale (30,000+
# contacts) one bad campaign pulls hundreds of thousands of rows into memory to
# answer "has this one address bounced three times".
_SOFT_BOUNCE_RAW = tuple(sorted(
    raw for raw, canon in ALIASES.items() if canon == "soft_bounce"))


def _soft_bounce_count(db: Session, email: str) -> int:
    """Normalized soft bounces for an address in the last 30 days.

    Joined to email_messages on message_id rather than reading meta->>'to':
    the address on the message is authoritative, it is indexed (migration
    u8a0b2c4d6e7), and it still works for events whose provider payload
    omitted the recipient.
    """
    since = datetime.utcnow() - timedelta(days=30)
    return (db.query(mx.DeliveryEvent.id)
            .join(mx.EmailMessage, mx.EmailMessage.id == mx.DeliveryEvent.message_id)
            .filter(mx.DeliveryEvent.occurred_at >= since,
                    func.lower(mx.EmailMessage.to_email) == (email or "").lower(),
                    func.lower(mx.DeliveryEvent.event_type).in_(_SOFT_BOUNCE_RAW))
            .count())


def message_events(db: Session, message_id: str) -> list[dict]:
    evs = db.query(mx.DeliveryEvent).filter_by(message_id=message_id).order_by(mx.DeliveryEvent.occurred_at).all()
    return [{"type": e.event_type, "provider": e.provider, "at": e.occurred_at} for e in evs]
