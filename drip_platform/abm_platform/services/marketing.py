"""Module 07 — Marketing Automation (Mailchimp replica core): audiences
(static + dynamic), suppression, campaigns, per-recipient messages.
MKT-001: every send checks suppression AND consent/do_not_contact at send time.
MKT-004: sends route through the delivery engine (dry-run by default) and the
KSA send-window is the delivery layer's concern (sequences.send_window)."""
from __future__ import annotations
from datetime import datetime
import uuid
from sqlalchemy.orm import Session
import models
import models_ext as mx
from . import delivery, marketing_ext, attribution, engagement
from abm_platform.events import Event, publish

_OPS = {
    "eq": lambda a, b: a == b, "ne": lambda a, b: a != b,
    "contains": lambda a, b: b.lower() in (a or "").lower() if isinstance(a, str) else False,
    "gt": lambda a, b: (a or 0) > b, "gte": lambda a, b: (a or 0) >= b,
    "lt": lambda a, b: (a or 0) < b, "lte": lambda a, b: (a or 0) <= b,
    "is_true": lambda a, b: bool(a), "is_false": lambda a, b: not bool(a),
}


def create_audience(db: Session, name: str, kind: str = "list", definition: list | None = None) -> mx.Audience:
    aud = mx.Audience(name=name, kind=kind, definition=definition or [])
    db.add(aud); db.commit()
    return aud


def add_members(db: Session, audience_id: str, person_ids: list[str]) -> int:
    n = 0
    for pid in person_ids:
        exists = db.query(mx.AudienceMember).filter_by(audience_id=audience_id, person_id=pid).first()
        if not exists:
            db.add(mx.AudienceMember(audience_id=audience_id, person_id=pid)); n += 1
    db.commit()
    return n


def resolve_members(db: Session, audience_id: str) -> list["models.Person"]:
    """Static list -> explicit members. Dynamic segment -> evaluate the JSON
    filter over Person fields (MKT: dynamic segments re-evaluate on read)."""
    aud = db.get(mx.Audience, audience_id)
    if aud is None:
        return []
    if aud.kind == "list":
        ids = [m.person_id for m in db.query(mx.AudienceMember).filter_by(audience_id=audience_id)]
        return db.query(models.Person).filter(models.Person.id.in_(ids)).all() if ids else []
    persons = db.query(models.Person).filter(models.Person.is_active == True).all()  # noqa: E712
    out = []
    for p in persons:
        ok = True
        for c in (aud.definition or []):
            op = _OPS.get(c.get("op", "eq"))
            if not op or not op(getattr(p, c.get("field", ""), None), c.get("value")):
                ok = False; break
        if ok:
            out.append(p)
    return out


def suppress(db: Session, email: str, reason: str = "manual") -> mx.Suppression:
    existing = db.query(mx.Suppression).filter_by(email=email.lower()).first()
    if existing:
        return existing
    s = mx.Suppression(email=email.lower(), reason=reason)
    db.add(s); db.commit()
    publish(Event("email.suppressed", key=email, payload={"reason": reason}))
    return s


def is_suppressed(db: Session, email: str | None) -> bool:
    if not email:
        return False
    return db.query(mx.Suppression).filter_by(email=email.lower()).first() is not None


def is_sendable(db: Session, person: "models.Person") -> tuple[bool, str]:
    """MKT-001 — the send-time gate."""
    if person is None or not person.is_active:
        return False, "inactive"
    if person.do_not_contact:
        return False, "do_not_contact"
    if (person.consent_status or "none") == "denied":
        return False, "consent_denied"
    if not person.primary_email:
        return False, "no_email"
    if is_suppressed(db, person.primary_email):
        return False, "suppressed"
    return True, "ok"


def create_campaign(db: Session, name: str, audience_id: str, subject: str, body: str,
                    ab_config: dict | None = None) -> mx.EmailCampaign:
    c = mx.EmailCampaign(name=name, audience_id=audience_id, subject=subject,
                         body=body, ab_config=ab_config or {})
    db.add(c); db.commit()
    return c


