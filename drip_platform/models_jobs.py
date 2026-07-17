"""
models_jobs.py — P0-B async substrate: transactional outbox + durable job queue.

Two tables, additive:

- `outbox` — events written in the SAME transaction as the state change that
  produced them. A relay worker publishes them to the bus and marks them done.
  This is the transactional-outbox pattern: events can never be lost on rollback
  and never emitted for a rolled-back change (fixes BOMB 3's durability gap).

- `jobs` — a durable work queue in Postgres. Workers claim rows with
  `FOR UPDATE SKIP LOCKED` so N workers never double-process the same job
  (fixes BOMB 5). Retries with backoff, dead-letter after max attempts, unique
  idempotency key to dedupe enqueues.

Postgres is a perfectly good queue at this scale (thousands/day). Redis Streams
/ Kafka become worth it only when throughput or fan-out to many independent
consumers demands it — the worker interface here is identical either way.
"""
from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Integer, Text, DateTime, JSON, Index, UniqueConstraint
)
from database import Base


def uid() -> str:
    return str(uuid.uuid4())


class Outbox(Base):
    __tablename__ = "outbox"
    id = Column(String(36), primary_key=True, default=uid)
    tenant_id = Column(String(36))
    event_type = Column(String, nullable=False)
    event_key = Column(String)                     # ordering/partition key (e.g. account_id)
    payload = Column(JSON, default=dict)
    status = Column(String, default="pending")     # pending / published / failed
    attempts = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    published_at = Column(DateTime)
    __table_args__ = (Index("idx_outbox_status", "status", "created_at"),)


class Job(Base):
    __tablename__ = "jobs"
    id = Column(String(36), primary_key=True, default=uid)
    tenant_id = Column(String(36))
    kind = Column(String, nullable=False)          # e.g. sequence_step / ai_generate / send_email
    payload = Column(JSON, default=dict)
    status = Column(String, default="queued")      # queued / running / done / failed / dead
    priority = Column(Integer, default=100)        # lower = higher priority
    attempts = Column(Integer, default=0)
    max_attempts = Column(Integer, default=5)
    run_after = Column(DateTime, default=datetime.utcnow)   # backoff / scheduling
    idempotency_key = Column(String)               # dedupe re-enqueues
    locked_by = Column(String)                     # worker id holding the claim
    locked_at = Column(DateTime)
    last_error = Column(Text)
    result = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime)
    __table_args__ = (
        UniqueConstraint("kind", "idempotency_key"),
        Index("idx_jobs_claim", "status", "priority", "run_after"),
    )


JOBS_TABLES = [Outbox, Job]
