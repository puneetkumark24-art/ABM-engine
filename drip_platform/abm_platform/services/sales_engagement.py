"""
sales_engagement.py — Sprint 5: Sales Engagement (Outreach/Salesloft/Apollo parity
on top of the existing sequence engine).

Adds the three things the sequence engine didn't have:
  1. Reply-sentiment classification + automated action (auto-pause on any reply,
     auto-suppress on opt-out/negative, flag positive for rep hand-off).
  2. Step-level A/B testing — pick a template variant per sequence step and record
     outcomes into VariantPerformance (kind="seqstep:<step_id>").
  3. Hot-lead prioritization — rank prospects by engagement score for the rep's
     "to-work" queue.

Reuses existing tables only (suppressions, variant_performance, person_engagement);
no schema change.
"""
from __future__ import annotations
import random
from sqlalchemy.orm import Session
import models
import models_ext as mx
import models_p10 as p10
import models_p11 as p11
from sequences import engine as seq

_POS = ("interested", "sounds good", "let's talk", "happy to", "book", "schedule",
        "yes", "keen", "demo", "call me")
_NEG = ("not interested", "no thanks", "stop", "unsubscribe", "remove me",
        "do not contact", "leave me alone", "spam")
_OOO = ("out of office", "on leave", "annual leave", "vacation", "away until",
        "maternity", "paternity")


def classify_reply(text: str) -> str:
    """positive | negative | ooo | neutral (keyword heuristic; deterministic)."""
    t = (text or "").lower()
    if any(k in t for k in _NEG):
        return "negative"
    if any(k in t for k in _OOO):
        return "ooo"
    if any(k in t for k in _POS):
        return "positive"
    return "neutral"


def _suppress(db: Session, email: str | None, reason: str) -> None:
    if not email:
        return
    if not db.query(mx.Suppression).filter_by(email=email).first():
        db.add(mx.Suppression(email=email, reason=reason))


def handle_reply(db: Session, person_id: str, text: str) -> dict:
    """Classify a prospect reply and act: pause the cadence always; suppress on
    opt-out/negative; flag positive for hand-off. Returns the action taken."""
    sentiment = classify_reply(text)
    person = db.get(models.Person, person_id)
    # any human reply pauses the automated cadence (Outreach behavior)
    seq.pause_on_reply(db, person_id, reason=f"reply:{sentiment}")
    action = "paused"
    if sentiment == "negative":
        _suppress(db, getattr(person, "primary_email", None), "opt-out")
        if person is not None:
            person.do_not_contact = True
        action = "suppressed"
    elif sentiment == "positive" and person is not None:
        person.replied = True
        person.next_step = "REP HAND-OFF: positive reply"
        action = "handoff"
    elif sentiment == "ooo":
        action = "deferred"
    db.commit()
    return {"person_id": person_id, "sentiment": sentiment, "action": action}


# ── step-level A/B ───────────────────────────────────────────
def _perf(db: Session, kind: str, key: str, label: str = "") -> p11.VariantPerformance:
    row = db.query(p11.VariantPerformance).filter_by(kind=kind, variant_key=key).first()
    if row is None:
        row = p11.VariantPerformance(kind=kind, variant_key=key, label=label,
                                     sends=0, opens=0, clicks=0, replies=0,
                                     meetings=0, score=0.0)
        db.add(row); db.flush()
    return row


def register_step_variants(db: Session, step_id: str, variants: list[dict]) -> int:
    """variants: [{key,label?}]. Seeds VariantPerformance rows for a step."""
    kind = f"seqstep:{step_id}"
    for v in variants:
        _perf(db, kind, v["key"], v.get("label", ""))
    db.commit()
    return len(variants)


def pick_step_variant(db: Session, step_id: str,
                      rng: random.Random | None = None) -> str | None:
    """Epsilon-greedy: 80% exploit best reply-rate, 20% explore. Falls back to
    random among untried variants."""
    rng = rng or random
    kind = f"seqstep:{step_id}"
    rows = db.query(p11.VariantPerformance).filter_by(kind=kind).all()
    if not rows:
        return None
    untried = [r for r in rows if (r.sends or 0) == 0]
    if untried or rng.random() < 0.2:
        pool = untried or rows
        return rng.choice(pool).variant_key

    def reply_rate(r):
        return (r.replies or 0) / (r.sends or 1)
    return max(rows, key=reply_rate).variant_key


def record_step_outcome(db: Session, step_id: str, variant_key: str,
                        event: str = "send") -> p11.VariantPerformance:
    """event ∈ send|open|click|reply|meeting. Updates counters + a blended score."""
    row = _perf(db, f"seqstep:{step_id}", variant_key)
    field = {"send": "sends", "open": "opens", "click": "clicks",
             "reply": "replies", "meeting": "meetings"}.get(event)
    if field:
        setattr(row, field, (getattr(row, field) or 0) + 1)
    sends = row.sends or 1
    row.score = round((2 * (row.replies or 0) + 3 * (row.meetings or 0)
                       + (row.clicks or 0)) / sends, 4)
    db.commit()
    return row


# ── hot-lead prioritization ──────────────────────────────────
def hot_leads(db: Session, limit: int = 20) -> list[dict]:
    rows = (db.query(p10.PersonEngagement)
            .order_by(p10.PersonEngagement.engagement_score.desc()).limit(limit).all())
    out = []
    for r in rows:
        p = db.get(models.Person, r.person_id)
        out.append({"person_id": r.person_id,
                    "name": getattr(p, "full_name", None),
                    "engagement_score": r.engagement_score,
                    "opens": r.opens, "clicks": r.clicks, "replies": r.replies})
    return out
