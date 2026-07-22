"""
bank_intelligence_agent.py — Tier B agent (AI_Intelligence_Layer_Architecture.md
section 5.2): the core synthesis agent. Turns a promoted signal_cluster into
intelligence_records (hypotheses, why-now narrative, risk flags) and
nba_recommendations for an account, incorporating graph context
(graph_query.build_context_block) and the account's not-yet-superseded prior
intelligence so reasoning is incremental rather than from-scratch every run.

Unlike the Tier A agents (signal_classification, executive_movement), this
agent DOES write to the database — intelligence_record/hypothesis/
nba_recommendation/evidence_ref rows are its designed output surface (per
5.2's own table), not something a caller applies afterward. It never writes
outside those tables: no Signal mutation, no Person/Organization mutation,
no outreach/send action — those stay human- or downstream-agent-triggered.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

import models
import models_intel as mi
from abm_platform.services import ai_orchestrator as orch
from abm_platform.services import graph_query

TIER = "B"
AGENT_NAME = "bank_intelligence"
PRIOR_RECORDS_LIMIT = 8   # Phase 8 Context Engine: compact summary of prior output, not full history

SYSTEM_PROMPT = (
    "You are a B2B banking-sector intelligence analyst for Decimal Technologies, "
    "a digital-lending/core-banking platform vendor selling into Saudi banks. "
    "You follow the EPIS discipline strictly: never claim confidence of 1.0 "
    "(clamp your own estimate to at most 0.95), always ground every statement "
    "in the provided signals or graph context — never invent a fact, always "
    "produce COMPETING hypotheses when the evidence is ambiguous rather than "
    "committing to a single guess, and explicitly flag when evidence is too "
    "sparse to say anything with confidence rather than fabricating a "
    "hypothesis to fill the gap."
)

JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "hypotheses": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "statement": {"type": "string"},
                    "confidence": {"type": "number"},
                    "supporting_signal_ids": {"type": "array", "items": {"type": "string"}},
                    "contradicting_signal_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["statement", "confidence"],
            },
        },
        "narrative": {
            "type": "object",
            "properties": {"why_now": {"type": "string"}, "confidence": {"type": "number"}},
        },
        "risk_flags": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "statement": {"type": "string"}, "confidence": {"type": "number"},
                    "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                },
            },
        },
        "nba_candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "action_code": {"type": "string"}, "rationale": {"type": "string"},
                    "confidence": {"type": "number"},
                    "expected_value_hint": {"type": "string", "enum": ["low", "medium", "high"]},
                },
            },
        },
    },
    "required": ["hypotheses", "narrative"],
}


def _developer_prompt() -> str:
    return (
        "Analyze the signal cluster and account context below. Return ONLY JSON "
        f"matching: {json.dumps(JSON_SCHEMA)}. If context is sparse (new account, "
        "few signals), it is correct and expected to return low-confidence "
        "hypotheses or an empty risk_flags/nba_candidates array — do not "
        "fabricate content to fill the schema."
    )


def _validate(d: dict) -> list[str]:
    errs = []
    if not isinstance(d.get("hypotheses"), list):
        errs.append("'hypotheses' must be a list")
    if not isinstance(d.get("narrative"), dict) or not d["narrative"].get("why_now"):
        errs.append("'narrative.why_now' is required")
    return errs


def _prior_summary(db: Session, org_id: str) -> list[dict]:
    """Compact summary only — Phase 8's Context Engine rule: prior
    intelligence_records are NOT re-sent in full, just statement+confidence,
    most-recent-first, capped at PRIOR_RECORDS_LIMIT."""
    rows = (
        db.query(mi.IntelligenceRecord)
        .filter(mi.IntelligenceRecord.org_id == org_id, mi.IntelligenceRecord.superseded_by_id.is_(None))
        .order_by(mi.IntelligenceRecord.created_at.desc())
        .limit(PRIOR_RECORDS_LIMIT)
        .all()
    )
    return [{"kind": r.kind, "statement": r.statement, "confidence": r.confidence} for r in rows]


@dataclass
class BankIntelligenceResult:
    cluster_id: str
    org_id: str
    intelligence_record_ids: list[str] = field(default_factory=list)
    hypothesis_ids: list[str] = field(default_factory=list)
    nba_recommendation_ids: list[str] = field(default_factory=list)
    status: str = "ok"
    error: str | None = None


def run_for_cluster(db: Session, cluster: mi.SignalCluster) -> BankIntelligenceResult:
    """The single entry point — call once per signal_cluster.promoted event
    (5.2's cost-optimization rule: once per cluster, not per raw signal)."""
    signals = (
        db.query(models.Signal).filter(models.Signal.id.in_(cluster.signal_ids or [])).all()
    )
    graph_ctx = graph_query.build_context_block(db, cluster.org_id)
    prior = _prior_summary(db, cluster.org_id)
    account = db.query(models.AccountIntelligence).filter_by(org_id=cluster.org_id).first()

    user_prompt = json.dumps({
        "account_snapshot": {
            "tier": account.tier if account else None,
            "priority": account.priority if account else None,
            "score": account.score if account else None,
        },
        "signals": [
            {"id": s.id, "type": s.signal_type, "title": s.title, "summary": s.summary,
             "urgency": s.urgency} for s in signals
        ],
        "graph_context": graph_ctx,
        "prior_intelligence": prior,
    })

    req = orch.AgentRequest(
        tier=TIER, agent_name=AGENT_NAME,
        system_prompt=SYSTEM_PROMPT,
        developer_prompt=_developer_prompt(),
        user_prompt=user_prompt,
        json_schema=JSON_SCHEMA,
        subject_type="signal_cluster",
        subject_id=cluster.id,
        validator=_validate,
    )
    result = orch.run_agent(db, req)

    if result.status != "ok":
        cluster.status = "needs_review"   # EDGE-UNK-02 default: permanently-failing cluster flagged, not dropped
        db.add(cluster)
        db.commit()
        return BankIntelligenceResult(cluster_id=cluster.id, org_id=cluster.org_id,
                                       status=result.status, error=result.error)

    out = BankIntelligenceResult(cluster_id=cluster.id, org_id=cluster.org_id, status="ok")
    o = result.output

    for h in o.get("hypotheses", []):
        rec = mi.IntelligenceRecord(
            org_id=cluster.org_id, signal_cluster_id=cluster.id, kind="hypothesis",
            statement=h.get("statement", ""), confidence=orch._clamp_confidence(h.get("confidence")),
            supporting_signal_ids=h.get("supporting_signal_ids", []),
            contradicting_signal_ids=h.get("contradicting_signal_ids", []),
            prompt_version=req.prompt_version, llm_call_id=result.llm_call_id,
        )
        db.add(rec); db.flush()
        out.intelligence_record_ids.append(rec.id)

        hyp = mi.Hypothesis(
            intelligence_record_id=rec.id, org_id=cluster.org_id,
            statement=h.get("statement", ""), confidence=rec.confidence,
            supporting_signal_ids=h.get("supporting_signal_ids", []),
            contradicting_signal_ids=h.get("contradicting_signal_ids", []),
        )
        db.add(hyp); db.flush()
        out.hypothesis_ids.append(hyp.id)

        for sig_id in h.get("supporting_signal_ids", []):
            db.add(mi.EvidenceRef(intelligence_record_id=rec.id, hypothesis_id=hyp.id, signal_id=sig_id))

    narrative = o.get("narrative") or {}
    if narrative.get("why_now"):
        rec = mi.IntelligenceRecord(
            org_id=cluster.org_id, signal_cluster_id=cluster.id, kind="narrative",
            statement=narrative["why_now"], confidence=orch._clamp_confidence(narrative.get("confidence")),
            prompt_version=req.prompt_version, llm_call_id=result.llm_call_id,
        )
        db.add(rec); db.flush()
        out.intelligence_record_ids.append(rec.id)

    for r in o.get("risk_flags", []):
        rec = mi.IntelligenceRecord(
            org_id=cluster.org_id, signal_cluster_id=cluster.id, kind="risk",
            statement=r.get("statement", ""), confidence=orch._clamp_confidence(r.get("confidence")),
            severity=r.get("severity"), prompt_version=req.prompt_version, llm_call_id=result.llm_call_id,
        )
        db.add(rec); db.flush()
        out.intelligence_record_ids.append(rec.id)

    for nba in o.get("nba_candidates", []):
        rec_id = out.intelligence_record_ids[0] if out.intelligence_record_ids else None
        row = mi.NbaRecommendation(
            org_id=cluster.org_id, intelligence_record_id=rec_id,
            action_code=nba.get("action_code", ""), rationale=nba.get("rationale"),
            confidence=orch._clamp_confidence(nba.get("confidence")),
            expected_value_hint=nba.get("expected_value_hint"),
        )
        db.add(row); db.flush()
        out.nba_recommendation_ids.append(row.id)

    cluster.status = "processed"
    from datetime import datetime
    cluster.processed_at = datetime.utcnow()
    db.add(cluster)
    db.commit()
    return out
