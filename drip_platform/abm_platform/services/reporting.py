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


# ── Final wave: generic report builder (HubSpot custom-reports gap) ──
_ENTITIES = {
    "persons": lambda: models.Person,
    "organizations": lambda: models.Organization,
    "opportunities": lambda: models.Opportunity,
    "signals": lambda: models.Signal,
}


def _row_matches(row, filters: list[dict]) -> bool:
    for f in filters or []:
        v = getattr(row, f["field"], None)
        op, t = f.get("op", "eq"), f.get("value")
        ok = ((op == "eq" and v == t) or (op == "neq" and v != t) or
              (op == "contains" and t is not None and str(t).lower() in str(v or "").lower()) or
              (op == "gt" and v is not None and t is not None and v > t) or
              (op == "lt" and v is not None and t is not None and v < t) or
              (op == "exists" and v not in (None, "")))
        if not ok:
            return False
    return True


def run_definition(db: Session, definition: dict) -> dict:
    """Generic custom report: {entity, filters?, group_by?, metric: count|sum,
    metric_field?}. Returns grouped rows ready for a table/bar viz."""
    entity = definition.get("entity", "persons")
    if entity not in _ENTITIES:
        raise ValueError(f"entity must be one of {sorted(_ENTITIES)}")
    model = _ENTITIES[entity]()
    rows = [r for r in db.query(model).all()
            if _row_matches(r, definition.get("filters"))]
    group_by = definition.get("group_by")
    metric = definition.get("metric", "count")
    mfield = definition.get("metric_field")

    def val(r):
        if metric == "sum" and mfield:
            return float(getattr(r, mfield, 0) or 0)
        return 1.0

    if group_by:
        groups: dict = {}
        for r in rows:
            k = str(getattr(r, group_by, None))
            groups[k] = groups.get(k, 0.0) + val(r)
        data = [{"group": k, "value": round(v, 2)}
                for k, v in sorted(groups.items(), key=lambda kv: -kv[1])]
    else:
        data = [{"group": "all", "value": round(sum(val(r) for r in rows), 2)}]
    return {"entity": entity, "metric": metric, "metric_field": mfield,
            "group_by": group_by, "row_count": len(rows), "data": data}


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
