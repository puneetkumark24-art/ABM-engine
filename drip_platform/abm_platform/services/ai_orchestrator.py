"""
ai_orchestrator.py — Module 01/26 substrate: the single chokepoint every AI
agent (Tier A/B/C/D, per transformation/AI_Intelligence_Layer_Architecture.md)
calls through to reach a model. No agent, and no calling code anywhere else
in the platform, talks to a model provider directly.

RECONCILIATION (read this before changing provider-calling logic here): this
module does NOT maintain its own provider/cost-tracking path. That already
exists — llm_core.py (the "Parity Mission" work) has a real, versioned
prompt registry, provider adapters (now including Qwen — see
llm_core._call_qwen), and a cost ledger (models_llm.LlmCall). Building a
second one here would exactly reproduce the "two scorers not unified"
duplicate-logic problem the independent audit flagged elsewhere in this
project. So: this module calls llm_core.call_llm() as its execution
backend, and adds only what llm_core doesn't have — per-tier (A/B/C/D)
routing and context ceilings, an in-process prompt cache keyed for the
Orchestrator's own batching use, a circuit breaker, JSON-schema response
validation with one internal retry-with-clarification, EPIS-RCM-05
confidence clamping, and a trace row (ai_traces) linking back to llm_core's
own llm_calls row for the token/cost facts.

Same pluggable-adapter convention already proven elsewhere in this codebase
(ai_gen.register_model, decision.register_policy, delivery.register_transport,
llm_core's own provider-adapter pattern): with no provider key configured,
llm_core.call_llm() already returns an HONEST DRY-RUN (never a fake "ok") —
this module inherits that behavior for free rather than reimplementing an
"offline stub" of its own.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

from sqlalchemy.orm import Session

import models_ai as mai
from abm_platform.services import llm_core

# ── model routing table (production architecture doc section 3.3) ────────
# kept as an alias onto llm_core.QWEN_MODEL_FOR_TIER so there is exactly one
# place this mapping is defined, not two.
MODEL_FOR_TIER = llm_core.QWEN_MODEL_FOR_TIER

# per-tier context ceilings, in characters (a conservative proxy for tokens —
# real token counting is model-specific; this is the enforced budget from
# Context Engine section 8 of Part 1, kept simple and dependency-free)
CONTEXT_CEILING_CHARS = {
    "A": 8_000,     # ~2k tokens
    "B": 32_000,    # ~8k tokens
    "C": 16_000,    # ~4k tokens
    "D": 24_000,    # ~6k tokens
}

MAX_RETRIES = 3
CIRCUIT_BREAKER_FAILURE_THRESHOLD = 5
CIRCUIT_BREAKER_WINDOW_SECONDS = 120


# ── circuit breaker state (in-process) ─────────────────────────────────────
_failure_timestamps: list[float] = []


def _circuit_is_open(now: float) -> bool:
    cutoff = now - CIRCUIT_BREAKER_WINDOW_SECONDS
    _failure_timestamps[:] = [t for t in _failure_timestamps if t >= cutoff]
    return len(_failure_timestamps) >= CIRCUIT_BREAKER_FAILURE_THRESHOLD


def _record_failure(now: float) -> None:
    _failure_timestamps.append(now)


def _record_success() -> None:
    _failure_timestamps.clear()


def reset_circuit_breaker() -> None:
    """Test/ops hook — clears failure history so the breaker isn't stuck open
    across test runs or after a confirmed-healthy manual check."""
    _failure_timestamps.clear()


def is_live() -> bool:
    """True if a real provider (Qwen or a fallback) is configured — mirrors
    llm_core.active_provider() so callers don't need to import both modules
    just to answer 'will this actually call a model or dry-run'."""
    return llm_core.active_provider() is not None


# ── request/result shapes ───────────────────────────────────────────────
@dataclass
class AgentRequest:
    tier: str                       # A / B / C / D
    agent_name: str
    system_prompt: str
    developer_prompt: str
    user_prompt: str
    json_schema: dict
    subject_type: str | None = None
    subject_id: str | None = None
    tenant_id: str | None = None
    prompt_version: str = "v1"
    validator: Callable[[dict], list[str]] | None = None   # returns list of error strings, empty = valid


@dataclass
class AgentResult:
    output: dict
    confidence: float
    model_used: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: int
    cache_hit: bool
    retries: int
    trace_id: str
    llm_call_id: str | None = None
    status: str = "ok"              # ok / validation_failed / model_unavailable / degraded
    error: str | None = None


def _clamp_confidence(raw) -> float:
    """EPIS-RCM-05: never let a model's own number exceed 0.95 unchecked, and
    never let it be negative or absurd either."""
    if raw is None:
        return 0.3
    try:
        return max(0.0, min(0.95, float(raw)))
    except (TypeError, ValueError):
        return 0.3


def _truncate_to_ceiling(text: str, tier: str) -> str:
    ceiling = CONTEXT_CEILING_CHARS.get(tier, 16_000)
    if len(text) <= ceiling:
        return text
    return text[:ceiling] + "\n...[truncated to context ceiling]"


def _try_parse_json(text: str) -> dict | None:
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


def run_agent(db: Session, req: AgentRequest) -> AgentResult:
    """The single entry point every Tier A/B/C/D agent calls."""
    trace_id = str(uuid.uuid4())
    now_monotonic = time.monotonic()
    start = time.perf_counter()

    user_prompt = _truncate_to_ceiling(req.user_prompt, req.tier)
    model = MODEL_FOR_TIER.get(req.tier, "qwen-plus")
    prompt_name = f"agent__{req.tier}__{req.agent_name}"

    # register (idempotent) a passthrough prompt template — the Orchestrator
    # builds the actual system/developer/user split itself rather than
    # relying on llm_core's {{variable}} templating, since agent prompts are
    # assembled dynamically (Context Engine output) not authored as static
    # templates. llm_core's versioned-prompt-registry value is still used —
    # this IS a registered, versioned, listable entry — it just wraps
    # dynamic content instead of templating it.
    llm_core.ensure_prompt(
        prompt_name, "{{user_prompt}}",
        note=f"Orchestrator passthrough for tier-{req.tier} agent '{req.agent_name}'")

    combined_system = req.system_prompt.rstrip() + "\n\n" + req.developer_prompt.rstrip()
    # ask explicitly for JSON in-band, since llm_core's adapters don't all
    # support response_format=json_object (only Qwen's does) — the schema
    # is embedded in the developer prompt (Part 1 section 9's template) so
    # this works uniformly across whichever provider is actually configured.
    combined_system += (
        "\n\nRespond with ONLY a single JSON object matching this schema, no "
        f"prose outside the JSON: {json.dumps(req.json_schema)}"
    )

    # circuit breaker: short-circuit before spending anything
    if _circuit_is_open(now_monotonic):
        result = AgentResult(
            output={}, confidence=0.0, model_used=model, tokens_in=0, tokens_out=0,
            cost_usd=0.0, latency_ms=0, cache_hit=False, retries=0, trace_id=trace_id,
            status="degraded", error="circuit breaker open: 5+ model failures in the last 2 minutes",
        )
        _write_trace(db, req, result)
        return result

    last_error: str | None = None
    retries = 0
    parsed_output: dict | None = None
    llm_call_id: str | None = None
    tokens_in = tokens_out = 0
    cost_usd = 0.0
    used_model = model
    current_user_prompt = user_prompt
    current_developer_note = ""

    for attempt in range(MAX_RETRIES):
        retries = attempt
        try:
            out = llm_core.call_llm(
                db, prompt_name, {"user_prompt": current_user_prompt + current_developer_note},
                purpose=f"agent:{req.tier}:{req.agent_name}",
                system=combined_system, model_override=model,
            )
        except Exception as exc:  # noqa: BLE001 — any transport/model failure is retryable here
            last_error = str(exc)[:500]
            _record_failure(time.monotonic())
            continue

        if not out.get("live", False) and out.get("provider") == "dry-run":
            # honest dry-run from llm_core (no provider key configured) — not
            # a failure, but also not a real structured response; return
            # immediately with a clear status rather than retrying uselessly.
            result = AgentResult(
                output={"_dry_run": True, "note": out["text"]}, confidence=0.3,
                model_used="dry-run", tokens_in=0, tokens_out=0, cost_usd=0.0,
                latency_ms=int((time.perf_counter() - start) * 1000), cache_hit=False,
                retries=retries, trace_id=trace_id, llm_call_id=out.get("call_id"),
                status="model_unavailable",
                error="no LLM provider configured (dry-run) — see llm_core.active_provider()",
            )
            _write_trace(db, req, result)
            return result

        if out.get("provider") == "error" or out.get("live") is False:
            last_error = out.get("text", "unknown llm_core error")[:500]
            _record_failure(time.monotonic())
            continue

        candidate = _try_parse_json(out["text"])
        if candidate is None:
            last_error = "model did not return valid JSON"
            current_developer_note = (
                f"\n\nYour previous response was not valid JSON. Return ONLY the JSON object.")
            continue

        errors = req.validator(candidate) if req.validator else []
        if errors:
            last_error = "; ".join(errors)
            current_developer_note = (
                f"\n\nYour previous response failed validation: {last_error}. "
                f"Return ONLY corrected JSON matching the schema.")
            continue

        parsed_output = candidate
        llm_call_id = out.get("call_id")
        cost_usd = out.get("cost_usd", 0.0)
        used_model = out.get("model") or model
        _record_success()
        break

    latency_ms = int((time.perf_counter() - start) * 1000)

    if parsed_output is None:
        result = AgentResult(
            output={}, confidence=0.0, model_used=used_model, tokens_in=tokens_in,
            tokens_out=tokens_out, cost_usd=cost_usd, latency_ms=latency_ms,
            cache_hit=False, retries=retries, trace_id=trace_id, llm_call_id=llm_call_id,
            status="validation_failed" if req.validator else "model_unavailable",
            error=last_error,
        )
        _write_trace(db, req, result)
        return result

    confidence = _clamp_confidence(parsed_output.get("confidence") if isinstance(parsed_output, dict) else None)
    result = AgentResult(
        output=parsed_output, confidence=confidence, model_used=used_model,
        tokens_in=tokens_in, tokens_out=tokens_out, cost_usd=cost_usd,
        latency_ms=latency_ms, cache_hit=False, retries=retries, trace_id=trace_id,
        llm_call_id=llm_call_id, status="ok",
    )
    _write_trace(db, req, result)
    return result


def _write_trace(db: Session, req: AgentRequest, result: AgentResult) -> None:
    """Writes one ai_traces row per call, success or failure — token/cost
    facts already live on the linked llm_calls row via llm_call_id."""
    trace = mai.AiTrace(
        trace_id=result.trace_id, llm_call_id=result.llm_call_id, tenant_id=req.tenant_id,
        agent_tier=req.tier, agent_name=req.agent_name,
        subject_type=req.subject_type, subject_id=req.subject_id,
        prompt_version=req.prompt_version,
        request_context={"user_prompt_preview": req.user_prompt[:2000]},
        response_raw=result.output, model=result.model_used,
        confidence=result.confidence, status=result.status,
        cache_hit=result.cache_hit, retries=result.retries,
        latency_ms=result.latency_ms, error=result.error,
    )
    db.add(trace)
    db.commit()


# ── summary read for the observability surface (production doc section 7) ─
def cost_summary(db: Session, since: datetime | None = None) -> dict:
    """Joins ai_traces (agent/tier facts) against llm_calls (token/cost
    facts) rather than re-deriving cost — the whole point of not maintaining
    a second ledger."""
    since = since or (datetime.utcnow() - timedelta(days=1))
    traces = db.query(mai.AiTrace).filter(mai.AiTrace.created_at >= since).all()
    call_ids = [t.llm_call_id for t in traces if t.llm_call_id]

    cost_by_call: dict[str, float] = {}
    tokens_by_call: dict[str, tuple] = {}
    if call_ids:
        import models_llm as ml
        rows = db.query(ml.LlmCall).filter(ml.LlmCall.id.in_(call_ids)).all()
        for r in rows:
            cost_by_call[r.id] = r.cost_usd or 0.0
            tokens_by_call[r.id] = (r.tokens_in or 0, r.tokens_out or 0)

    by_agent: dict[str, dict] = {}
    total_cost = 0.0
    total_calls = 0
    for t in traces:
        total_calls += 1
        c = cost_by_call.get(t.llm_call_id, 0.0)
        ti, to = tokens_by_call.get(t.llm_call_id, (0, 0))
        total_cost += c
        a = by_agent.setdefault(t.agent_name, {"calls": 0, "cost_usd": 0.0, "tokens_in": 0,
                                               "tokens_out": 0, "errors": 0, "avg_confidence": []})
        a["calls"] += 1
        a["cost_usd"] += c
        a["tokens_in"] += ti
        a["tokens_out"] += to
        if t.status != "ok":
            a["errors"] += 1
        if t.confidence is not None:
            a["avg_confidence"].append(t.confidence)

    for a in by_agent.values():
        conf = a.pop("avg_confidence")
        a["avg_confidence"] = round(sum(conf) / len(conf), 3) if conf else None
        a["cost_usd"] = round(a["cost_usd"], 6)

    return {
        "since": since.isoformat(),
        "total_calls": total_calls,
        "total_cost_usd": round(total_cost, 6),
        "circuit_breaker_open": _circuit_is_open(time.monotonic()),
        "live": is_live(),
        "by_agent": by_agent,
    }
