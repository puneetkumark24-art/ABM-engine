"""Deliverability engine — the part of Mailchimp nobody sees.
Domain health (DKIM/SPF/DMARC readiness), warmup schedule with daily caps,
rolling reputation from bounce/complaint rates, a can_send() volume gate for
real transports (dry_run bypasses it), and the full analytics rate card:
delivery/bounce/open/click/CTR/CTOR/spam/unsub/reply rates.

TRANSPORT RECOMMENDATION — REVISED, read before enabling SES
------------------------------------------------------------
This module previously recommended Amazon SES as the first real adapter on
cost + deliverability grounds. That holds for transactional mail. It does NOT
hold for the cold 1:1 B2B outreach this platform runs: SES, Mandrill,
SendGrid, Mailgun, Postmark and Resend all prohibit unsolicited/cold outreach
in their acceptable-use policies, because they share IP pools where one
tenant's complaints degrade every other tenant. SendGrid was already flagged
as an AUP violation earlier in this project.

Use a real Google Workspace / Microsoft 365 mailbox instead — see
`delivery_gmail.py`. Same register_transport() seam; nothing here changes.

One caveat that DOES change here: WARMUP_CAPS below tops out at 100k/day,
which is right for SES and far too high for a Workspace mailbox doing cold
outreach (practical ceiling ~40-50/day/mailbox, technical ~2,000). Cap the
domain's warmup_stage accordingly and let reputation govern, not the ladder."""
from __future__ import annotations
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
import models_ext as mx
import models_p11 as p11

# warmup: stage -> max sends/day (grows roughly 2x; stage 7 = effectively open)
WARMUP_CAPS = {1: 50, 2: 100, 3: 250, 4: 500, 5: 1000, 6: 2500, 7: 100000}
BOUNCE_ALERT = 0.05          # >5% bounces = reputation hit
COMPLAINT_ALERT = 0.002      # >0.2% complaints = serious


def ensure_domain(db: Session, domain: str) -> p11.DomainHealth:
    d = db.query(p11.DomainHealth).filter_by(domain=domain.lower()).first()
    if d is None:
        d = p11.DomainHealth(domain=domain.lower())
        db.add(d); db.commit()
    return d


def set_auth(db: Session, domain: str, dkim: bool, spf: bool, dmarc: bool) -> p11.DomainHealth:
    d = ensure_domain(db, domain)
    d.dkim_ok, d.spf_ok, d.dmarc_ok = dkim, spf, dmarc
    db.commit()
    return d


def _reset_if_new_day(d: p11.DomainHealth) -> None:
    if d.last_reset and datetime.utcnow() - d.last_reset > timedelta(days=1):
        d.sends_today = 0
        d.last_reset = datetime.utcnow()


def can_send(db: Session, domain: str, volume: int = 1) -> tuple[bool, str]:
    """The volume gate a REAL transport must pass (dry_run doesn't send, so it
    doesn't consume warmup budget). DEL rules: auth must be green; warmup cap
    enforced; poor reputation throttles."""
    d = ensure_domain(db, domain)
    _reset_if_new_day(d)
    if not (d.dkim_ok and d.spf_ok):
        return False, "domain auth not green (DKIM/SPF required)"
    if d.reputation < 0.3:
        return False, f"reputation too low ({d.reputation:.2f}) — pause & investigate"
    cap = WARMUP_CAPS.get(d.warmup_stage, 50)
    if d.sends_today + volume > cap:
        return False, f"warmup cap: stage {d.warmup_stage} allows {cap}/day, used {d.sends_today}"
    return True, f"ok (stage {d.warmup_stage}, {cap - d.sends_today - volume} left today)"


def consume(db: Session, domain: str, volume: int = 1) -> None:
    d = ensure_domain(db, domain)
    d.sends_today = (d.sends_today or 0) + volume
    db.commit()


def update_reputation(db: Session, domain: str) -> p11.DomainHealth:
    """Rolling reputation from the last 30 days of delivery events."""
    d = ensure_domain(db, domain)
    since = datetime.utcnow() - timedelta(days=30)
    events = (db.query(mx.DeliveryEvent)
              .filter(mx.DeliveryEvent.occurred_at >= since).all())
    delivered = sum(1 for e in events if e.event_type == "delivered") or 1
    bounces = sum(1 for e in events if e.event_type in ("bounce", "hard_bounce"))
    complaints = sum(1 for e in events if e.event_type in ("complaint", "spam"))
    d.bounce_rate = round(bounces / delivered, 4)
    d.complaint_rate = round(complaints / delivered, 4)
    rep = 0.9
    if d.bounce_rate > BOUNCE_ALERT:
        rep -= 0.3
    if d.complaint_rate > COMPLAINT_ALERT:
        rep -= 0.4
    if d.dkim_ok and d.spf_ok and d.dmarc_ok:
        rep += 0.1
    d.reputation = max(0.0, min(1.0, rep))
    # advance warmup one stage per clean day of >=50% cap usage
    cap = WARMUP_CAPS.get(d.warmup_stage, 50)
    if (d.sends_today >= cap * 0.5 and d.bounce_rate <= BOUNCE_ALERT
            and d.complaint_rate <= COMPLAINT_ALERT and d.warmup_stage < 7):
        d.warmup_stage += 1
    db.commit()
    return d


def rate_card(db: Session, campaign_id: str | None = None) -> dict:
    """The full analytics rate card. CTOR = clicks/opens; CTR = clicks/delivered."""
    mq = db.query(mx.EmailMessage)
    if campaign_id:
        mq = mq.filter_by(campaign_id=campaign_id)
    msgs = mq.all()
    ids = [m.id for m in msgs]
    events = (db.query(mx.DeliveryEvent)
              .filter(mx.DeliveryEvent.message_id.in_(ids)).all()) if ids else []

    sent = len(msgs) or 1
    by: dict[str, set] = {}
    for e in events:
        by.setdefault(e.event_type, set()).add(e.message_id)
    delivered = len(by.get("delivered", set()))
    opened = len(by.get("open", set()))
    clicked = len(by.get("click", set()))
    bounced = len(by.get("bounce", set()) | by.get("hard_bounce", set()))
    spam = len(by.get("complaint", set()) | by.get("spam", set()))
    unsub = len(by.get("unsub", set()))
    replied = sum(1 for m in msgs if m.status == "replied")

    def pct(n, d): return round(n / d * 100, 2) if d else 0.0
    return {
        "sent": sent if msgs else 0,
        "delivery_rate": pct(delivered, sent),
        "bounce_rate": pct(bounced, sent),
        "open_rate": pct(opened, max(delivered, 1)),
        "click_rate_ctr": pct(clicked, max(delivered, 1)),
        "ctor": pct(clicked, max(opened, 1)),
        "spam_rate": pct(spam, sent),
        "unsubscribe_rate": pct(unsub, sent),
        "reply_rate": pct(replied, sent),
        "note": "opens are approximate (image prefetch); clicks are reliable",
    }
