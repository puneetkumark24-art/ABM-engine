"""routers/platform_modules.py — API surface for the 16 Phase-9 modules.
Thin: every write goes through abm_platform/services/* so gates live in one
place. Grouped under /px/<domain> to keep the OpenAPI tidy."""
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from abm_platform.services import (
    enrichment, marketing, campaign, ai_gen, delivery, linkedin, landing,
    assets, rules, workflow, analytics, reporting, notification, attribution,
    admin, copilot,
)

router = APIRouter(prefix="/px", tags=["platform-modules"])


# ---- 03 enrichment ----
class EnrichReq(BaseModel):
    person_id: str
    required: Optional[list[str]] = None


@router.post("/enrichment/run")
def enrich(req: EnrichReq, db: Session = Depends(get_db)):
    job = enrichment.run_waterfall(db, req.person_id, req.required)
    return {"job_id": job.id, "status": job.status, "providers_tried": job.providers_tried}


@router.post("/enrichment/detect-duplicates")
def dupes(db: Session = Depends(get_db)):
    out = enrichment.detect_duplicates(db)
    return {"candidates": len(out)}


# ---- 07 marketing ----
class AudienceReq(BaseModel):
    name: str
    kind: str = "list"
    definition: Optional[list] = None


@router.post("/marketing/audiences")
def mk_audience(req: AudienceReq, db: Session = Depends(get_db)):
    a = marketing.create_audience(db, req.name, req.kind, req.definition)
    return {"audience_id": a.id}


class CampaignReq(BaseModel):
    name: str
    audience_id: str
    subject: str
    body: str
    ab_config: Optional[dict] = None


@router.post("/marketing/campaigns")
def mk_campaign(req: CampaignReq, db: Session = Depends(get_db)):
    c = marketing.create_campaign(db, req.name, req.audience_id, req.subject, req.body, req.ab_config)
    return {"campaign_id": c.id}


@router.post("/marketing/campaigns/{campaign_id}/send")
def send_campaign(campaign_id: str, db: Session = Depends(get_db)):
    """Transport is hard-locked to dry_run at the API level — enabling a real
    transport is a deliberate code change, not an API parameter."""
    return marketing.send_campaign(db, campaign_id, transport="dry_run")


@router.get("/marketing/campaigns/{campaign_id}/report")
def campaign_rep(campaign_id: str, db: Session = Depends(get_db)):
    return marketing.campaign_report(db, campaign_id)


# ---- 09 abm campaign ----
@router.post("/campaigns")
def mk_abm_campaign(name: str, objective: str = "pipeline", db: Session = Depends(get_db)):
    c = campaign.create(db, name, objective)
    return {"campaign_id": c.id}


@router.get("/campaigns/{campaign_id}/rollup")
def campaign_rollup(campaign_id: str, db: Session = Depends(get_db)):
    return campaign.rollup(db, campaign_id)


# ---- 10 ai generation ----
class GenReq(BaseModel):
    kind: str = "email"
    person_id: Optional[str] = None
    org_id: Optional[str] = None
    context: Optional[dict] = None


@router.post("/ai/generate")
def generate(req: GenReq, db: Session = Depends(get_db)):
    g = ai_gen.generate(db, req.kind, req.person_id, req.org_id, req.context)
    return {"generation_id": g.id, "status": g.status, "qc": g.qc, "output": g.output}


# ---- 11 delivery ----
@router.post("/delivery/webhook")
def webhook(events: list[dict], db: Session = Depends(get_db)):
    return delivery.ingest_webhook(db, events)


@router.get("/delivery/messages/{message_id}/events")
def msg_events(message_id: str, db: Session = Depends(get_db)):
    return delivery.message_events(db, message_id)


# ---- 12 linkedin ----
@router.post("/linkedin/seats")
def mk_seat(owner: str, daily_limit: int = 20, db: Session = Depends(get_db)):
    s = linkedin.create_seat(db, owner, daily_limit)
    return {"seat_id": s.id}


class LiActionReq(BaseModel):
    seat_id: str
    person_id: str
    action_type: str = "connect"


@router.post("/linkedin/actions")
def queue_li(req: LiActionReq, db: Session = Depends(get_db)):
    a, reason = linkedin.queue_action(db, req.seat_id, req.person_id, req.action_type)
    if a is None:
        raise HTTPException(status_code=409, detail=reason)
    return {"action_id": a.id, "status": a.status, "reason": reason}


@router.post("/linkedin/breaker/trip")
def trip(reason: str = "manual", db: Session = Depends(get_db)):
    b = linkedin.trip_breaker(db, reason)
    return {"healthy": b.healthy, "reason": b.reason}


