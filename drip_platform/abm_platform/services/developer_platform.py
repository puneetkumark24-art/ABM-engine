"""
developer_platform.py — Sprint 8: API keys + signed outbound webhooks.

API keys: generated as `dk_<prefix>_<secret>`, shown once, stored as sha256.
Webhooks: emit_event() fans an event out to matching active subscriptions as
pending WebhookDelivery rows; deliver_pending() signs each body (HMAC-SHA256),
POSTs via an injected sender (testable, no network in unit tests), and retries
with exponential backoff, dead-lettering after max_attempts.
"""
from __future__ import annotations
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
import models_s8 as m8

_BACKOFF_BASE_SECONDS = 60


# ── API keys ─────────────────────────────────────────────────
def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def create_api_key(db: Session, name: str, scopes: list[str] | None = None) -> dict:
    prefix = "dk_" + secrets.token_hex(3)
    secret = secrets.token_urlsafe(24)
    plaintext = f"{prefix}_{secret}"
    row = m8.ApiKey(name=name, prefix=prefix, key_hash=_hash(plaintext),
                    scopes=scopes or [])
    db.add(row); db.commit()
    # plaintext returned ONCE; never stored or logged
    return {"id": row.id, "prefix": prefix, "api_key": plaintext, "scopes": row.scopes}


def verify_api_key(db: Session, plaintext: str, now: datetime | None = None) -> m8.ApiKey | None:
    row = (db.query(m8.ApiKey)
           .filter_by(key_hash=_hash(plaintext), active=True).first())
    if row is None:
        return None
    row.last_used_at = now or datetime.utcnow()
    db.commit()
    return row


def revoke_api_key(db: Session, key_id: str) -> bool:
    row = db.get(m8.ApiKey, key_id)
    if row is None:
        return False
    row.active = False; db.commit()
    return True


# ── webhook subscriptions ────────────────────────────────────
def create_subscription(db: Session, url: str, event_types: list[str] | None = None,
                        secret: str | None = None) -> m8.WebhookSubscription:
    sub = m8.WebhookSubscription(url=url, event_types=event_types or [],
                                 secret=secret or secrets.token_hex(16))
    db.add(sub); db.commit()
    return sub


def sign_payload(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def emit_event(db: Session, event_type: str, payload: dict) -> int:
    """Create pending deliveries for every active subscription matching the event
    (empty event_types = subscribe-to-all). Returns number of deliveries queued."""
    import json
    subs = db.query(m8.WebhookSubscription).filter_by(active=True).all()
    n = 0
    for sub in subs:
        if sub.event_types and event_type not in sub.event_types:
            continue
        body = json.dumps({"event": event_type, "data": payload},
                          sort_keys=True).encode()
        d = m8.WebhookDelivery(subscription_id=sub.id, event_type=event_type,
                               payload=payload, signature=sign_payload(sub.secret, body),
                               status="pending", next_attempt_at=datetime.utcnow())
        db.add(d); n += 1
    db.commit()
    return n


def deliver_pending(db: Session, sender, now: datetime | None = None,
                    max_batch: int = 200) -> dict:
    """Attempt pending/failed-due deliveries. `sender(url, headers, body) -> int`
    returns an HTTP status code (2xx = success). Retries with backoff; dead-letters
    at max_attempts."""
    import json
    now = now or datetime.utcnow()
    due = (db.query(m8.WebhookDelivery)
           .filter(m8.WebhookDelivery.status.in_(("pending", "failed")),
                   m8.WebhookDelivery.next_attempt_at <= now)
           .limit(max_batch).all())
    delivered = failed = dead = 0
    for d in due:
        sub = db.get(m8.WebhookSubscription, d.subscription_id)
        if sub is None or not sub.active:
            d.status = "dead_letter"; d.last_error = "subscription missing/inactive"
            dead += 1; continue
        body = json.dumps({"event": d.event_type, "data": d.payload},
                          sort_keys=True).encode()
        headers = {"Content-Type": "application/json",
                   "X-DRIP-Signature": sign_payload(sub.secret, body),
                   "X-DRIP-Event": d.event_type, "X-DRIP-Delivery": d.id}
        d.attempts = (d.attempts or 0) + 1
        try:
            code = int(sender(sub.url, headers, body))
        except Exception as e:  # noqa: BLE001
            code = 0; d.last_error = f"{type(e).__name__}: {e}"
        d.response_code = code
        if 200 <= code < 300:
            d.status = "delivered"; d.next_attempt_at = None; delivered += 1
        elif d.attempts >= (d.max_attempts or 5):
            d.status = "dead_letter"; d.next_attempt_at = None; dead += 1
        else:
            d.status = "failed"
            d.next_attempt_at = now + timedelta(seconds=_BACKOFF_BASE_SECONDS * (2 ** (d.attempts - 1)))
            failed += 1
    db.commit()
    return {"processed": len(due), "delivered": delivered, "failed": failed,
            "dead_lettered": dead}
