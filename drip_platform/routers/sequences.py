"""
routers/sequences.py — Sequence / Journey Engine API (Blueprint Module 08).

Thin FastAPI surface over sequences/engine.py. Every write goes through the
engine's policy layer so compliance gates and the account-centric pause are
enforced in one place, never bypassed by the API.
"""
from __future__ import annotations

from typing import Optional, List
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
import models
from sequences import engine as seq_engine

router = APIRouter(prefix="/sequences", tags=["sequences"])


# ---------- response/request shapes ----------
class StepOut(BaseModel):
    step_number: int
    channel: str
    wait_days_after_previous: int
    is_final: bool

    class Config:
        from_attributes = True


class SequenceOut(BaseModel):
    id: str
    name: str
    relationship_type: Optional[str] = None
    is_active: bool
    steps: List[StepOut] = []

    class Config:
        from_attributes = True


class EnrollRequest(BaseModel):
    person_id: str
    sequence_id: Optional[str] = None


class PauseRequest(BaseModel):
    reason: str = "manual"


class ReplyRequest(BaseModel):
    person_id: str
    reason: str = "reply"


# ---------- sequence definitions ----------
@router.get("", response_model=List[SequenceOut])
def list_sequences(db: Session = Depends(get_db)):
    return db.query(models.SequenceDefinition).all()


@router.post("/ensure-default", response_model=SequenceOut)
def ensure_default(db: Session = Depends(get_db)):
    return seq_engine.ensure_default_sequence(db)


# ---------- enrollment ----------
@router.post("/enroll")
def enroll(req: EnrollRequest, db: Session = Depends(get_db)):
    enr, reason = seq_engine.enroll_person(db, req.person_id, req.sequence_id)
    if enr is None:
        # compliance gate blocked it — 409 with the reason, not a silent success
        raise HTTPException(status_code=409, detail=f"enrollment blocked: {reason}")
    return {"enrollment_id": enr.id, "status": enr.status, "result": reason,
            "current_step": enr.current_step, "next_run_at": enr.next_run_at}


@router.post("/backfill")
def backfill(db: Session = Depends(get_db)):
    return seq_engine.backfill_enrollments(db)


# ---------- runtime ----------
@router.get("/due")
def due(limit: int = Query(20, le=200), respect_send_window: bool = True,
        db: Session = Depends(get_db)):
    rows = seq_engine.get_due(db, limit=limit, respect_send_window=respect_send_window)
    return [{
        "enrollment_id": r["enrollment"].id,
        "person_id": r["person"].id,
        "person_name": r["person"].full_name,
        "org_id": r["enrollment"].org_id,
        "next_step_number": r["next_step"].step_number,
        "channel": r["next_step"].channel,
        "tier": r["person"].tier,
    } for r in rows]


@router.post("/enrollments/{enrollment_id}/advance")
def advance(enrollment_id: str, db: Session = Depends(get_db)):
    enr = seq_engine.advance(db, enrollment_id)
    if enr is None:
        raise HTTPException(status_code=404, detail="enrollment not found")
    return {"enrollment_id": enr.id, "status": enr.status,
            "current_step": enr.current_step, "next_run_at": enr.next_run_at}


@router.post("/enrollments/{enrollment_id}/pause")
def pause(enrollment_id: str, req: PauseRequest, db: Session = Depends(get_db)):
    enr = seq_engine.pause(db, enrollment_id, req.reason)
    if enr is None:
        raise HTTPException(status_code=404, detail="enrollment not found")
    return {"enrollment_id": enr.id, "status": enr.status, "pause_reason": enr.pause_reason}


@router.post("/enrollments/{enrollment_id}/resume")
def resume(enrollment_id: str, db: Session = Depends(get_db)):
    enr = seq_engine.resume(db, enrollment_id)
    if enr is None:
        raise HTTPException(status_code=404, detail="enrollment not found")
    return {"enrollment_id": enr.id, "status": enr.status, "next_run_at": enr.next_run_at}


@router.post("/reply")
def reply(req: ReplyRequest, db: Session = Depends(get_db)):
    """Register a reply — pauses the person AND the whole account (ACC-001)."""
    return seq_engine.pause_on_reply(db, req.person_id, req.reason)


@router.get("/enrollments/{enrollment_id}/events")
def enrollment_events(enrollment_id: str, db: Session = Depends(get_db)):
    evs = (db.query(models.SequenceEnrollmentEvent)
           .filter(models.SequenceEnrollmentEvent.enrollment_id == enrollment_id)
           .order_by(models.SequenceEnrollmentEvent.created_at).all())
    return [{"event_type": e.event_type, "step_number": e.step_number,
             "detail": e.detail, "created_at": e.created_at} for e in evs]
