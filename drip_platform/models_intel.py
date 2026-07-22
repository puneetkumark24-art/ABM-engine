"""
models_intel.py — Module 01/02 intelligence-layer tables (signal_cluster,
intelligence_record, hypothesis, nba_recommendation, evidence_ref), built as
the dependency Sprint 3's Bank Intelligence Agent (Tier B) needs.

These tables were specified in transformation/AI_Intelligence_Layer_Architecture.md
section 5.2/Phase 7 but did not exist anywhere in the codebase (confirmed by
grep before writing this file) — Module 01/02's own spec assumed them as
given, but per this project's KEEP·IMPROVE·EXTEND·HARDEN transformation
philosophy, nothing gets built on an assumption; the tables are created here,
additively, matching the JSON shapes already documented in the architecture
doc so the agent that consumes them isn't inventing a schema on the fly.

Design notes:
  - `signal_cluster` groups signals.Signal rows (kept as an id list rather
    than a join table for v1 — clusters are small, typically single-digit
    signal counts per the architecture doc's own edge-case note about
    signal storms being handled upstream of this layer).
  - `intelligence_record` is the durable "memory" the architecture doc
    calls for in lieu of a vector store (Phase 7: "long-term memory is the
    intelligence_record table itself, not a separate vector store for v1").
  - EPIS-RCM-05 discipline (confidence never fabricated, never 1.0, clamped
    to 0.95 max) is enforced at the point these rows are WRITTEN (in
    bank_intelligence_agent.py, via ai_orchestrator._clamp_confidence),
    not re-validated here — this module only defines storage shape.
  - Same conventions as models_ai.py/models_ext.py: String(36) UUIDs
    generated in Python, JSON columns, portable across SQLite (dev) and
    PostgreSQL (prod). ADDITIVE ONLY.
"""
from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Integer, Float, Boolean, Text, DateTime, JSON, Index, ForeignKey
)
from database import Base


def uid() -> str:
    return str(uuid.uuid4())


class SignalCluster(Base):
    """A promoted group of related signals for one account — the trigger
    event for the Bank Intelligence Agent. `signal_ids` is a JSON array of
    models.Signal.id values; kept denormalized (not a join table) because
    clusters are small and read-mostly, per the architecture doc's own
    scale assumption for this layer."""
    __tablename__ = "signal_clusters"
    id = Column(String(36), primary_key=True, default=uid)
    tenant_id = Column(String(36), nullable=True)
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    signal_ids = Column(JSON, default=list)
    cluster_theme = Column(String, nullable=True)     # short human label, e.g. "core banking RFP wave"
    status = Column(String, default="promoted")        # promoted / processed / needs_review
    promoted_at = Column(DateTime, default=datetime.utcnow)
    processed_at = Column(DateTime, nullable=True)
    __table_args__ = (Index("idx_signal_clusters_org", "org_id"),)


class IntelligenceRecord(Base):
    """One synthesized output row from the Bank Intelligence Agent —
    kind=hypothesis|narrative|risk, per section 5.2's Expected JSON shape.
    `superseded_by_id` lets an account's intelligence evolve incrementally
    (5.2: 'reasoning is incremental, not from-scratch every time') without
    ever deleting the prior record — audit trail stays intact."""
    __tablename__ = "intelligence_records"
    id = Column(String(36), primary_key=True, default=uid)
    tenant_id = Column(String(36), nullable=True)
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    signal_cluster_id = Column(String(36), ForeignKey("signal_clusters.id"), nullable=True)
    kind = Column(String, nullable=False)               # hypothesis / narrative / risk
    statement = Column(Text, nullable=False)
    confidence = Column(Float, nullable=False)           # EPIS-RCM-05 clamped at write time
    severity = Column(String, nullable=True)             # risk kind only: low/medium/high
    supporting_signal_ids = Column(JSON, default=list)
    contradicting_signal_ids = Column(JSON, default=list)
    prompt_version = Column(String, nullable=True)        # AIP-004 reproducibility
    llm_call_id = Column(String(36), nullable=True)        # links to llm_calls, not a duplicate cost row
    superseded_by_id = Column(String(36), ForeignKey("intelligence_records.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (
        Index("idx_intelrec_org", "org_id"),
        Index("idx_intelrec_cluster", "signal_cluster_id"),
    )


class Hypothesis(Base):
    """Competing explanations, kept distinct from IntelligenceRecord(kind=
    hypothesis) rows that are already-accepted narrative — per EPIS
    discipline ('competing hypotheses not one guess'), a cluster can
    produce several Hypothesis rows that get compared, not one row picked
    in advance by the agent."""
    __tablename__ = "hypotheses"
    id = Column(String(36), primary_key=True, default=uid)
    tenant_id = Column(String(36), nullable=True)
    intelligence_record_id = Column(String(36), ForeignKey("intelligence_records.id"), nullable=True)
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    statement = Column(Text, nullable=False)
    confidence = Column(Float, nullable=False)
    supporting_signal_ids = Column(JSON, default=list)
    contradicting_signal_ids = Column(JSON, default=list)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (Index("idx_hypotheses_org", "org_id"),)


class NbaRecommendation(Base):
    """Next-Best-Action candidates emitted by the Bank Intelligence Agent.
    Deliberately NOT auto-executed — a human (or, later, decision.py's
    existing policy engine) consumes these; this table is the agent's
    output surface, not an action-execution log."""
    __tablename__ = "nba_recommendations"
    id = Column(String(36), primary_key=True, default=uid)
    tenant_id = Column(String(36), nullable=True)
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    intelligence_record_id = Column(String(36), ForeignKey("intelligence_records.id"), nullable=True)
    action_code = Column(String, nullable=False)          # e.g. escalate_rfp, schedule_briefing, warm_intro
    rationale = Column(Text)
    confidence = Column(Float, nullable=False)
    expected_value_hint = Column(String, nullable=True)    # low/medium/high — qualitative, not a $ estimate
    status = Column(String, default="proposed")             # proposed / accepted / dismissed / expired
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (Index("idx_nba_org", "org_id"), Index("idx_nba_status", "status"))


class EvidenceRef(Base):
    """Links any intelligence output back to the concrete signal(s) it's
    grounded in — the mechanism that makes 'cite or omit' (COP-003)
    enforceable for both the Bank Intelligence Agent and, downstream, the
    Copilot (Sprint 5) when it quotes an intelligence_record."""
    __tablename__ = "evidence_refs"
    id = Column(String(36), primary_key=True, default=uid)
    tenant_id = Column(String(36), nullable=True)
    intelligence_record_id = Column(String(36), ForeignKey("intelligence_records.id"), nullable=True)
    hypothesis_id = Column(String(36), ForeignKey("hypotheses.id"), nullable=True)
    nba_recommendation_id = Column(String(36), ForeignKey("nba_recommendations.id"), nullable=True)
    signal_id = Column(String(36), ForeignKey("signals.id"), nullable=True)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (Index("idx_evidence_intelrec", "intelligence_record_id"),)
