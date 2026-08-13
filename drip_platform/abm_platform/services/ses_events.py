"""Fail-closed translation of native Amazon SES event-publishing records."""
from __future__ import annotations
import hashlib

MAX_EVENTS = 1000
SUPPORTED = {"SEND", "DELIVERY", "OPEN", "CLICK", "BOUNCE", "COMPLAINT",
             "REJECT", "RENDERING_FAILURE", "DELIVERY_DELAY", "SUBSCRIPTION"}


def _first(value):
    return value[0] if isinstance(value, list) and value else value


def _canonical(event_type: str, item: dict) -> str | None:
    if event_type == "SEND": return "accepted"
    if event_type == "DELIVERY": return "delivered"
    if event_type == "OPEN": return "open"
    if event_type == "CLICK": return "click"
    if event_type == "COMPLAINT": return "complaint"
    if event_type == "REJECT": return "rejected"
    if event_type == "RENDERING_FAILURE": return "failed"
    if event_type == "DELIVERY_DELAY": return "soft_bounce"
    if event_type == "SUBSCRIPTION":
        status = str((item.get("subscription") or {}).get("newTopicPreferencesStatus", "")).upper()
        return "unsubscribe" if status == "OPT_OUT" else None
    if event_type == "BOUNCE":
        kind = str((item.get("bounce") or {}).get("bounceType", "")).lower()
        return "soft_bounce" if kind == "transient" else "hard_bounce"
    return None


def translate(payload, allow_provider_engagement: bool = False) -> tuple[list[dict], list[dict]]:
    items = payload if isinstance(payload, list) else [payload]
    if len(items) > MAX_EVENTS:
        raise OverflowError(f"SES event batch exceeds {MAX_EVENTS} items")
    accepted, rejected = [], []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            rejected.append({"index": index, "reason": "event is not an object"}); continue
        raw_type = str(item.get("eventType") or item.get("notificationType") or "").upper()
        mail = item.get("mail") if isinstance(item.get("mail"), dict) else {}
        provider_id = mail.get("messageId")
        tags = mail.get("tags") if isinstance(mail.get("tags"), dict) else {}
        message_id = _first(tags.get("drip_message_id"))
        canonical = _canonical(raw_type, item) if raw_type in SUPPORTED else None
        # DRIP already owns idempotent click redirects and open pixels. Ingesting
        # SES engagement as well would count the same human action twice. It is
        # opt-in only for deployments that deliberately disable DRIP tracking.
        if canonical in {"open", "click"} and not allow_provider_engagement:
            canonical = None
        if not provider_id:
            rejected.append({"index": index, "reason": "missing SES messageId"}); continue
        if not message_id:
            rejected.append({"index": index, "reason": "missing drip_message_id tag"}); continue
        if not canonical:
            rejected.append({"index": index, "reason": "unknown or non-actionable SES event"}); continue
        detail = item.get(raw_type.lower()) if isinstance(item.get(raw_type.lower()), dict) else {}
        timestamp = detail.get("timestamp") or mail.get("timestamp")
        fingerprint = hashlib.sha256(
            f"{provider_id}|{canonical}|{timestamp}|{detail.get('ipAddress','')}|"
            f"{detail.get('link','')}".encode()).hexdigest()[:32]
        # delivery.enqueue already records provider acceptance using the raw
        # SES MessageId. Reuse that id for SEND so event publishing deduplicates
        # it instead of inflating accepted counts.
        event_id = str(provider_id) if raw_type == "SEND" else f"ses:{fingerprint}"
        accepted.append({
            "id": event_id, "message_id": str(message_id),
            "provider_message_id": str(provider_id), "provider": "ses",
            "type": canonical, "ts": timestamp, "ses_event_type": raw_type,
            "diagnostic": (item.get("bounce") or {}).get("bouncedRecipients", []),
        })
    return accepted, rejected
