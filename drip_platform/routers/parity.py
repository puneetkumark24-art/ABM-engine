"""routers/parity.py — Parity Mission API surface: LLM core (prompts, calls,
eval, analytics), signal collectors, and segments/lists."""
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from abm_platform.services import llm_core, collectors, segments as seg

router = APIRouter(tags=["parity"])


# ── LLM core ────────────────────────────────────────────────
@router.get("/ai/prompts")
def prompts():
    return llm_core.list_prompts()


class PromptReq(BaseModel):
    name: str
    template: str
    note: str = ""


@router.post("/ai/prompts", status_code=201)
def register_prompt(req: PromptReq):
    v = llm_core.register_prompt(req.name, req.template, req.note)
    return {"name": req.name, "version": v["version"], "active": True}


@router.post("/ai/prompts/{name}/rollback/{version}")
def rollback(name: str, version: int):
    try:
        v = llm_core.rollback_prompt(name, version)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"name": name, "active_version": v["version"]}


class LlmCallReq(BaseModel):
    prompt_name: str
    variables: dict = {}
    purpose: str = "general"


@router.post("/ai/call")
def call(req: LlmCallReq, db: Session = Depends(get_db)):
    try:
        return llm_core.call_llm(db, req.prompt_name, req.variables, req.purpose)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


class EvalReq(BaseModel):
    cases: list[dict]


@router.post("/ai/prompts/{name}/evaluate")
def evaluate(name: str, req: EvalReq, db: Session = Depends(get_db)):
    return llm_core.evaluate_prompt(db, name, req.cases)


@router.get("/ai/analytics")
def ai_analytics(db: Session = Depends(get_db)):
    return llm_core.llm_analytics(db)


# ── collectors ───────────────────────────────────────────────
@router.get("/abm/collectors")
def sources(db: Session = Depends(get_db)):
    return collectors.sources_health(db)


class SourceReq(BaseModel):
    name: str
    url: str
    kind: str = "rss"
    signal_type: str = "news"
    interval_minutes: int = 60


@router.post("/abm/collectors", status_code=201)
def add_source(req: SourceReq, db: Session = Depends(get_db)):
    s = collectors.add_source(db, req.name, req.url, req.kind,
                              req.signal_type, req.interval_minutes)
    return {"id": s.id, "name": s.name}


@router.post("/abm/collectors/seed")
def seed(db: Session = Depends(get_db)):
    return {"added": collectors.seed_default_sources(db)}


@router.post("/abm/collectors/run")
def run(db: Session = Depends(get_db)):
    """Fetch all due sources NOW (also wired for cron/worker)."""
    return collectors.run_due(db)


# ── segments & lists ─────────────────────────────────────────
class SegmentReq(BaseModel):
    name: str
    conditions: list[dict] = []
    is_dynamic: bool = True


@router.post("/crm/segments", status_code=201)
def create_segment(req: SegmentReq, db: Session = Depends(get_db)):
    try:
        s = seg.create_segment(db, req.name, req.conditions, req.is_dynamic)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"id": s.id, "name": s.name}


@router.get("/crm/segments/{segment_id}")
def segment(segment_id: str, db: Session = Depends(get_db)):
    try:
        return seg.segment_summary(db, segment_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=404, detail="segment not found")


class MemberReq(BaseModel):
    person_id: str


@router.post("/crm/segments/{segment_id}/members")
def add_member(segment_id: str, req: MemberReq, db: Session = Depends(get_db)):
    try:
        added = seg.add_to_list(db, segment_id, req.person_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"added": added}


@router.delete("/crm/segments/{segment_id}/members/{person_id}")
def remove_member(segment_id: str, person_id: str, db: Session = Depends(get_db)):
    return {"removed": seg.remove_from_list(db, segment_id, person_id)}
