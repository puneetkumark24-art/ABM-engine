"""routers/journeys.py — Sprint 3: REST surface for marketing journey
orchestration. Mounted under /mkt so it inherits SCOPE_POLICY(/mkt ->
marketing.manage) and tenant scoping via get_db."""
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from abm_platform.services import journeys as jn

router = APIRouter(prefix="/mkt/journeys", tags=["journeys"])


class JourneyReq(BaseModel):
    name: str
    nodes: list[dict]
    entry_node_id: Optional[str] = None


@router.post("", status_code=201)
def create_journey(req: JourneyReq, db: Session = Depends(get_db)):
    try:
        j = jn.define_journey(db, req.name, req.nodes, req.entry_node_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"id": j.id, "name": j.name, "entry_node_id": j.entry_node_id,
            "nodes": len(j.nodes)}


class EnrollReq(BaseModel):
    person_id: str


@router.post("/{journey_id}/enroll", status_code=201)
def enroll(journey_id: str, req: EnrollReq, db: Session = Depends(get_db)):
    try:
        e = jn.enroll(db, journey_id, req.person_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"enrollment_id": e.id, "current_node_id": e.current_node_id}


@router.post("/tick")
def tick(db: Session = Depends(get_db)):
    """Advance all due enrollments once (worker/cron entrypoint)."""
    return jn.tick(db)


@router.get("/{journey_id}/enrollments")
def enrollments(journey_id: str, db: Session = Depends(get_db)):
    import models_s3 as m3
    rows = db.query(m3.JourneyEnrollment).filter_by(journey_id=journey_id).all()
    return [{"id": r.id, "person_id": r.person_id, "status": r.status,
             "current_node_id": r.current_node_id, "steps": len(r.history or [])}
            for r in rows]
