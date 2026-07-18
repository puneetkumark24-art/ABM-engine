"""routers/unified.py — Platform Unification API surface: global search,
executive dashboard, email analytics, GA4 seam, and the capability registry /
feature-parity dashboard."""
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from abm_platform.services import unified
import capability_registry as reg

router = APIRouter(tags=["unified"])


@router.get("/search")
def search(q: str, db: Session = Depends(get_db)):
    return unified.global_search(db, q)


@router.get("/dashboard/executive")
def executive(db: Session = Depends(get_db)):
    return unified.executive_dashboard(db)


@router.get("/analytics/email")
def email_analytics(campaign_id: Optional[str] = None, since_days: int = 90,
                    db: Session = Depends(get_db)):
    return unified.email_analytics(db, campaign_id, since_days)


@router.get("/analytics/ga4/status")
def ga4_status():
    return unified.ga4_status()


class Ga4EventReq(BaseModel):
    client_id: str
    name: str
    params: dict = {}


@router.post("/analytics/ga4/event")
def ga4_event(req: Ga4EventReq):
    return unified.ga4_send_event(req.client_id, req.name, req.params)


@router.get("/platform/capabilities")
def capabilities():
    return {"summary": reg.summary(), "modules": reg.by_module()}


@router.get("/platform/parity")
def parity():
    return reg.parity_dashboard()
