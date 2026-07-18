"""
models_llm.py — Parity Mission: LLM call ledger (cost/token/latency tracking).

Every model call — live or dry-run — is logged here with its prompt name and
version, so prompt analytics, cost tracking, and rollback decisions are queries,
not guesswork. Additive table; tenant-scoped like every business table.
"""
from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Integer, Float, Text, Index
from database import Base


def _id() -> str:
    return str(uuid.uuid4())


class LlmCall(Base):
    __tablename__ = "llm_calls"
    id = Column(String(36), primary_key=True, default=_id)
    tenant_id = Column(String(36), index=True)
    provider = Column(String(30))            # openai | anthropic | gemini | dry-run
    model = Column(String(60))
    prompt_name = Column(String(80), index=True)
    prompt_version = Column(Integer)
    purpose = Column(String(60))             # personalization | decision | copilot | eval
    tokens_in = Column(Integer, default=0)
    tokens_out = Column(Integer, default=0)
    cost_usd = Column(Float, default=0.0)
    latency_ms = Column(Integer)
    status = Column(String(20))              # ok | error | dry-run
    error = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index("ix_llm_calls_prompt_time", "prompt_name", "created_at"),)


LLM_TABLES = ["llm_calls"]
