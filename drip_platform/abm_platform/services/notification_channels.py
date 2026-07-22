"""
notification_channels.py — real Slack + email channel adapters for
notification.py's `register_channel()` seam (AI Intelligence Layer Sprint
6). Same opt-in-flag discipline as delivery_ext.py's SES/Mandrill
adapters: every adapter here is inert until its env vars are explicitly
set, so the platform stays notification-safe (nothing external fires) by
construction until someone deliberately turns it on.

Slack: a single incoming-webhook URL (this is a single-operator platform
per the transformation Constitution — no per-user Slack OAuth needed for
v1). Email: reuses the EXISTING delivery.py send path (whatever transport
is currently registered there — dry_run by default, mandrill/ses if
opted in) rather than adding a third way to send an email; a notification
email is just another SendRequest.
"""
from __future__ import annotations
import os

import models_ext as mx
from . import notification, delivery

SLACK_ENV_FLAG = "SLACK_WEBHOOK_URL"
NOTIFY_EMAIL_ENV_FLAG = "ENABLE_EMAIL_NOTIFICATIONS"
NOTIFY_EMAIL_TO_ENV = "NOTIFY_EMAIL_TO"


def try_register_slack() -> tuple[bool, str]:
    webhook_url = os.environ.get(SLACK_ENV_FLAG)
    if not webhook_url:
        return False, f"{SLACK_ENV_FLAG} not set — staying inert (deliberate)"
    try:
        import httpx  # noqa: F401
    except ImportError:
        return False, "httpx not installed"

    def _slack_adapter(n: "mx.Notification") -> str:
        import httpx
        text = _format_for_slack(n)
        with httpx.Client(timeout=10) as client:
            r = client.post(webhook_url, json={"text": text})
        r.raise_for_status()
        return f"slack:{n.id}"

    notification.register_channel("slack", _slack_adapter)
    return True, "Slack channel adapter registered"


def try_register_email() -> tuple[bool, str]:
    if os.environ.get(NOTIFY_EMAIL_ENV_FLAG, "").lower() != "true":
        return False, f"{NOTIFY_EMAIL_ENV_FLAG} not set — staying inert (deliberate)"
    to_email = os.environ.get(NOTIFY_EMAIL_TO_ENV)
    if not to_email:
        return False, f"{NOTIFY_EMAIL_TO_ENV} not set"

    def _email_adapter(n: "mx.Notification") -> str:
        subject, body = _format_for_email(n)
        req = delivery.enqueue(
            _current_db(n), message_id=f"notify-{n.id}", to_email=to_email,
            subject=subject, body=body,
            transport=_active_email_transport(), respect_send_window=False,
        )
        if req.status not in ("sent",):
            raise RuntimeError(f"notification email not sent: status={req.status} detail={req.detail}")
        return req.message_id

    notification.register_channel("email", _email_adapter)
    return True, "Email channel adapter registered"


def _active_email_transport() -> str:
    """Notification emails ride whatever real transport delivery.py already
    has registered (mandrill/ses) — falls back to dry_run so registering
    this adapter is still safe even if no real transport is configured yet."""
    for name in ("mandrill", "ses"):
        if name in delivery._TRANSPORTS:
            return name
    return "dry_run"


def _current_db(n: "mx.Notification"):
    """The adapter signature is fn(notification) -> str per
    notification.register_channel's contract, but delivery.enqueue needs a
    live Session. SQLAlchemy attaches the owning Session to any object
    still in its identity map, which n always is here since send() calls
    the adapter immediately after committing n on the same Session."""
    from sqlalchemy.orm import object_session
    return object_session(n)


def _format_for_slack(n: "mx.Notification") -> str:
    payload = n.payload or {}
    return f"*[{n.kind}]* ({n.priority}) {payload}"


def _format_for_email(n: "mx.Notification") -> tuple[str, str]:
    payload = n.payload or {}
    subject = f"[Decimal DRIP] {n.kind} ({n.priority})"
    body = f"Notification: {n.kind}\nPriority: {n.priority}\nDetails: {payload}"
    return subject, body
