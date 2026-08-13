"""Mailchimp Transactional (Mandrill) webhook translation.

This module only receives provider receipts; it does not register or activate
an outbound transport. Mapping is deliberately fail-closed: an event must carry
DRIP's own message id in ``msg.metadata.drip_message_id``.
"""
from __future__ import annotations
import hashlib

from .email_events import CANONICAL, normalize

MAX_EVENTS = 1000


def translate(payload) -> tuple[list[dict], list[dict]]:
    """Return canonical events and rejected-item explanations."""
    if not isinstance(payload, list):
        raise ValueError("mandrill_events must be a JSON list")
    if len(payload) > MAX_EVENTS:
        raise OverflowError(f"mandrill event batch exceeds {MAX_EVENTS} items")
    accepted, rejected = [], []
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            rejected.append({"index": index, "reason": "event is not an object"})
            continue
        msg = item.get("msg") if isinstance(item.get("msg"), dict) else {}
        metadata = msg.get("metadata") if isinstance(msg.get("metadata"), dict) else {}
        message_id = metadata.get("drip_message_id")
        event_type = normalize(item.get("event"))
        provider_message_id = msg.get("_id")
        if not message_id:
            rejected.append({"index": index, "reason": "missing drip_message_id metadata"})
            continue
        if event_type not in CANONICAL:
            rejected.append({"index": index, "reason": "unknown event type"})
            continue
        if not provider_message_id:
            rejected.append({"index": index, "reason": "missing provider message id"})
            continue
        ts = item.get("ts") if item.get("ts") is not None else (msg.get("ts") or "")
        url = item.get("url") or ""
        fingerprint = hashlib.sha256(
            f"{provider_message_id}|{event_type}|{ts}|{url}|{item.get('ip') or ''}|"
            f"{item.get('user_agent') or ''}".encode()).hexdigest()[:24]
        accepted.append({
            "id": f"mandrill:{fingerprint}",
            "message_id": str(message_id),
            "type": event_type,
            "ts": ts,
            "to": msg.get("email"),
            "provider": "mandrill",
            "provider_message_id": provider_message_id,
            "url": url or None,
            "user_agent": item.get("user_agent"),
            "ip": item.get("ip"),
        })
    return accepted, rejected