def send_campaign(db: Session, campaign_id: str, transport: str = "dry_run") -> dict:
    """Resolve audience -> gate each recipient -> create EmailMessage -> enqueue
    via the delivery engine. A/B: alternate variants across eligible recipients.
    Never sends for real unless transport is explicitly switched later."""
    camp = db.get(mx.EmailCampaign, campaign_id)
    if camp is None:
        return {"error": "campaign not found"}
    camp.status = "sending"
    members = resolve_members(db, camp.audience_id)
    variants = (camp.ab_config or {}).get("variants") or [{"name": "A", "subject": camp.subject}]
    sent = blocked = existing = held_for_human = 0
    reasons: dict[str, int] = {}
    touched_orgs: set[str] = set()
    for i, person in enumerate(members):
        ok, reason = is_sendable(db, person)
        if not ok:
            blocked += 1
            reasons[reason] = reasons.get(reason, 0) + 1
            continue
        var = variants[i % len(variants)]
        subject = marketing_ext.render_merge(db, var.get("subject") or camp.subject, person)
        body = marketing_ext.render_merge(db, camp.body, person)
        if person.seniority_level == "c_suite":
            pending = (db.query(models.Draft).filter(
                models.Draft.person_id == person.id,
                models.Draft.source == f"campaign:{camp.id}",
                models.Draft.status.in_(["pending", "approved", "sent"])).first())
            if pending:
                existing += 1
            else:
                db.add(models.Draft(org_id=person.current_org_id, person_id=person.id,
                                    channel="email", subject=subject, body=body,
                                    status="pending", source=f"campaign:{camp.id}",
                                    sequence_step=0))
                # flush() is load-bearing here, not tidiness. SessionLocal is
                # built with autoflush=False (database.py), so without this the
                # Draft is still only pending in the identity map when the
                # `pending_approvals` count runs below -- the count comes back
                # 0 and the campaign is marked "sent" while an executive draft
                # is still awaiting human review. That is the exact opposite of
                # the guarantee this branch exists to provide. Caught by
                # driving a real campaign end-to-end rather than trusting the
                # service call in isolation.
                db.flush()
                held_for_human += 1
            continue
        # Stable recipient id makes scheduler/API retries exactly-once.
        msg_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"drip:campaign:{camp.id}:{person.id}"))
        msg = db.get(mx.EmailMessage, msg_id)
        if msg is not None:
            existing += 1
            continue
        msg = mx.EmailMessage(id=msg_id, campaign_id=camp.id, person_id=person.id,
                              to_email=person.primary_email, variant=var["name"])
        db.add(msg); db.flush()
        delivery.enqueue(db, message_id=msg.id, to_email=person.primary_email,
                         subject=subject, body=body,
                         transport=transport)
        msg.status = "sent"; msg.sent_at = datetime.utcnow()
        attribution.record_touch(db, org_id=person.current_org_id, person_id=person.id,
                                 channel="email", campaign_id=camp.id)
        if person.current_org_id:
            touched_orgs.add(person.current_org_id)
        sent += 1
    pending_approvals = db.query(models.Draft).filter(
        models.Draft.source == f"campaign:{camp.id}",
        models.Draft.status.in_(["pending", "approved"])).count()
    camp.status = "awaiting_approval" if pending_approvals else "sent"
    db.commit()
    for org_id in touched_orgs:
        engagement.rollup_org(db, org_id)
    publish(Event("email.campaign.sent", key=camp.id, payload={"sent": sent, "blocked": blocked}))
    return {"sent": sent, "held_for_human": held_for_human,
            "existing_skipped": existing, "blocked": blocked,
            "blocked_reasons": reasons, "variants_used": len(variants),
            "accounts_rescored": len(touched_orgs), "status": camp.status}


def campaign_report(db: Session, campaign_id: str) -> dict:
    msgs = db.query(mx.EmailMessage).filter_by(campaign_id=campaign_id).all()
    ids = [m.id for m in msgs]
    events = (db.query(mx.DeliveryEvent).filter(mx.DeliveryEvent.message_id.in_(ids)).all()
              if ids else [])
    by = {}
    for e in events:
        by[e.event_type] = by.get(e.event_type, 0) + 1
    return {"messages": len(msgs), "events": by,
            "by_variant": _variant_split(msgs, events)}


def _variant_split(msgs, events) -> dict:
    ev_by_msg: dict[str, set] = {}
    for e in events:
        ev_by_msg.setdefault(e.message_id, set()).add(e.event_type)
    out: dict[str, dict] = {}
    for m in msgs:
        v = out.setdefault(m.variant or "A", {"sent": 0, "opened": 0})
        v["sent"] += 1
        if "open" in ev_by_msg.get(m.id, set()):
            v["opened"] += 1
    return out
