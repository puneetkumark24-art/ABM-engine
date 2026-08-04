"""
routers/pipeline_ops.py — Pipeline Operations: the screens the backend was
always missing.

Every piece of this (Draft, DecisionLog, SequenceEnrollment) already existed
as a real, working table populated by real services (abm_platform.services
.orchestrator, .decision, sequences.engine) -- there was simply no way to see
any of it without querying Postgres directly or reading raw JSON from a CLI
script. This router adds visibility and human control (approve/reject/edit a
draft) on top of the existing service layer -- it does not introduce a
second code path. Approving/rejecting here only ever flips models.Draft.status;
delivery is still hardcoded dry_run in orchestrator.py/delivery.py regardless.

Paginated throughout (PAGE_SIZE): this has to hold up at 30k contacts / 500
institutions, not just today's handful of test rows. Every list query is a
single bulk name-lookup for persons/orgs, not N+1.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
import models
import models_p11 as p11

router = APIRouter(tags=["pipeline-ops"])
PAGE_SIZE = 50


def _bulk_names(db: Session, rows: list, person_attr: str = "person_id",
                org_attr: str = "org_id") -> tuple[dict, dict]:
    person_ids = {getattr(r, person_attr) for r in rows if getattr(r, person_attr, None)}
    org_ids = {getattr(r, org_attr) for r in rows if getattr(r, org_attr, None)}
    persons = ({p.id: p for p in db.query(models.Person)
               .filter(models.Person.id.in_(person_ids)).all()} if person_ids else {})
    orgs = ({o.id: o for o in db.query(models.Organization)
            .filter(models.Organization.id.in_(org_ids)).all()} if org_ids else {})
    return persons, orgs


# ───────────────────────── Drafts / Approvals queue ─────────────────────────
@router.get("/drafts")
def list_drafts(status: str = "", org_id: str = "", person_id: str = "",
                channel: str = "", page: int = Query(1, ge=1), db: Session = Depends(get_db)):
    q = db.query(models.Draft)
    if status:
        q = q.filter(models.Draft.status == status)
    if org_id:
        q = q.filter(models.Draft.org_id == org_id)
    if person_id:
        q = q.filter(models.Draft.person_id == person_id)
    if channel:
        q = q.filter(models.Draft.channel == channel)
    total = q.count()
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    rows = (q.order_by(models.Draft.created_at.desc())
            .offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE).all())
    persons, orgs = _bulk_names(db, rows)
    status_counts = {s: db.query(models.Draft).filter(models.Draft.status == s).count()
                     for s in ("pending", "approved", "rejected", "sent")}
    return {"page": page, "pages": pages, "total": total, "status_counts": status_counts,
            "drafts": [{
                "id": d.id, "status": d.status, "channel": d.channel,
                "subject": d.subject, "body": d.body, "source": d.source,
                "sequence_step": d.sequence_step, "person_id": d.person_id,
                "person_name": persons[d.person_id].full_name if d.person_id in persons else None,
                "seniority": persons[d.person_id].seniority_level if d.person_id in persons else None,
                "org_id": d.org_id,
                "org_name": orgs[d.org_id].canonical_name if d.org_id in orgs else None,
                "created_at": d.created_at, "reviewed_at": d.reviewed_at, "sent_at": d.sent_at,
                "reviewer_notes": d.reviewer_notes,
            } for d in rows]}


class DraftDecision(BaseModel):
    reviewer_notes: Optional[str] = None


class DraftEdit(BaseModel):
    subject: Optional[str] = None
    body: Optional[str] = None


@router.patch("/drafts/{draft_id}")
def edit_draft(draft_id: str, req: DraftEdit, db: Session = Depends(get_db)):
    d = db.get(models.Draft, draft_id)
    if d is None:
        raise HTTPException(404, "draft not found")
    # Pending-only: once approved, the content is what was reviewed and
    # authorized. Allowing edits after approval would let someone approve X
    # then silently change it to Y before the next tick dispatches it --
    # Y would ship without ever having been the thing a human actually saw.
    if d.status != "pending":
        raise HTTPException(409, f"only a pending draft can be edited (status={d.status})")
    if req.subject is not None:
        d.subject = req.subject
    if req.body is not None:
        d.body = req.body
    if not (d.body or "").strip():
        raise HTTPException(422, "draft body cannot be empty")
    db.commit()
    return {"id": d.id, "status": d.status, "subject": d.subject, "body": d.body}


@router.post("/drafts/{draft_id}/approve")
def approve_draft(draft_id: str, req: DraftDecision, db: Session = Depends(get_db)):
    d = db.get(models.Draft, draft_id)
    if d is None:
        raise HTTPException(404, "draft not found")
    if d.status != "pending":
        raise HTTPException(409, f"only a pending draft can be approved (status={d.status})")
    if not d.person_id or not (d.body or "").strip():
        raise HTTPException(422, "draft requires a linked contact and non-empty body")
    person = db.get(models.Person, d.person_id)
    from sequences.engine import is_contactable
    contactable, reason = is_contactable(person)
    if not contactable:
        raise HTTPException(409, f"contact is not eligible for outreach: {reason}")
    if not person.primary_email:
        raise HTTPException(409, "contact has no primary email")
    d.status = "approved"
    d.reviewed_at = datetime.utcnow()
    if req.reviewer_notes:
        d.reviewer_notes = req.reviewer_notes
    db.commit()
    return {"id": d.id, "status": d.status}


@router.post("/drafts/{draft_id}/reject")
def reject_draft(draft_id: str, req: DraftDecision, db: Session = Depends(get_db)):
    d = db.get(models.Draft, draft_id)
    if d is None:
        raise HTTPException(404, "draft not found")
    if d.status not in ("pending", "approved"):
        raise HTTPException(409, f"cannot reject a draft in status={d.status}")
    if not (req.reviewer_notes or "").strip():
        raise HTTPException(422, "a rejection reason is required")
    d.status = "rejected"
    d.reviewed_at = datetime.utcnow()
    if req.reviewer_notes:
        d.reviewer_notes = req.reviewer_notes
    db.commit()
    return {"id": d.id, "status": d.status}


# ───────────────────────── AI Decision log ─────────────────────────
@router.get("/decisions")
def list_decisions(person_id: str = "", org_id: str = "", page: int = Query(1, ge=1),
                   db: Session = Depends(get_db)):
    q = db.query(p11.DecisionLog)
    if person_id:
        q = q.filter(p11.DecisionLog.person_id == person_id)
    if org_id:
        q = q.filter(p11.DecisionLog.org_id == org_id)
    total = q.count()
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    rows = (q.order_by(p11.DecisionLog.created_at.desc())
            .offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE).all())
    persons, _ = _bulk_names(db, rows)
    return {"page": page, "pages": pages, "total": total,
            "decisions": [{
                "id": d.id, "action": d.action, "channel": d.channel,
                "wait_hours": d.wait_hours, "content_hint": d.content_hint,
                "confidence": d.confidence, "reasons": d.reasons or [],
                "executed": bool(d.executed), "outcome": d.outcome,
                "person_id": d.person_id,
                "person_name": persons[d.person_id].full_name if d.person_id in persons else None,
                "org_id": d.org_id, "created_at": d.created_at,
            } for d in rows]}
