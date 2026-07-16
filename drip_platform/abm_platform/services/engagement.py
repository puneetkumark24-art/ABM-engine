"""Engagement rollup — closes the Mailchimp loop.
delivery_events + li_actions + form_submissions + replies
  -> PersonEngagement (per-person, 0..1)
  -> org reachability (0-20)
  -> account_scores row + AccountIntelligence.priority re-tier (HOT/WARM/COLD)
  -> score.updated / account.tiered events.

This is the wire the original bug history flagged as never closed: engagement
now actually moves the Reachability 20% of the account score.
Weights are a documented v1 heuristic (replies dominate, bounces subtract);
the Bible's effective-opportunity formula in scoring.py is untouched — this
feeds the daily-dimension score, not the modifier chain."""
from __future__ import annotations
from datetime import datetime
from sqlalchemy.orm import Session
import models
import models_ext as mx
import models_p10 as p10
from abm_platform.events import Event, publish

# v1 heuristic weights
W = {"open": 1, "click": 3, "reply": 10, "li_accept": 2, "li_reply": 8,
     "form": 5, "bounce": -4}
NORMALIZE_AT = 20.0          # raw score at which engagement_score saturates to 1.0
TIER_HOT, TIER_WARM = 75, 50


def rollup_person(db: Session, person_id: str) -> p10.PersonEngagement:
    """Recompute one person's engagement from raw event stores."""
    msgs = db.query(mx.EmailMessage).filter_by(person_id=person_id).all()
    msg_ids = [m.id for m in msgs]
    events = (db.query(mx.DeliveryEvent)
              .filter(mx.DeliveryEvent.message_id.in_(msg_ids)).all() if msg_ids else [])
    opens = sum(1 for e in events if e.event_type == "open")
    clicks = sum(1 for e in events if e.event_type == "click")
    bounces = sum(1 for e in events if e.event_type in ("bounce", "hard_bounce"))

    person = db.get(models.Person, person_id)
    replies = 1 if (person and person.replied) else 0

    li = db.query(mx.LiAction).filter_by(person_id=person_id).all()
    li_accepts = sum(1 for a in li if a.status == "accepted")
    li_replies = sum(1 for a in li if a.status == "replied")

    forms = db.query(mx.FormSubmission).filter_by(person_id=person_id).count()

    raw = (opens * W["open"] + clicks * W["click"] + replies * W["reply"]
           + li_accepts * W["li_accept"] + li_replies * W["li_reply"]
           + forms * W["form"] + bounces * W["bounce"])
    score = max(0.0, min(1.0, raw / NORMALIZE_AT))

    pe = db.query(p10.PersonEngagement).filter_by(person_id=person_id).first()
    if pe is None:
        pe = p10.PersonEngagement(person_id=person_id)
        db.add(pe)
    pe.opens, pe.clicks, pe.replies = opens, clicks, replies
    pe.li_accepts, pe.li_replies = li_accepts, li_replies
    pe.form_submits, pe.bounces = forms, bounces
    pe.engagement_score = round(score, 4)
    db.commit()
    return pe


def org_reachability(db: Session, org_id: str) -> int:
    """0-20: up to 8 pts for contactable coverage, up to 12 pts for engagement."""
    persons = (db.query(models.Person)
               .filter(models.Person.current_org_id == org_id,
                       models.Person.is_active == True).all())  # noqa: E712
    if not persons:
        return 0
    contactable = [p for p in persons
                   if p.primary_email and not p.do_not_contact
                   and (p.consent_status or "none") != "denied"]
    coverage_pts = min(4, len(contactable)) * 2                    # 0..8

    scores = []
    for p in persons:
        pe = db.query(p10.PersonEngagement).filter_by(person_id=p.id).first()
        if pe is not None:
            scores.append(pe.engagement_score or 0.0)
    engagement_pts = round((sum(scores) / len(scores)) * 12) if scores else 0   # 0..12
    return min(20, coverage_pts + engagement_pts)


def _signal_dim(db: Session, org_id: str, now: datetime) -> tuple[int, int]:
    """(signal 0-35, regulatory 0-30) from live (non-decayed) signals. v1 heuristic."""
    sigs = db.query(models.Signal).filter_by(org_id=org_id).all()
    live = [s for s in sigs if not (s.decay_expires_at and s.decay_expires_at < now)]
    high = sum(1 for s in live if (s.urgency or "") in ("CRITICAL", "HIGH"))
    other = len(live) - high
    signal = min(35, high * 7 + other * 3)
    reg = min(30, sum(15 for s in live if s.signal_type == "regulatory"))
    return signal, reg


def _relationship_dim(db: Session, org_id: str) -> int:
    """0-15 from warm paths + committee coverage. v1 heuristic."""
    persons = db.query(models.Person).filter(models.Person.current_org_id == org_id).all()
    ids = [p.id for p in persons]
    warm_edges = (db.query(models.PersonRelationship)
                  .filter(models.PersonRelationship.to_person_id.in_(ids)).count()) if ids else 0
    committee = db.query(models.BuyingCommitteeMember).filter_by(org_id=org_id).count()
    return min(15, warm_edges * 3 + committee * 2)


def recompute_account_score(db: Session, org_id: str, now: datetime | None = None) -> models.AccountScore:
    """Full dimension recompute -> account_scores row -> re-tier -> events."""
    now = now or datetime.utcnow()
    signal, regulatory = _signal_dim(db, org_id, now)
    reach = org_reachability(db, org_id)
    rel = _relationship_dim(db, org_id)
    total = signal + regulatory + reach + rel
    tier = "HOT" if total >= TIER_HOT else ("WARM" if total >= TIER_WARM else "COLD")

    row = models.AccountScore(org_id=org_id, signal_score=signal,
                              regulatory_score=regulatory, reachability_score=reach,
                              relationship_score=rel, total_score=total, tier=tier,
                              notes="engagement-rollup recompute (Phase 10)")
    db.add(row)

    acct = db.get(models.AccountIntelligence, org_id)
    old_tier = acct.priority if acct else None
    if acct is None:
        acct = models.AccountIntelligence(org_id=org_id)
        db.add(acct)
    acct.priority = tier
    acct.score = total
    db.commit()

    publish(Event("score.updated", key=org_id,
                  payload={"total": total, "reachability": reach, "tier": tier}))
    if old_tier != tier:
        publish(Event("account.tiered", key=org_id,
                      payload={"from": old_tier, "to": tier}))
    return row


def rollup_org(db: Session, org_id: str) -> dict:
    """Convenience: roll up every person at the org, then rescore the account."""
    persons = db.query(models.Person).filter(models.Person.current_org_id == org_id).all()
    for p in persons:
        rollup_person(db, p.id)
    row = recompute_account_score(db, org_id)
    return {"persons_rolled": len(persons), "total_score": row.total_score,
            "reachability": row.reachability_score, "tier": row.tier}
