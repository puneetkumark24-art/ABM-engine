"""routers/workflow_durable.py — Sprint 6: read/ops surface for durable workflow
execution (dead-letter queue inspection + manual retry trigger). Execution itself
is driven by workers, not HTTP. Mounted under /workflow."""
from __future__ import annotations
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from abm_platform.services import workflow_durable as wd

router = APIRouter(prefix="/workflow", tags=["workflow-durable"])


@router.get("/dead-letters")
def dead_letters(limit: int = 100, db: Session = Depends(get_db)):
    return wd.dead_letters(db, limit)


@router.get("/step-executions/{run_id}")
def run_steps(run_id: str, db: Session = Depends(get_db)):
    import models_s6 as m6
    rows = db.query(m6.WorkflowStepExecution).filter_by(run_id=run_id).all()
    return [{"node_id": r.node_id, "status": r.status, "attempts": r.attempts,
             "max_attempts": r.max_attempts, "error": r.last_error} for r in rows]
