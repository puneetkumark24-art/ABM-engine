"""
workflow_durable.py — Sprint 6: durable step execution for the workflow engine.

Guarantees:
  • Idempotency  — a (run, node, idempotency_key) that already succeeded returns
    its cached result and never re-executes the side effect.
  • Bounded retry — failures increment attempts and schedule an exponential
    backoff; retry_due() re-runs steps whose backoff has elapsed.
  • Dead-letter  — once attempts reach max_attempts the step is parked in
    'dead_letter' for human/ops attention instead of retrying forever.

Actions are plain callables `fn(ctx) -> dict`. retry_due() resolves the callable
for a parked step via a registry so a worker can drive retries generically.
"""
from __future__ import annotations
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
import models_s6 as m6

_BACKOFF_BASE_SECONDS = 30


def _ledger(db: Session, run_id: str, node_id: str, key: str,
            max_attempts: int) -> m6.WorkflowStepExecution:
    row = (db.query(m6.WorkflowStepExecution)
           .filter_by(run_id=run_id, node_id=node_id, idempotency_key=key).first())
    if row is None:
        row = m6.WorkflowStepExecution(run_id=run_id, node_id=node_id,
                                       idempotency_key=key, status="pending",
                                       attempts=0, max_attempts=max_attempts)
        db.add(row); db.flush()
    return row


def execute_step(db: Session, run_id: str, node_id: str, action_fn,
                 ctx: dict | None = None, idempotency_key: str | None = None,
                 max_attempts: int = 3, now: datetime | None = None) -> dict:
    """Execute one workflow step durably. Returns
    {status, attempts, result?, error?, dead_letter?}."""
    now = now or datetime.utcnow()
    key = idempotency_key or f"{run_id}:{node_id}"
    row = _ledger(db, run_id, node_id, key, max_attempts)

    if row.status == "succeeded":                 # idempotent short-circuit
        return {"status": "succeeded", "attempts": row.attempts,
                "result": row.result, "idempotent_replay": True}
    if row.status == "dead_letter":
        return {"status": "dead_letter", "attempts": row.attempts,
                "error": row.last_error}

    row.attempts = (row.attempts or 0) + 1
    try:
        result = action_fn(ctx or {}) or {}
        row.status = "succeeded"; row.result = result; row.last_error = None
        row.next_attempt_at = None
        db.commit()
        return {"status": "succeeded", "attempts": row.attempts, "result": result}
    except Exception as e:                          # noqa: BLE001 — durable boundary
        row.last_error = f"{type(e).__name__}: {e}"
        if row.attempts >= (row.max_attempts or max_attempts):
            row.status = "dead_letter"; row.next_attempt_at = None
            db.commit()
            return {"status": "dead_letter", "attempts": row.attempts,
                    "error": row.last_error, "dead_letter": True}
        row.status = "failed"
        backoff = _BACKOFF_BASE_SECONDS * (2 ** (row.attempts - 1))
        row.next_attempt_at = now + timedelta(seconds=backoff)
        db.commit()
        return {"status": "failed", "attempts": row.attempts,
                "error": row.last_error, "retry_at": str(row.next_attempt_at)}


def retry_due(db: Session, resolver, now: datetime | None = None,
              max_batch: int = 200) -> dict:
    """Re-run failed steps whose backoff elapsed. `resolver(row) -> (fn, ctx)`
    supplies the callable + context for a parked step."""
    now = now or datetime.utcnow()
    due = (db.query(m6.WorkflowStepExecution)
           .filter(m6.WorkflowStepExecution.status == "failed",
                   m6.WorkflowStepExecution.next_attempt_at <= now)
           .limit(max_batch).all())
    retried = succeeded = dead = 0
    for row in due:
        fn, ctx = resolver(row)
        retried += 1
        res = execute_step(db, row.run_id, row.node_id, fn, ctx=ctx,
                           idempotency_key=row.idempotency_key,
                           max_attempts=row.max_attempts, now=now)
        if res["status"] == "succeeded":
            succeeded += 1
        elif res["status"] == "dead_letter":
            dead += 1
    return {"retried": retried, "succeeded": succeeded, "dead_lettered": dead}


def dead_letters(db: Session, limit: int = 100) -> list[dict]:
    rows = (db.query(m6.WorkflowStepExecution)
            .filter_by(status="dead_letter").limit(limit).all())
    return [{"id": r.id, "run_id": r.run_id, "node_id": r.node_id,
             "attempts": r.attempts, "error": r.last_error} for r in rows]
