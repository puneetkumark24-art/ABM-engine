"""routers/abm_intel.py — Sprint 4: ABM Intelligence REST surface (buying-
committee inference + coverage, deduped signal ingest, account scoring).
Mounted under /abm; add ('/abm','abm.read') to SCOPE_POLICY when enforcing."""
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from abm_platform.services import abm_intel as ai

router = APIRouter(prefix="/abm", tags=["abm-intel"])


@router.post("/committee/{org_id}/infer")
def infer_committee(org_id: str, product_id: Optional[str] = None,
                    db: Session = Depends(get_db)):
    return ai.infer_committee(db, org_id, product_id)


@router.get("/committee/{org_id}/coverage")
def coverage(org_id: str, product_id: Optional[str] = None,
             db: Session = Depends(get_db)):
    return ai.committee_coverage(db, org_id, product_id)


class SignalReq(BaseModel):
    org_id: str
    signal_type: str
    source: str
    title: str
    summary: str = ""
    url: Optional[str] = None
    urgency: str = "medium"


@router.post("/signals/ingest")
def ingest(req: SignalReq, db: Session = Depends(get_db)):
    s, created = ai.ingest_signal(db, req.org_id, req.signal_type, req.source,
                                  req.title, req.summary, req.url, req.urgency)
    return {"signal_id": s.id, "created": created, "deduped": not created}


@router.post("/accounts/{org_id}/score")
def score(org_id: str, db: Session = Depends(get_db)):
    row = ai.score_account(db, org_id)
    return {"org_id": org_id, "total_score": row.total_score, "tier": row.tier,
            "signal_score": row.signal_score, "relationship_score": row.relationship_score,
            "notes": row.notes}
