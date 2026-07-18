"""routers/security_compliance.py — Sprint 9: PDPL data-subject requests +
consent management. Mounted under /compliance; add ('/compliance','admin.full')
to SCOPE_POLICY when enforcing (erasure/export are privileged)."""
from __future__ import annotations
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from abm_platform.services import security_compliance as sc

router = APIRouter(prefix="/compliance", tags=["security-compliance"])


@router.get("/subjects/{person_id}/export")
def export_subject(person_id: str, db: Session = Depends(get_db)):
    try:
        return sc.export_subject(db, person_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/subjects/{person_id}/erase")
def erase_subject(person_id: str, db: Session = Depends(get_db)):
    try:
        return sc.erase_subject(db, person_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


class ConsentReq(BaseModel):
    status: str
    source: str = "web"


@router.post("/subjects/{person_id}/consent")
def set_consent(person_id: str, req: ConsentReq, db: Session = Depends(get_db)):
    try:
        return sc.set_consent(db, person_id, req.status, req.source)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
