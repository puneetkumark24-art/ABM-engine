"""
models_s6.py — Sprint 6 (Workflow durability): a step-execution ledger giving
the existing workflow engine idempotency, bounded retries, and a dead-letter
state (Temporal/Marketo-durability parity) without replacing the engine.

One additive table. A row is the durable record of one (run, node) execution
attempt-set, keyed by an idempotency_key so re-delivery never double-executes.
"""
from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Integer, JSON, Text, UniqueConstraint, Index
from database import Base


def _id() -> str:
    return str(uuid.uuid4())


class WorkflowStepExecution(Base):
    __tablename__ = "workflow_step_executions"
    id = Column(String(36), primary_key=True, default=_id)
    tenant_id = Column(String(36), index=True)
    run_id = Column(String(36), index=True, nullable=False)
    node_id = Column(String(64), nullable=False)
    idempotency_key = Column(String(120), nullable=False)
    status = Column(String(20), default="pending")   # pending|succeeded|failed|dead_letter
    attempts = Column(Integer, default=0)
    max_attempts = Column(Integer, default=3)
    next_attempt_at = Column(DateTime, index=True)
    last_error = Column(Text)
    result = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("run_id", "node_id", "idempotency_key", name="uq_wf_step_idem"),
        Index("ix_wf_step_retry", "status", "next_attempt_at"),
    )


S6_TABLES = ["workflow_step_executions"]
