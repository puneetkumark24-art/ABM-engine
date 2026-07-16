"""Module 26 — AI Copilot: natural-language interface over the platform.
Rule-based intent router (no API key required); an LLM adapter can be
registered later for free-form questions. COP-003: answers are grounded —
every claim cites the record it came from. COP-002: any action it takes goes
through the owning engine's gates (it can only *suggest* outreach)."""
from __future__ import annotations
from datetime import datetime
from sqlalchemy.orm import Session
import models
import models_ext as mx


def ask(db: Session, question: str) -> mx.CopilotTurn:
    q = (question or "").lower()
    if any(k in q for k in ("who should i call", "call today", "priorit")):
        intent, answer, cites = "call_list", *(_call_list(db))
    elif "how do i approach" in q or "approach" in q:
        intent, answer, cites = "approach", *(_approach(db, question))
    elif any(k in q for k in ("status", "summary", "where are we")):
        intent, answer, cites = "status", *(_status(db))
    else:
        intent = "unknown"
        answer = ("I can answer: 'Who should I call today?', 'How do I approach "
                  "<bank>?', or 'status'. (Free-form questions need the LLM "
                  "adapter, which isn't configured.)")
        cites = []
    turn = mx.CopilotTurn(question=question, intent=intent, answer=answer, citations=cites)
    db.add(turn); db.commit()
    return turn


def _call_list(db: Session):
    """Ranked by account priority + person tier + due sequence steps."""
    from sequences import engine as seq_engine
    due = seq_engine.get_due(db, limit=10, respect_send_window=False)
    lines, cites = [], []
    for r in due[:5]:
        p, e = r["person"], r["enrollment"]
        org = db.get(models.Organization, e.org_id) if e.org_id else None
        org_name = org.canonical_name if org else "—"
        lines.append(f"• {p.full_name} ({p.current_title or 'n/a'}) at {org_name} — "
                     f"tier {p.tier}, sequence step {r['next_step'].step_number} due")
        cites.append(f"enrollment:{e.id}")
    if not lines:
        # fall back to HOT accounts even with nothing due
        hot = (db.query(models.AccountIntelligence)
               .filter(models.AccountIntelligence.priority == "HOT").limit(5).all())
        for a in hot:
            org = db.get(models.Organization, a.org_id)
            lines.append(f"• {org.canonical_name if org else a.org_id} — HOT "
                         f"(score {a.effective_opportunity or a.score})")
            cites.append(f"account:{a.org_id}")
    answer = ("Today's priorities:\n" + "\n".join(lines)) if lines else \
             "Nothing due and no HOT accounts — check signal feed."
    return answer, cites


def _approach(db: Session, question: str):
    """Find the org named in the question; assemble committee + live signals."""
    orgs = db.query(models.Organization).all()
    target = None
    for o in orgs:
        if o.canonical_name and o.canonical_name.lower() in question.lower():
            target = o; break
        if o.short_name and o.short_name.lower() in question.lower():
            target = o; break
    if target is None:
        return "I couldn't match that organization. Try its exact name.", []
    persons = (db.query(models.Person)
               .filter(models.Person.current_org_id == target.id).all())
    now = datetime.utcnow()
    signals = [s for s in db.query(models.Signal).filter_by(org_id=target.id)
               .order_by(models.Signal.created_at.desc()).limit(10)
               if not (s.decay_expires_at and s.decay_expires_at < now)]
    cites = [f"org:{target.id}"] + [f"person:{p.id}" for p in persons[:5]] + \
            [f"signal:{s.id}" for s in signals[:3]]
    lines = [f"Approach plan for {target.canonical_name}:"]
    dms = [p for p in persons if p.persona == "Decision Maker" or p.is_decision_maker]
    champs = [p for p in persons if (p.persona or "") == "Champion"]
    if dms:
        lines.append("Decision makers: " + ", ".join(f"{p.full_name} ({p.current_title})" for p in dms[:3]))
    if champs:
        lines.append("Champion/bridge: " + ", ".join(p.full_name for p in champs[:2]))
    if signals:
        lines.append("Why now: " + "; ".join(s.title[:80] for s in signals[:2] if s.title))
    if not (dms or champs):
        lines.append("No committee mapped yet — enrich contacts first.")
    return "\n".join(lines), cites


def _status(db: Session):
    from abm_platform import registry
    n_orgs = db.query(models.Organization).count()
    n_persons = db.query(models.Person).count()
    n_signals = db.query(models.Signal).count()
    n_enroll = db.query(models.SequenceEnrollment).count()
    s = registry.summary()
    answer = (f"Platform: {s['total']} modules ({s['by_status']}). "
              f"Data: {n_orgs} organizations, {n_persons} contacts, "
              f"{n_signals} signals, {n_enroll} sequence enrollments.")
    return answer, ["registry:summary"]
