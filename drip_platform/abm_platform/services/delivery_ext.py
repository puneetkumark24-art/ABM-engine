"""Delivery upgrades (Phase 12) — the deliverability behaviours the scorecard
flagged: an Amazon SES transport adapter (inert until credentials exist),
retry-with-backoff for failed sends, and Mailchimp's signature safety feature:
automatic campaign pause when bounce/complaint rates spike mid-send."""
from __future__ import annotations
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
import models_ext as mx
from . import delivery, deliverability
from abm_platform.events import Event, publish

# ── Amazon SES adapter (the recommended first real transport) ─
# Registers ONLY if boto3 + credentials + explicit env opt-in are all present.
# Until then the platform remains dry-run-only by construction.
SES_ENV_FLAG = "ENABLE_SES_TRANSPORT"          # must be "true"
SES_REGION_ENV = "AWS_SES_REGION"


def try_register_ses() -> tuple[bool, str]:
    import os
    if os.environ.get(SES_ENV_FLAG, "").lower() != "true":
        return False, f"{SES_ENV_FLAG} not set — staying dry-run (deliberate)"
    try:
        import boto3  # noqa: F401
    except ImportError:
        return False, "boto3 not installed"
    region = __import__("os").environ.get(SES_REGION_ENV, "me-south-1")

    def _ses_transport(req: "mx.SendRequest") -> str:
        import boto3
        client = boto3.client("sesv2", region_name=region)
        resp = client.send_email(
            FromEmailAddress=__import__("os").environ.get("SES_FROM", "noreply@example.invalid"),
            Destination={"ToAddresses": [req.to_email]},
            Content={"Simple": {"Subject": {"Data": req.subject or ""},
                                "Body": {"Html": {"Data": req.body or ""}}}})
        return resp["MessageId"]

    delivery.register_transport("ses", _ses_transport)
    return True, f"SES transport registered (region {region})"


# ── retry with backoff ───────────────────────────────────────
MAX_ATTEMPTS = 3
BACKOFF_MINUTES = [5, 30, 120]


def retry_failed(db: Session, now: datetime | None = None, limit: int = 50) -> dict:
    """Re-attempt failed sends with exponential backoff; give up after
    MAX_ATTEMPTS and leave a permanent failure record (never silently drop)."""
    now = now or datetime.utcnow()
    failed = (db.query(mx.SendRequest)
              .filter(mx.SendRequest.status == "failed",
                      mx.SendRequest.attempts < MAX_ATTEMPTS)
              .limit(limit).all())
    retried = succeeded = exhausted = 0
    for req in failed:
        wait = timedelta(minutes=BACKOFF_MINUTES[min(req.attempts - 1, len(BACKOFF_MINUTES) - 1)]) \
            if req.attempts > 0 else timedelta(0)
        base = req.sent_at or req.created_at or now
        if base + wait > now:
            continue
        fn = delivery._TRANSPORTS.get(req.transport)
        if fn is None:
            continue
        retried += 1
        try:
            provider_id = fn(req)
            req.status = "sent"; req.sent_at = now
            req.attempts += 1
            db.add(mx.DeliveryEvent(message_id=req.message_id, event_type="delivered",
                                    provider=req.transport,
                                    provider_event_id=f"{provider_id}:retry{req.attempts}"))
            succeeded += 1
        except Exception as e:
            req.attempts += 1
            req.detail = f"attempt {req.attempts}: {e}"
            if req.attempts >= MAX_ATTEMPTS:
                req.status = "failed"           # terminal
                exhausted += 1
                publish(Event("email.send.exhausted", key=req.message_id,
                              payload={"to": req.to_email}))
    db.commit()
    return {"retried": retried, "succeeded": succeeded, "exhausted": exhausted}


# ── mid-send auto-pause (Mailchimp's safety behaviour) ───────
PAUSE_BOUNCE_RATE = 0.05      # 5%
PAUSE_SPAM_RATE = 0.002       # 0.2%
MIN_SENDS_FOR_CHECK = 20


def check_campaign_health(db: Session, campaign_id: str) -> dict:
    """If a sending/sent campaign's bounce or complaint rate crosses the
    threshold, PAUSE it and alert — the platform protects the domain
    automatically, exactly like Mailchimp pausing high-bounce campaigns."""
    camp = db.get(mx.EmailCampaign, campaign_id)
    if camp is None:
        return {"error": "campaign not found"}
    msgs = db.query(mx.EmailMessage).filter_by(campaign_id=campaign_id).all()
    if len(msgs) < MIN_SENDS_FOR_CHECK:
        return {"checked": len(msgs), "action": "none", "reason": "below minimum sample"}
    ids = [m.id for m in msgs]
    events = (db.query(mx.DeliveryEvent)
              .filter(mx.DeliveryEvent.message_id.in_(ids)).all())
    bounced = len({e.message_id for e in events
                   if e.event_type in ("bounce", "hard_bounce")})
    spam = len({e.message_id for e in events
                if e.event_type in ("complaint", "spam")})
    n = len(msgs)
    bounce_rate, spam_rate = bounced / n, spam / n
    if bounce_rate > PAUSE_BOUNCE_RATE or spam_rate > PAUSE_SPAM_RATE:
        camp.status = "paused"
        db.commit()
        from . import notification
        notification.send(db, "Puneet", "anomaly",
                          payload={"campaign": camp.name,
                                   "bounce_rate": round(bounce_rate, 4),
                                   "spam_rate": round(spam_rate, 4)},
                          priority="urgent")
        publish(Event("email.campaign.autopaused", key=campaign_id,
                      payload={"bounce_rate": bounce_rate, "spam_rate": spam_rate}))
        return {"action": "paused", "bounce_rate": round(bounce_rate, 4),
                "spam_rate": round(spam_rate, 4)}
    return {"action": "none", "bounce_rate": round(bounce_rate, 4),
            "spam_rate": round(spam_rate, 4)}
