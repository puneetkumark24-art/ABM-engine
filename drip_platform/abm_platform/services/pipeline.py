"""Module 19 — Pipeline Engine (the biggest HubSpot gap, now real).
Configurable pipelines + ordered stages with probabilities and rotting days,
governed deal placement via OpportunityStageLink (opportunities table untouched),
weighted forecast, and health flags (stalled / single-threaded / hygiene)."""
from __future__ import annotations
import re
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
import models
import models_p10 as p10
from abm_platform.events import Event, publish

DEFAULT_STAGES = [
    {"name": "Identified", "order": 1, "probability": 0.10, "rotting_days": 30},
    {"name": "Qualified", "order": 2, "probability": 0.25, "rotting_days": 21},
    {"name": "Proposal", "order": 3, "probability": 0.50, "rotting_days": 21},
    {"name": "Negotiation", "order": 4, "probability": 0.75, "rotting_days": 14},
    {"name": "Won", "order": 5, "probability": 1.00, "is_won": True},
    {"name": "Lost", "order": 6, "probability": 0.00, "is_lost": True},
]


def create_pipeline(db: Session, name: str, stages: list[dict] | None = None,
                    is_default: bool = False) -> p10.Pipeline:
    pl = p10.Pipeline(name=name, is_default=is_default)
    db.add(pl); db.flush()
    for s in (stages or DEFAULT_STAGES):
        db.add(p10.PipelineStage(pipeline_id=pl.id, name=s["name"], order=s["order"],
                                 probability=s.get("probability", 0.1),
                                 rotting_days=s.get("rotting_days", 30),
                                 is_won=s.get("is_won", False),
                                 is_lost=s.get("is_lost", False)))
    db.commit()
    return pl


def stages(db: Session, pipeline_id: str) -> list[p10.PipelineStage]:
    return (db.query(p10.PipelineStage).filter_by(pipeline_id=pipeline_id)
            .order_by(p10.PipelineStage.order).all())


def assign_deal(db: Session, opportunity_id: str, pipeline_id: str,
                stage_name: str | None = None, by: str = "system") -> p10.OpportunityStageLink:
    """Attach a deal to a pipeline at a stage (default: first stage)."""
    sts = stages(db, pipeline_id)
    if not sts:
        raise ValueError("pipeline has no stages")
    target = next((s for s in sts if s.name == stage_name), sts[0]) if stage_name else sts[0]
    link = db.query(p10.OpportunityStageLink).filter_by(opportunity_id=opportunity_id).first()
    if link is None:
        link = p10.OpportunityStageLink(opportunity_id=opportunity_id,
                                        pipeline_id=pipeline_id, stage_id=target.id,
                                        moved_by=by, history=[{"stage": target.name,
                                                               "at": str(datetime.utcnow()), "by": by}])
        db.add(link)
    else:
        link.pipeline_id = pipeline_id
        link.stage_id = target.id
    db.commit()
    return link


def move_deal(db: Session, opportunity_id: str, to_stage_name: str,
              by: str = "user", reason: str | None = None) -> p10.OpportunityStageLink:
    """PIP-001: the target stage must belong to the deal's pipeline. Moves are
    recorded in the link's history; terminal stages publish deal.stage.changed
    with won/lost flags so scoring/attribution can react."""
    link = db.query(p10.OpportunityStageLink).filter_by(opportunity_id=opportunity_id).first()
    if link is None:
        raise ValueError("deal is not assigned to a pipeline")
    target = (db.query(p10.PipelineStage)
              .filter_by(pipeline_id=link.pipeline_id, name=to_stage_name).first())
    if target is None:
        raise ValueError(f"stage '{to_stage_name}' not in this pipeline")

    link.stage_id = target.id
    link.entered_stage_at = datetime.utcnow()
    link.moved_by = by
    hist = list(link.history or [])
    hist.append({"stage": target.name, "at": str(datetime.utcnow()), "by": by,
                 **({"reason": reason} if reason else {})})
    link.history = hist

    # mirror the human-readable label + probability on the Opportunity itself
    opp = db.get(models.Opportunity, opportunity_id)
    if opp is not None:
        opp.stage = target.name
        opp.probability = int(round(target.probability * 100))
        if target.is_won or target.is_lost:
            opp.closed_at = datetime.utcnow()
    db.commit()
    publish(Event("deal.stage.changed", key=opportunity_id,
                  payload={"stage": target.name, "won": target.is_won, "lost": target.is_lost}))
    return link


_NUM_RE = re.compile(r"[\d.]+")


def _amount(opp: "models.Opportunity") -> float:
    """estimated_value is free text ('SAR 2.5M', '500k'); parse best-effort."""
    if not opp.estimated_value:
        return 0.0
    txt = opp.estimated_value.lower().replace(",", "")
    m = _NUM_RE.search(txt)
    if not m:
        return 0.0
    val = float(m.group())
    if "m" in txt or "million" in txt:
        val *= 1_000_000
    elif "k" in txt:
        val *= 1_000
    return val


def forecast(db: Session, pipeline_id: str) -> dict:
    """PIP-002: weighted = sum(amount x stage probability) over open deals."""
    sts = {s.id: s for s in stages(db, pipeline_id)}
    links = db.query(p10.OpportunityStageLink).filter_by(pipeline_id=pipeline_id).all()
    weighted = best = 0.0
    open_deals = won = lost = 0
    for link in links:
        st = sts.get(link.stage_id)
        opp = db.get(models.Opportunity, link.opportunity_id)
        if st is None or opp is None:
            continue
        if st.is_won:
            won += 1
            continue
        if st.is_lost:
            lost += 1
            continue
        open_deals += 1
        amt = _amount(opp)
        best += amt
        weighted += amt * st.probability
    return {"open_deals": open_deals, "won": won, "lost": lost,
            "best_case": round(best, 2), "weighted": round(weighted, 2)}


def health(db: Session, pipeline_id: str, now: datetime | None = None) -> list[dict]:
    """PIP-003/004/005: stalled (idle past stage.rotting_days), single-threaded
    (org has <2 active contacts), hygiene (open deal with past close marker)."""
    now = now or datetime.utcnow()
    sts = {s.id: s for s in stages(db, pipeline_id)}
    flags = []
    for link in db.query(p10.OpportunityStageLink).filter_by(pipeline_id=pipeline_id).all():
        st = sts.get(link.stage_id)
        if st is None or st.is_won or st.is_lost:
            continue
        opp = db.get(models.Opportunity, link.opportunity_id)
        deal_flags = []
        idle_days = (now - (link.entered_stage_at or now)).days
        if st.rotting_days and idle_days > st.rotting_days:
            deal_flags.append(f"stalled ({idle_days}d in {st.name})")
        if opp and opp.org_id:
            active_contacts = (db.query(models.Person)
                               .filter(models.Person.current_org_id == opp.org_id,
                                       models.Person.is_active == True).count())  # noqa: E712
            if active_contacts < 2:
                deal_flags.append("single-threaded")
        if opp and opp.closed_at and opp.closed_at < now:
            deal_flags.append("hygiene: closed_at set on open deal")
        if deal_flags:
            flags.append({"opportunity_id": link.opportunity_id, "stage": st.name,
                          "flags": deal_flags})
    return flags
