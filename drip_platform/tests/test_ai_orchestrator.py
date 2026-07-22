"""
AI Intelligence Layer Sprint 1 test — ai_orchestrator.run_agent() routed
through llm_core.call_llm(), circuit breaker, retry-on-invalid-JSON,
confidence clamping (EPIS-RCM-05), and trace persistence to ai_traces
(linked to llm_calls via llm_call_id, not a duplicate cost ledger).
Runs unchanged on SQLite and PostgreSQL.
"""
import os
import sys
import json

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from database import Base, engine, SessionLocal  # noqa: E402
import models  # noqa: E402,F401
import models_llm  # noqa: E402,F401
import models_ai as mai  # noqa: E402
from abm_platform.services import llm_core  # noqa: E402
from abm_platform.services import ai_orchestrator as orch  # noqa: E402

_results = []


def check(name, cond):
    _results.append((name, bool(cond)))
    print(("PASS" if cond else "FAIL"), "-", name)


def run():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    # ── 1. no provider configured → honest dry-run, not a fake "ok" ──
    llm_core._TEST_PROVIDER = None
    for var in ("QWEN_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
        os.environ.pop(var, None)
    orch.reset_circuit_breaker()

    req = orch.AgentRequest(
        tier="A", agent_name="signal_classification",
        system_prompt="You classify banking signals.",
        developer_prompt="Return JSON only.",
        user_prompt="Bank X sponsors a football team.",
        json_schema={"type": "object", "properties": {"category": {"type": "string"}}},
        subject_type="signal", subject_id="sig-1",
    )
    result = orch.run_agent(db, req)
    check("dry-run: status=model_unavailable when no provider configured",
          result.status == "model_unavailable")
    check("dry-run: is_live() is False", orch.is_live() is False)
    trace = db.query(mai.AiTrace).filter_by(trace_id=result.trace_id).first()
    check("dry-run: trace row written", trace is not None)
    check("dry-run: trace status matches result status", trace.status == "model_unavailable")

    # ── 2. test provider registered → valid JSON first try ──
    def _good_provider(system: str, user: str) -> str:
        return json.dumps({"category": "sponsorship", "confidence": 0.87})

    llm_core.set_test_provider(_good_provider)
    orch.reset_circuit_breaker()

    result2 = orch.run_agent(db, req)
    check("valid JSON: status=ok", result2.status == "ok")
    check("valid JSON: output parsed correctly", result2.output.get("category") == "sponsorship")
    check("valid JSON: confidence clamped/preserved under 0.95", result2.confidence == 0.87)
    check("valid JSON: retries=0 on first-try success", result2.retries == 0)
    check("valid JSON: llm_call_id populated", result2.llm_call_id is not None)

    llm_call = db.query(models_llm.LlmCall).filter_by(id=result2.llm_call_id).first()
    check("llm_calls row exists for the traced call", llm_call is not None)
    check("llm_calls row has provider=test", llm_call is not None and llm_call.provider == "test")

    trace2 = db.query(mai.AiTrace).filter_by(trace_id=result2.trace_id).first()
    check("trace2: llm_call_id links to the llm_calls row", trace2.llm_call_id == result2.llm_call_id)
    check("trace2: agent_tier recorded", trace2.agent_tier == "A")
    check("trace2: agent_name recorded", trace2.agent_name == "signal_classification")

    # ── 3. confidence clamping — model claims 1.0, must clamp to 0.95 ──
    def _overconfident_provider(system: str, user: str) -> str:
        return json.dumps({"category": "sponsorship", "confidence": 1.0})

    llm_core.set_test_provider(_overconfident_provider)
    result3 = orch.run_agent(db, req)
    check("EPIS-RCM-05: confidence 1.0 clamped to 0.95", result3.confidence == 0.95)

    # ── 4. invalid JSON first, valid on retry ──
    _calls = {"n": 0}

    def _flaky_provider(system: str, user: str) -> str:
        _calls["n"] += 1
        if _calls["n"] == 1:
            return "not json at all"
        return json.dumps({"category": "sponsorship", "confidence": 0.6})

    llm_core.set_test_provider(_flaky_provider)
    result4 = orch.run_agent(db, req)
    check("retry: recovers from invalid JSON on 2nd attempt", result4.status == "ok")
    check("retry: retries counter reflects the retry", result4.retries >= 1)

    # ── 5. validator rejects output on every attempt → validation_failed ──
    def _wrong_shape_provider(system: str, user: str) -> str:
        return json.dumps({"category": 12345})

    def _validator(d: dict) -> list:
        errs = []
        if not isinstance(d.get("category"), str):
            errs.append("category must be a string")
        return errs

    llm_core.set_test_provider(_wrong_shape_provider)
    req_validated = orch.AgentRequest(
        tier="A", agent_name="signal_classification",
        system_prompt="You classify banking signals.",
        developer_prompt="Return JSON only.",
        user_prompt="Bank X sponsors a football team.",
        json_schema={"type": "object"},
        validator=_validator,
    )
    result5 = orch.run_agent(db, req_validated)
    check("validator: exhausts retries → validation_failed", result5.status == "validation_failed")
    check("validator: retries hit MAX_RETRIES-1", result5.retries == orch.MAX_RETRIES - 1)

    # ── 6. circuit breaker trips after threshold consecutive failures ──
    def _erroring_provider(system: str, user: str) -> str:
        raise RuntimeError("simulated transport failure")

    llm_core.set_test_provider(_erroring_provider)
    orch.reset_circuit_breaker()
    for _ in range(orch.CIRCUIT_BREAKER_FAILURE_THRESHOLD):
        orch.run_agent(db, req)
    check("circuit breaker: opens after threshold failures", orch._circuit_is_open(__import__("time").monotonic()))

    llm_core.set_test_provider(_good_provider)  # even a healthy provider should be short-circuited now
    result6 = orch.run_agent(db, req)
    check("circuit breaker: short-circuits subsequent calls while open", result6.status == "degraded")
    check("circuit breaker: no llm_calls row written while open", result6.llm_call_id is None)

    orch.reset_circuit_breaker()
    llm_core.set_test_provider(_good_provider)
    result7 = orch.run_agent(db, req)
    check("circuit breaker: recovers after reset", result7.status == "ok")

    # ── 7. context ceiling truncation (Tier A ~8k chars) ──
    long_req = orch.AgentRequest(
        tier="A", agent_name="signal_classification",
        system_prompt="sys", developer_prompt="dev",
        user_prompt="x" * 50_000,
        json_schema={"type": "object"},
    )
    truncated = orch._truncate_to_ceiling(long_req.user_prompt, "A")
    check("context ceiling: Tier A truncates to configured ceiling",
          len(truncated) <= orch.CONTEXT_CEILING_CHARS["A"] + len("\n...[truncated to context ceiling]"))

    # ── 8. cost_summary reads llm_calls via ai_traces, not a duplicate ledger ──
    summary = orch.cost_summary(db)
    check("cost_summary: total_calls counts traces in window", summary["total_calls"] > 0)
    check("cost_summary: by_agent breakdown present", "signal_classification" in summary["by_agent"])
    check("cost_summary: no AiCostLedger attribute exists (reconciled design)",
          not hasattr(mai, "AiCostLedger"))

    llm_core._TEST_PROVIDER = None
    db.close()

    failed = [n for n, ok in _results if not ok]
    print(f"\n{len(_results) - len(failed)}/{len(_results)} passed")
    if failed:
        print("FAILED:", failed)
        sys.exit(1)


if __name__ == "__main__":
    run()
