"""
models_ai.py — AI Orchestrator trace table (Transformation program, AI
Intelligence Layer Sprint 1: see
transformation/AI_Intelligence_Layer_Production_Architecture.md section 2.6).

RECONCILIATION NOTE (found while building Sprint 1, worth recording): the
codebase already has models_llm.py's `LlmCall` table + llm_core.py's
provider-adapter/prompt-registry/cost-tracking system (the "Parity Mission"
work), which does real token/cost/provider tracking today for
Anthropic/OpenAI/Gemini. Rather than building a second, competing cost
ledger — which would exactly reproduce the "two scorers not unified" duplicate-
logic problem the independent audit already flagged elsewhere in this
project — Sprint 1 EXTENDS llm_core.py with Qwen as a provider (see the
`_call_qwen` adapter added there) and keeps `llm_calls` as the ONE place
token/cost/provider facts live. This table, AiTrace, only adds the fields
llm_calls doesn't have: which agent TIER (A/B/C/D) made the call, which
subject (account/contact/opportunity) it was about, confidence (EPIS-RCM-05
clamped), retry count, cache-hit, and validation status — linked back to its
llm_calls row via `llm_call_id`, not duplicating tokens/cost/model onto a
second row.

Same conventions as models_ext.py: String(36) UUIDs generated in Python, JSON
columns, portable across SQLite (dev) and PostgreSQL (prod). ADDITIVE ONLY.
"""
from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Integer, Float, Boolean, Text, DateTime, JSON, Index
)
from database import Base


def uid() -> str:
    return str(uuid.uuid4())


class AiTrace(Base):
    """One row per Orchestrator.run_agent() call — the 'complete traceability'
    requirement from the architecture doc's objective 5. Token/cost/provider
    facts live on the linked llm_calls row (llm_call_id); this row adds what
    llm_calls doesn't track: agent tier, subject linkage, confidence,
    retries, cache-hit, and validation status."""
    __tablename__ = "ai_traces"
    id = Column(String(36), primary_key=True, default=uid)
    trace_id = Column(String(36), nullable=False, unique=True, default=uid)
    llm_call_id = Column(String(36), nullable=True)          # fk-by-convention to llm_calls.id (may be null on offline-stub runs)
    tenant_id = Column(String(36), nullable=True)          # nullable until multi-tenant RLS wired to this table
    agent_tier = Column(String, nullable=False)            # A / B / C / D
    agent_name = Column(String, nullable=False)            # e.g. "signal_classification", "bank_intelligence"
    subject_type = Column(String, nullable=True)            # account / contact / opportunity / signal / vendor
    subject_id = Column(String(36), nullable=True)

    # request/response, for reproducibility (AIP-004 pattern, applied platform-wide here)
    prompt_version = Column(String, nullable=True)
    request_context = Column(JSON, default=dict)            # the exact context block sent (post-anonymization)
    response_raw = Column(JSON, default=dict)                # the validated, schema-conformant output
    model = Column(String, nullable=False)                   # qwen-turbo / qwen-plus / qwen-max / offline-stub
    confidence = Column(Float, nullable=True)                 # EPIS-RCM-05 clamped, never >0.95

    # execution facts
    status = Column(String, default="ok")                     # ok / validation_failed / model_unavailable / degraded
    cache_hit = Column(Boolean, default=False)
    retries = Column(Integer, default=0)
    latency_ms = Column(Integer, nullable=True)
    error = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_ai_traces_agent", "agent_name", "created_at"),
        Index("idx_ai_traces_subject", "subject_type", "subject_id"),
    )
