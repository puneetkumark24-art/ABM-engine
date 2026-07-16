"""Module 20 — Reporting Engine: saved reports over analytics + the one-click
executive brief (REP-003: briefs pull only current, non-decayed intelligence)."""
from __future__ import annotations
from datetime import datetime
from sqlalchemy.orm import Session
import models
import models_ext as mx
from . import analytics


def create_report(db: Session, name: str, definition: dict, viz: str = "table") -> mx.ReportDef:
    r = mx.ReportDef(name=name, definition=definition, viz=viz)
    db.add(r); db.commit()
    return r


def render(db: Session, report_id: str) -> dict:
    r = db.get(mx.ReportDef, report_id)
    if r is None:
        return {"error": "report not found"}
    d = r.definition or {}
    data = analytics.query(db, event_type=d.get("event_type"),
                           since_days=d.get("since_days", 30),
                           group_by=d.get("group_by", "event_type"))
    return {"report": r.name, "viz": r.viz, "data": data}


def generate_brief(db: Session, org_id: str) -> mx.ExecBrief:
    """One-click pre-meeting brief: profile, committee, live signals (non-
    decayed only), score, open opportunities, suggested next steps."""
    org = db.get(models.Organization, org_id)
    now = datetime.utcnow()

    persons = (db.query(models.Person)
               .filter(models.Person.current_org_id == org_id,
                       models.Person.is_active == True).all())  # noqa: E712
    committee = [{"name": p.full_name, "title": p.current_title, "persona": p.persona,
                  "warmness": p.warmness} for p in persons]

    signals_q = (db.query(models.Signal)
                 .filter(models.Signal.org_id == org_id)
                 .order_by(models.Signal.created_at.desc()).limit(20).all())
    live_signals = [{"title": s.title, "type": s.signal_type, "urgency": s.urgency,
                     "confidence": s.confidence_score}
                    for s in signals_q
                    if not (s.decay_expires_at and s.decay_expires_at < now)]  # REP-003

    acct = db.get(models.AccountIntelligence, org_id)
    opps = db.query(models.Opportunity).filter_by(org_id=org_id).all()

    next_steps = []
    if not committee:
        next_steps.append("Discover buying committee — no contacts on file.")
    if live_signals and any(s["urgency"] in ("CRITICAL", "HIGH") for s in live_signals):
        next_steps.append("Act on high-urgency live signal(s) this week.")
    if acct and (acct.priority or "COLD") == "HOT" and not opps:
        next_steps.append("HOT account with no opportunity — open one.")
    if not next_steps:
        next_steps.append("Maintain nurture cadence; review at next scoring cycle.")

    content = {
        "organization": {"name": org.canonical_name if org else org_id,
                         "segment": acct.segment if acct else None,
                         "tier": acct.tier if acct else None,
                         "priority": acct.priority if acct else None,
                         "score": acct.effective_opportunity if acct else None},
        "buying_committee": committee,
        "live_signals": live_signals,
        "open_opportunities": [{"stage": o.stage, "probability": o.probability} for o in opps
                               if o.stage not in ("Won", "Lost")],
        "suggested_next_steps": next_steps,
        "generated_at": str(now),
    }
    brief = mx.ExecBrief(org_id=org_id, content=content)
    db.add(brief); db.commit()
    return brief
