"""
signal_classification_agent.py — Tier A agent (AI_Intelligence_Layer_Architecture.md
section 5.4): classifies a raw signal's type/urgency/product relevance and,
when the text describes a partnership, layers the existing deterministic
COMPETITIVE_CLOSURE/INTEGRATION_OPPORTUNITY/COMPLIANCE_ALIGNMENT/NEUTRAL
classification (etl.signal_intel.classify_partnership) with an AI-judged
confidence and rationale rather than replacing it.

Batching (Phase 4 cost-optimisation directive — "the design must minimise
API cost"): classify_batch() classifies up to BATCH_SIZE signals in a SINGLE
Qwen call by asking for a JSON array keyed by index, instead of one call per
signal. This is the single biggest lever for Tier A cost, since signal
classification is the highest-volume agent in the platform (every signal
that lands in Postgres passes through it).

This agent NEVER writes to the database itself — callers (e.g. a nightly
job or the signal ingestion route) apply its output to models.Signal
fields, the same human-in-the-loop-friendly boundary ai_gen.py already uses
for generated copy (AIP-003: c-suite-sensitive output needs a human look
before it's trusted).
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy.orm import Session

from abm_platform.services import ai_orchestrator as orch
from etl import signal_intel

TIER = "A"
AGENT_NAME = "signal_classification"
BATCH_SIZE = 20

SIGNAL_TYPES = [
    "leadership_change", "regulatory", "product_launch", "hiring", "funding",
    "partnership", "rfp", "expansion", "earnings", "other",
]
URGENCY_LEVELS = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
DECAY_CATEGORIES = ["OPERATIONAL", "TACTICAL", "STRATEGIC", "STRUCTURAL"]

SYSTEM_PROMPT = (
    "You are a B2B banking-sector signal classifier for Decimal Technologies, "
    "a digital-lending/core-banking platform vendor selling into Saudi banks. "
    "You read a short news/announcement snippet about a bank or financial "
    "institution and classify it. You NEVER invent facts not present in the "
    "text. If the text is ambiguous, say so via a lower confidence score — "
    "never fabricate certainty."
)

_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "signal_type": {"type": "string", "enum": SIGNAL_TYPES},
        "urgency": {"type": "string", "enum": URGENCY_LEVELS},
        "decay_category": {"type": "string", "enum": DECAY_CATEGORIES},
        "product_match": {"type": "string"},
        "rationale": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["signal_type", "urgency", "confidence"],
}

BATCH_JSON_SCHEMA = {
    "type": "object",
    "properties": {"results": {"type": "array", "items": _ITEM_SCHEMA}},
    "required": ["results"],
}


@dataclass
class SignalInput:
    ref_id: str            # caller's own key (e.g. Signal.id, or a temp id pre-insert)
    title: str
    summary: str
    source: str = ""


@dataclass
class SignalClassification:
    ref_id: str
    signal_type: str | None
    urgency: str | None
    decay_category: str | None
    product_match: str | None
    rationale: str | None
    confidence: float
    partner_classification: str | None = None
    partner_classification_matched_vendor: str | None = None
    status: str = "ok"


def _developer_prompt(n: int) -> str:
    return (
        f"Classify all {n} signals below. Return ONLY JSON matching the schema: "
        f"{json.dumps(BATCH_JSON_SCHEMA)}. The 'results' array MUST have exactly "
        f"{n} items, in the same order as the input signals. signal_type must be "
        f"one of {SIGNAL_TYPES}. urgency must be one of {URGENCY_LEVELS}. "
        f"decay_category must be one of {DECAY_CATEGORIES} — OPERATIONAL for "
        "signals that matter for days, TACTICAL for weeks, STRATEGIC for months, "
        "STRUCTURAL for signals that reflect a lasting institutional shift. "
        "product_match should name which Decimal product (core banking, digital "
        "lending, onboarding, payments) is most relevant, or empty string if none."
    )


def _user_prompt(items: list[SignalInput]) -> str:
    lines = []
    for i, s in enumerate(items):
        lines.append(f"[{i}] source={s.source or 'unknown'} | title={s.title} | summary={s.summary}")
    return "\n".join(lines)


def _validate_batch(d: dict, expected_n: int) -> list[str]:
    errs = []
    results = d.get("results")
    if not isinstance(results, list):
        return ["'results' must be a list"]
    if len(results) != expected_n:
        errs.append(f"expected {expected_n} results, got {len(results)}")
    for i, r in enumerate(results):
        if not isinstance(r, dict):
            errs.append(f"result[{i}] not an object")
            continue
        if r.get("signal_type") not in SIGNAL_TYPES:
            errs.append(f"result[{i}].signal_type invalid")
        if r.get("urgency") not in URGENCY_LEVELS:
            errs.append(f"result[{i}].urgency invalid")
    return errs


def classify_batch(db: Session, items: list[SignalInput]) -> list[SignalClassification]:
    """Classifies up to BATCH_SIZE signals per Qwen call. Callers with more
    than BATCH_SIZE items should chunk themselves (kept explicit rather than
    silently chunking here, so a caller doing cost accounting per invocation
    isn't surprised by multiple calls hiding inside one function call)."""
    if not items:
        return []
    if len(items) > BATCH_SIZE:
        raise ValueError(f"classify_batch: {len(items)} items exceeds BATCH_SIZE={BATCH_SIZE}; chunk first")

    req = orch.AgentRequest(
        tier=TIER, agent_name=AGENT_NAME,
        system_prompt=SYSTEM_PROMPT,
        developer_prompt=_developer_prompt(len(items)),
        user_prompt=_user_prompt(items),
        json_schema=BATCH_JSON_SCHEMA,
        subject_type="signal_batch",
        validator=lambda d: _validate_batch(d, len(items)),
    )
    result = orch.run_agent(db, req)

    out: list[SignalClassification] = []
    results = result.output.get("results", []) if result.status == "ok" else []
    for i, s in enumerate(items):
        # deterministic partnership layer runs regardless of AI call outcome —
        # it's free, offline, and per the Bible is the authoritative first pass
        partner = signal_intel.classify_partnership(s.title, s.summary)

        if result.status == "ok" and i < len(results):
            r = results[i]
            out.append(SignalClassification(
                ref_id=s.ref_id,
                signal_type=r.get("signal_type"),
                urgency=r.get("urgency"),
                decay_category=r.get("decay_category"),
                product_match=r.get("product_match") or None,
                rationale=r.get("rationale"),
                confidence=orch._clamp_confidence(r.get("confidence")),
                partner_classification=partner.get("classification"),
                partner_classification_matched_vendor=partner.get("matched_vendor"),
                status="ok",
            ))
        else:
            # AI unavailable/failed: still return the deterministic partnership
            # read so callers get SOMETHING useful, with a status flag so they
            # know not to trust signal_type/urgency as AI-derived.
            out.append(SignalClassification(
                ref_id=s.ref_id, signal_type=None, urgency=None, decay_category=None,
                product_match=None, rationale=None, confidence=0.0,
                partner_classification=partner.get("classification"),
                partner_classification_matched_vendor=partner.get("matched_vendor"),
                status=result.status,
            ))
    return out


def classify_one(db: Session, ref_id: str, title: str, summary: str, source: str = "") -> SignalClassification:
    return classify_batch(db, [SignalInput(ref_id=ref_id, title=title, summary=summary, source=source)])[0]
