"""routers/crm_marketing_ext.py — Phase 12: CRM configurability (properties/
views/tasks), marketing upgrades (merge/schedule/AB-winner/test-send), the
PUBLIC landing pages (/p/{slug}), and delivery ops (retry, auto-pause)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from database import get_db
from abm_platform.services import crm_ext, marketing_ext, landing_render, delivery_ext

router = APIRouter(tags=["crm-marketing-ext"])


# ── CRM: custom properties ───────────────────────────────────
class PropDefReq(BaseModel):
    object_type: str
    key: str
    label: str
    data_type: str = "text"
    options: Optional[list] = None
    default_value: Optional[str] = None


@router.post("/crm/properties")
def define_prop(req: PropDefReq, db: Session = Depends(get_db)):
    try:
        pd = crm_ext.define_property(db, req.object_type, req.key, req.label,
                                     req.data_type, req.options, req.default_value)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"property_id": pd.id, "key": pd.key}


class PropSetReq(BaseModel):
    object_type: str
    object_id: str
    key: str
    value: str


@router.post("/crm/properties/set")
def set_prop(req: PropSetReq, db: Session = Depends(get_db)):
    try:
        crm_ext.set_property(db, req.object_type, req.object_id, req.key, req.value)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return crm_ext.get_properties(db, req.object_type, req.object_id)


@router.get("/crm/properties/{object_type}/{object_id}")
def get_props(object_type: str, object_id: str, db: Session = Depends(get_db)):
    return crm_ext.get_properties(db, object_type, object_id)


# ── CRM: saved views ─────────────────────────────────────────
class ViewReq(BaseModel):
    object_type: str
    name: str
    filters: list[dict]
    sort_by: Optional[str] = None


@router.post("/crm/views")
def create_view(req: ViewReq, db: Session = Depends(get_db)):
    try:
        v = crm_ext.create_view(db, req.object_type, req.name, req.filters, req.sort_by)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"view_id": v.id}


@router.get("/crm/views/{view_id}/run")
def run_view(view_id: str, limit: int = 100, db: Session = Depends(get_db)):
    rows = crm_ext.run_view(db, view_id, limit)
    return [{"id": r.id, "label": getattr(r, "full_name", None)
             or getattr(r, "canonical_name", None) or getattr(r, "stage", r.id)}
            for r in rows]


# ── CRM: tasks ───────────────────────────────────────────────
class TaskReq(BaseModel):
    title: str
    due_at: Optional[datetime] = None
    assignee: str = "Puneet"
    priority: str = "med"
    related_type: Optional[str] = None
    related_id: Optional[str] = None
    parent_task_id: Optional[str] = None


@router.post("/crm/tasks")
def create_task(req: TaskReq, db: Session = Depends(get_db)):
    try:
        t = crm_ext.create_task(db, **req.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"task_id": t.id}


@router.post("/crm/tasks/{task_id}/complete")
def complete(task_id: str, db: Session = Depends(get_db)):
    t = crm_ext.complete_task(db, task_id)
    if t is None:
        raise HTTPException(status_code=404, detail="task not found")
    return {"task_id": t.id, "status": t.status}


@router.get("/crm/tasks/my-day/{assignee}")
def my_day(assignee: str, db: Session = Depends(get_db)):
    return crm_ext.my_day(db, assignee)


# ── Marketing upgrades ───────────────────────────────────────
class ScheduleReq(BaseModel):
    at: datetime


@router.post("/mkt/campaigns/{campaign_id}/schedule")
def schedule(campaign_id: str, req: ScheduleReq, db: Session = Depends(get_db)):
    try:
        c = marketing_ext.schedule_campaign(db, campaign_id, req.at)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"campaign_id": c.id, "status": c.status, "scheduled_at": c.scheduled_at}


@router.post("/mkt/run-scheduled")
def run_scheduled(respect_send_window: bool = True, db: Session = Depends(get_db)):
    return marketing_ext.run_scheduled(db, respect_send_window=respect_send_window)


@router.post("/mkt/campaigns/{campaign_id}/test-send")
def testsend(campaign_id: str, to_email: str = "test@example.invalid",
             db: Session = Depends(get_db)):
    return marketing_ext.test_send(db, campaign_id, to_email)


@router.post("/mkt/campaigns/{campaign_id}/ab-winner")
def abwin(campaign_id: str, metric: str = "open", db: Session = Depends(get_db)):
    return marketing_ext.ab_winner(db, campaign_id, metric)


# ── Delivery ops ─────────────────────────────────────────────
@router.post("/delivery/retry-failed")
def retry(db: Session = Depends(get_db)):
    return delivery_ext.retry_failed(db)


@router.post("/delivery/campaigns/{campaign_id}/health-check")
def health_check(campaign_id: str, db: Session = Depends(get_db)):
    return delivery_ext.check_campaign_health(db, campaign_id)


# ── PUBLIC landing pages ─────────────────────────────────────
@router.get("/p/{slug}", response_class=HTMLResponse)
def public_page(slug: str, db: Session = Depends(get_db)):
    html = landing_render.render_page(db, slug)
    if html is None:
        raise HTTPException(status_code=404, detail="page not found")
    return HTMLResponse(html)


@router.post("/p/{slug}/submit", response_class=HTMLResponse)
async def public_submit(slug: str, request: Request, db: Session = Depends(get_db)):
    form = dict(await request.form())
    utm = {k: v for k, v in request.query_params.items() if k.startswith("utm_")}
    visitor_id = request.cookies.get("drip_vid")
    html, ok = landing_render.handle_submit(db, slug, form, utm=utm, visitor_id=visitor_id)
    return HTMLResponse(html, status_code=200 if ok else 422)