# ---- 13 landing/forms ----
class SubmitReq(BaseModel):
    form_id: str
    data: dict
    consent_given: bool = False
    utm: Optional[dict] = None


@router.post("/forms/submit")
def submit_form(req: SubmitReq, db: Session = Depends(get_db)):
    sub, reason = landing.submit(db, req.form_id, req.data, req.utm, req.consent_given)
    if sub is None:
        raise HTTPException(status_code=422, detail=reason)
    return {"submission_id": sub.id, "person_id": sub.person_id}


@router.post("/unsubscribe")
def unsub(email: str, db: Session = Depends(get_db)):
    return landing.unsubscribe(db, email)


# ---- 14 assets ----
@router.post("/assets/{asset_id}/sign")
def sign(asset_id: str, ttl_seconds: int = 3600):
    return {"token": assets.sign_link(asset_id, ttl_seconds)}


@router.get("/assets/download/{token}")
def dl(token: str, db: Session = Depends(get_db)):
    asset, reason = assets.download(db, token)
    if asset is None:
        raise HTTPException(status_code=410, detail=reason)
    return {"asset": asset.name, "version": asset.version, "url": asset.storage_url}


# ---- 15 rules ----
class RuleReq(BaseModel):
    name: str
    event_type: str
    conditions: list[dict]
    actions: list[dict]
    priority: int = 100


@router.post("/rules")
def mk_rule(req: RuleReq, db: Session = Depends(get_db)):
    r = rules.create_rule(db, req.name, req.event_type, req.conditions, req.actions, req.priority)
    return {"rule_id": r.id}


@router.post("/rules/{rule_id}/activate")
def act_rule(rule_id: str, db: Session = Depends(get_db)):
    try:
        r = rules.activate(db, rule_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"rule_id": r.id, "status": r.status}


class FireReq(BaseModel):
    event_type: str
    subject: dict
    dry_run: bool = False


@router.post("/rules/fire")
def fire_rules(req: FireReq, db: Session = Depends(get_db)):
    firings = rules.fire(db, req.event_type, req.subject, req.dry_run)
    return [{"rule_id": f.rule_id, "matched": f.matched, "results": f.actions_result} for f in firings]


# ---- 16 workflow ----
class WfReq(BaseModel):
    name: str
    nodes: list[dict]
    edges: list[dict]


@router.post("/workflows")
def mk_wf(req: WfReq, db: Session = Depends(get_db)):
    try:
        wf = workflow.create(db, req.name, req.nodes, req.edges)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"workflow_id": wf.id}


@router.post("/workflows/{workflow_id}/run")
def run_wf(workflow_id: str, ctx: Optional[dict] = None, db: Session = Depends(get_db)):
    run = workflow.start_run(db, workflow_id, ctx)
    return {"run_id": run.id, "status": run.status, "cursor": run.cursor}


@router.post("/workflows/runs/{run_id}/approve/{node_id}")
def approve_wf(run_id: str, node_id: str, db: Session = Depends(get_db)):
    run = workflow.approve(db, run_id, node_id)
    return {"run_id": run.id, "status": run.status}


# ---- 17 analytics / 20 reporting ----
@router.get("/analytics/query")
def a_query(event_type: Optional[str] = None, since_days: int = 30,
            group_by: str = "event_type", db: Session = Depends(get_db)):
    return analytics.query(db, event_type, since_days, group_by)


@router.post("/reports/brief/{org_id}")
def brief(org_id: str, db: Session = Depends(get_db)):
    b = reporting.generate_brief(db, org_id)
    return {"brief_id": b.id, "content": b.content}


# ---- 21 notification ----
@router.get("/notifications/{user}")
def inbox(user: str, db: Session = Depends(get_db)):
    return [{"id": n.id, "kind": n.kind, "priority": n.priority, "status": n.status,
             "payload": n.payload} for n in notification.inbox(db, user)]


# ---- 22 attribution ----
@router.post("/attribution/compute")
def attr(org_id: str, outcome_ref: str, model: str = "linear", db: Session = Depends(get_db)):
    res = attribution.compute(db, org_id, outcome_ref, model)
    return {"result_id": res.id, "model": res.model, "credit": res.credit,
            "by_campaign": attribution.campaign_credit(db, res.id)}


# ---- 25 admin ----
@router.get("/admin/quota/{kind}")
def quota(kind: str, db: Session = Depends(get_db)):
    q = admin.ensure_quota(db, kind)
    return {"kind": q.kind, "limit": q.limit, "used": q.used}


# ---- 26 copilot ----
class AskReq(BaseModel):
    question: str


@router.post("/copilot/ask")
def ask(req: AskReq, db: Session = Depends(get_db)):
    t = copilot.ask(db, req.question)
    return {"intent": t.intent, "answer": t.answer, "citations": t.citations}
