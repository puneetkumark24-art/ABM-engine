"""routers/engine_e2e.py — Phase 10: pipeline, engagement, merge, timeline,
and the end-to-end orchestrator tick."""
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
from abm_platform.services import engagement, pipeline, merge, timeline, orchestrator

router = APIRouter(prefix="/engine", tags=["engine-e2e"])


# ---- orchestrator ----
@router.post("/tick")
def tick(limit: int = Query(10, le=100), respect_send_window: bool = True,
         db: Session = Depends(get_db)):
    """One full engine cycle: due -> draft -> dry-run send -> advance -> rollup
    -> rescore -> re-tier. Transport is dry_run only; c-suite drafts held."""
    return orchestrator.run_tick(db, limit=limit, respect_send_window=respect_send_window)


# ---- engagement / scoring loop ----
@router.post("/engagement/rollup/{org_id}")
def rollup(org_id: str, db: Session = Depends(get_db)):
    return engagement.rollup_org(db, org_id)


@router.post("/engagement/person/{person_id}")
def rollup_person(person_id: str, db: Session = Depends(get_db)):
    pe = engagement.rollup_person(db, person_id)
    return {"person_id": person_id, "engagement_score": pe.engagement_score,
            "opens": pe.opens, "clicks": pe.clicks, "replies": pe.replies}


# ---- pipeline engine ----
class PipelineReq(BaseModel):
    name: str
    stages: Optional[list[dict]] = None
    is_default: bool = False


@router.post("/pipelines")
def mk_pipeline(req: PipelineReq, db: Session = Depends(get_db)):
    pl = pipeline.create_pipeline(db, req.name, req.stages, req.is_default)
    return {"pipeline_id": pl.id,
            "stages": [{"name": s.name, "order": s.order, "probability": s.probability}
                       for s in pipeline.stages(db, pl.id)]}


class AssignReq(BaseModel):
    opportunity_id: str
    pipeline_id: str
    stage_name: Optional[str] = None


@router.post("/pipelines/assign")
def assign(req: AssignReq, db: Session = Depends(get_db)):
    try:
        link = pipeline.assign_deal(db, req.opportunity_id, req.pipeline_id, req.stage_name)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"link_id": link.id, "stage_id": link.stage_id}


class MoveReq(BaseModel):
    to_stage: str
    reason: Optional[str] = None


@router.post("/deals/{opportunity_id}/move")
def move(opportunity_id: str, req: MoveReq, db: Session = Depends(get_db)):
    try:
        link = pipeline.move_deal(db, opportunity_id, req.to_stage, by="api", reason=req.reason)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"opportunity_id": opportunity_id, "history": link.history}


@router.get("/pipelines/{pipeline_id}/forecast")
def fc(pipeline_id: str, db: Session = Depends(get_db)):
    return pipeline.forecast(db, pipeline_id)


@router.get("/pipelines/{pipeline_id}/health")
def hp(pipeline_id: str, db: Session = Depends(get_db)):
    return pipeline.health(db, pipeline_id)


# ---- merge ----
class MergeReq(BaseModel):
    keep_id: str
    lose_id: str


@router.post("/merge/persons")
def do_merge(req: MergeReq, db: Session = Depends(get_db)):
    try:
        return merge.merge_persons(db, req.keep_id, req.lose_id, actor="api")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


# ---- timeline ----
@router.get("/timeline/person/{person_id}")
def tl_person(person_id: str, limit: int = 100, db: Session = Depends(get_db)):
    return timeline.person_timeline(db, person_id, limit)


@router.get("/timeline/org/{org_id}")
def tl_org(org_id: str, limit: int = 100, db: Session = Depends(get_db)):
    return timeline.org_timeline(db, org_id, limit)
