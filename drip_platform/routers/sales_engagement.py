"""routers/sales_engagement.py — Sprint 5: reply handling, step A/B, hot leads.
Mounted under /sales; add ('/sales','sequences.manage') to SCOPE_POLICY when
enforcing."""
from __future__ import annotations
from pydantic import BaseModel
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from abm_platform.services import sales_engagement as se

router = APIRouter(prefix="/sales", tags=["sales-engagement"])


class ReplyReq(BaseModel):
    person_id: str
    text: str


@router.post("/replies")
def handle_reply(req: ReplyReq, db: Session = Depends(get_db)):
    return se.handle_reply(db, req.person_id, req.text)


class StepVariantsReq(BaseModel):
    variants: list[dict]


@router.post("/steps/{step_id}/variants")
def register_variants(step_id: str, req: StepVariantsReq, db: Session = Depends(get_db)):
    n = se.register_step_variants(db, step_id, req.variants)
    return {"step_id": step_id, "registered": n}


@router.get("/steps/{step_id}/pick")
def pick(step_id: str, db: Session = Depends(get_db)):
    return {"step_id": step_id, "variant_key": se.pick_step_variant(db, step_id)}


class OutcomeReq(BaseModel):
    variant_key: str
    event: str = "send"


@router.post("/steps/{step_id}/outcome")
def outcome(step_id: str, req: OutcomeReq, db: Session = Depends(get_db)):
    row = se.record_step_outcome(db, step_id, req.variant_key, req.event)
    return {"variant_key": row.variant_key, "sends": row.sends, "replies": row.replies,
            "score": row.score}


@router.get("/hot-leads")
def hot_leads(limit: int = 20, db: Session = Depends(get_db)):
    return se.hot_leads(db, limit)
