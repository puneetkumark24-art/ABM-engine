"""
jobs.py — durable queue + worker runtime (P0-B).

enqueue()          add a job (idempotent by kind+idempotency_key)
claim_batch()      atomically claim N due jobs with FOR UPDATE SKIP LOCKED
                   (Postgres) — the mechanism that makes multiple workers safe.
run_once()         claim → run registered handler → complete/retry/dead-letter
register()         map a job kind to a handler(session, payload) -> dict
outbox_emit()      write an event to the outbox in the caller's transaction
relay_outbox()     publish pending outbox rows to the in-proc bus (or Redis/Kafka
                   later) — same interface.

Backoff is exponential; exhausted jobs go to 'dead' (never silently dropped).
On SQLite the claim degrades to a plain UPDATE (single-worker dev); the
concurrency guarantee is a Postgres property and is tested there.
"""
from __future__ import annotations
import logging
import os
import socket
from datetime import datetime, timedelta
from typing import Callable, Optional
from sqlalchemy import text
from sqlalchemy.orm import Session
from database import SessionLocal
import models_jobs as mj
from abm_platform.events import Event, publish

logger = logging.getLogger("drip.jobs")
WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"
BACKOFF_SECONDS = [10, 60, 300, 1800, 7200]

_HANDLERS: dict[str, Callable[[Session, dict], dict]] = {}


def register(kind: str, handler: Callable[[Session, dict], dict]) -> None:
    _HANDLERS[kind] = handler


# ── enqueue ──────────────────────────────────────────────────
def enqueue(db: Session, kind: str, payload: dict, tenant_id: Optional[str] = None,
            priority: int = 100, idempotency_key: Optional[str] = None,
            run_after: Optional[datetime] = None) -> Optional[mj.Job]:
    """Idempotent by (kind, idempotency_key). Returns the existing job if the
    key is already queued/running (dedupe), else the new job."""
    if idempotency_key:
        existing = (db.query(mj.Job)
                    .filter(mj.Job.kind == kind,
                            mj.Job.idempotency_key == idempotency_key).first())
        if existing:
            return existing
    job = mj.Job(kind=kind, payload=payload, tenant_id=tenant_id, priority=priority,
                 idempotency_key=idempotency_key,
                 run_after=run_after or datetime.utcnow())
    db.add(job)
    db.commit()
    return job


# ── claim (the concurrency-safe core) ────────────────────────
def claim_batch(db: Session, limit: int = 10) -> list[mj.Job]:
    """Atomically claim up to `limit` due jobs. On Postgres uses
    FOR UPDATE SKIP LOCKED so concurrent workers never grab the same row."""
    now = datetime.utcnow()
    is_pg = db.bind.dialect.name == "postgresql"
    if is_pg:
        rows = db.execute(text("""
            SELECT id FROM jobs
            WHERE status = 'queued' AND run_after <= :now
            ORDER BY priority ASC, run_after ASC
            LIMIT :lim
            FOR UPDATE SKIP LOCKED
        """), {"now": now, "lim": limit}).fetchall()
        ids = [r[0] for r in rows]
    else:
        ids = [j.id for j in (db.query(mj.Job)
               .filter(mj.Job.status == "queued", mj.Job.run_after <= now)
               .order_by(mj.Job.priority, mj.Job.run_after).limit(limit).all())]
    if not ids:
        return []
    jobs = db.query(mj.Job).filter(mj.Job.id.in_(ids)).all()
    for j in jobs:
        j.status = "running"
        j.locked_by = WORKER_ID
        j.locked_at = now
        j.attempts += 1
    db.commit()
    return jobs


def _complete(db: Session, job: mj.Job, result: dict) -> None:
    job.status = "done"; job.result = result; job.finished_at = datetime.utcnow()
    db.commit()


def _fail(db: Session, job: mj.Job, err: str) -> None:
    if job.attempts >= job.max_attempts:
        job.status = "dead"; job.last_error = err; job.finished_at = datetime.utcnow()
        logger.error("job %s (%s) dead after %d attempts: %s", job.id, job.kind, job.attempts, err)
        publish(Event("job.dead", key=job.id, payload={"kind": job.kind, "error": err}))
    else:
        backoff = BACKOFF_SECONDS[min(job.attempts - 1, len(BACKOFF_SECONDS) - 1)]
        job.status = "queued"; job.last_error = err
        job.run_after = datetime.utcnow() + timedelta(seconds=backoff)
        job.locked_by = None; job.locked_at = None
    db.commit()


def run_once(db: Session, limit: int = 10) -> dict:
    """Claim and execute a batch. Each job runs the registered handler; the
    handler's exceptions become retries/dead-letters — never a lost job."""
    jobs = claim_batch(db, limit)
    done = failed = 0
    for job in jobs:
        handler = _HANDLERS.get(job.kind)
        if handler is None:
            _fail(db, job, f"no handler for kind '{job.kind}'"); failed += 1; continue
        try:
            result = handler(db, job.payload or {})
            _complete(db, job, result or {}); done += 1
        except Exception as e:
            db.rollback()
            _fail(db, job, str(e)); failed += 1
    return {"claimed": len(jobs), "done": done, "failed": failed}


def run_worker(poll_seconds: float = 1.0, batch: int = 10, max_iterations: Optional[int] = None):
    """Long-running worker loop (call from a process/container). Bounded by
    max_iterations in tests."""
    import time
    i = 0
    while max_iterations is None or i < max_iterations:
        db = SessionLocal()
        try:
            res = run_once(db, batch)
        finally:
            db.close()
        if res["claimed"] == 0:
            time.sleep(poll_seconds)
        i += 1


# ── transactional outbox ─────────────────────────────────────
def outbox_emit(db: Session, event_type: str, event_key: Optional[str] = None,
                payload: Optional[dict] = None, tenant_id: Optional[str] = None) -> mj.Outbox:
    """Write an event to the outbox in the CALLER's transaction. Do NOT commit
    here — the caller commits, atomically binding the event to the state change."""
    row = mj.Outbox(event_type=event_type, event_key=event_key,
                    payload=payload or {}, tenant_id=tenant_id)
    db.add(row)
    return row


def relay_outbox(db: Session, limit: int = 100) -> dict:
    """Publish pending outbox rows to the bus. Runs in its own worker; failures
    stay pending and are retried. (Swap `publish` for Redis/Kafka later.)"""
    is_pg = db.bind.dialect.name == "postgresql"
    if is_pg:
        rows = db.execute(text("""
            SELECT id FROM outbox WHERE status='pending'
            ORDER BY created_at LIMIT :lim FOR UPDATE SKIP LOCKED
        """), {"lim": limit}).fetchall()
        ids = [r[0] for r in rows]
        pend = db.query(mj.Outbox).filter(mj.Outbox.id.in_(ids)).all() if ids else []
    else:
        pend = (db.query(mj.Outbox).filter(mj.Outbox.status == "pending")
                .order_by(mj.Outbox.created_at).limit(limit).all())
    published = 0
    for row in pend:
        try:
            publish(Event(row.event_type, key=row.event_key, payload=row.payload or {}))
            row.status = "published"; row.published_at = datetime.utcnow()
            published += 1
        except Exception as e:
            row.attempts += 1; row.status = "failed" if row.attempts > 5 else "pending"
            logger.warning("outbox relay failed for %s: %s", row.id, e)
    db.commit()
    return {"published": published, "scanned": len(pend)}
