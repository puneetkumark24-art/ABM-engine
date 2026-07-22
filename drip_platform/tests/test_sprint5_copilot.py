"""
AI Intelligence Layer Sprint 5 test — Copilot's Tier D plan-then-synthesize
path, RBAC-filtered tool catalog + execution-time permission enforcement
(COP-001), grounded citations (COP-003), clean fallback to the original
rule-based router when no LLM is configured or the LLM path fails, and the
grounding-rate eval harness. Runs unchanged on SQLite and PostgreSQL.
"""
import os
import sys
import json

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from database import Base, engine, SessionLocal  # noqa: E402
import models  # noqa: E402
import models_ext as mx  # noqa: E402
import models_llm  # noqa: E402,F401
import models_ai  # noqa: E402,F401
import models_intel as mi  # noqa: E402
from abm_platform.services import llm_core  # noqa: E402
from abm_platform.services import ai_orchestrator as orch  # noqa: E402
from abm_platform.services import admin, copilot  # noqa: E402

_results = []


def check(name, cond):
    _results.append((name, bool(cond)))
    print(("PASS" if cond else "FAIL"), "-", name)


def run():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    orch.reset_circuit_breaker()

    org = models.Organization(canonical_name="Gulf National Bank", short_name="GNB")
    db.add(org); db.commit()
    rec = mi.IntelligenceRecord(org_id=org.id, kind="narrative",
                                statement="Active core banking RFP.", confidence=0.7)
    db.add(rec); db.commit()

    # ── no provider configured: LLM path returns None, falls back cleanly ──
    llm_core._TEST_PROVIDER = None
    for var in ("QWEN_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
        os.environ.pop(var, None)
    orch.reset_circuit_breaker()

    turn = copilot.ask(db, "status")
    check("no-LLM fallback: rule-based status answer still works", turn.intent == "status")
    turn2 = copilot.ask(db, "How do I approach GNB?")
    check("no-LLM fallback: rule-based approach answer still works", turn2.intent == "approach")
    turn3 = copilot.ask(db, "who should i call today")
    check("no-LLM fallback: rule-based call_list answer still works", turn3.intent == "call_list")

    # ── RBAC: role with no permissions gets an empty catalog -> immediate fallback ──
    no_access_role = admin.create_role(db, "no_access", [])
    no_access_user = admin.create_user(db, "blocked@example.invalid", "Blocked User", role_id=no_access_role.id)
    turn4 = copilot.ask(db, "status", user_id=no_access_user.id)
    check("RBAC: user with no permissions falls back to rule-based path",
          turn4.intent in ("status", "unknown", "call_list", "approach"))

    reader_role = admin.create_role(db, "reader", ["crm.read", "sequences.read"])
    reader_user = admin.create_user(db, "reader@example.invalid", "Reader User", role_id=reader_role.id)
    catalog = copilot.list_tools(db, reader_user.id)
    check("RBAC: reader catalog includes crm.read tools", "graph.buying_committee" in catalog)
    check("RBAC: reader catalog includes sequences.read tools", "accounts.call_list" in catalog)

    catalog_blocked = copilot.list_tools(db, no_access_user.id)
    check("RBAC: no-access catalog is empty", catalog_blocked == {})

    # execute_tool refuses even if called directly for an unpermitted user
    result = copilot.execute_tool(db, "graph.buying_committee", {"org_id": org.id}, no_access_user.id)
    check("RBAC: execute_tool denies unpermitted user at execution time", result.get("denied") is True)

    result_ok = copilot.execute_tool(db, "graph.buying_committee", {"org_id": org.id}, reader_user.id)
    check("RBAC: execute_tool allows permitted user", "buying_committee" in result_ok)

    # ── LLM plan-then-synthesize: happy path ──
    _call_n = {"n": 0}

    def _planner_then_synth(system: str, user: str) -> str:
        _call_n["n"] += 1
        if _call_n["n"] == 1:
            return json.dumps({"tool_calls": [{"tool": "intelligence.recent_for_org", "args": {"org_id": org.id}}]})
        payload = json.loads(user)
        check("LLM path: synthesizer receives tool_results", "tool_results" in payload)
        return json.dumps({"answer": "GNB has an active core banking RFP underway.",
                           "citations": [f"intelligence_record:{rec.id}"]})

    llm_core.set_test_provider(_planner_then_synth)
    orch.reset_circuit_breaker()
    turn5 = copilot.ask(db, "What's the latest intelligence on GNB?", user_id=reader_user.id)
    check("LLM path: intent=llm_grounded", turn5.intent == "llm_grounded")
    check("LLM path: answer populated", "RFP" in turn5.answer)
    check("LLM path: citations present (COP-003 grounded)", len(turn5.citations) > 0)

    # ── LLM plan proposes an out-of-catalog tool for a restricted user -> refused, not executed ──
    def _rogue_planner(system: str, user: str) -> str:
        if "tool_results" in user:
            return json.dumps({"answer": "I could not access that information.", "citations": []})
        return json.dumps({"tool_calls": [{"tool": "graph.buying_committee", "args": {"org_id": org.id}}]})

    llm_core.set_test_provider(_rogue_planner)
    orch.reset_circuit_breaker()
    turn6 = copilot.ask(db, "Who's on the buying committee?", user_id=no_access_user.id)
    check("LLM path: restricted user gets no tool results (empty catalog -> immediate fallback)",
          turn6.intent != "llm_grounded")

    # ── clarify path ──
    def _clarify_planner(system: str, user: str) -> str:
        return json.dumps({"clarify": "Which organization did you mean?"})

    llm_core.set_test_provider(_clarify_planner)
    orch.reset_circuit_breaker()
    turn7 = copilot.ask(db, "approach them", user_id=reader_user.id)
    check("LLM path: clarify intent when planner is unsure", turn7.intent == "clarify")
    check("LLM path: clarify has no citations", turn7.citations == [])

    # ── grounding-rate eval harness ──
    stats = copilot.evaluate_grounding(db)
    check("eval: turns_evaluated excludes unknown/clarify", stats["turns_evaluated"] >= 1)
    check("eval: grounding_rate is a float between 0 and 1", 0.0 <= stats["grounding_rate"] <= 1.0)

    llm_core._TEST_PROVIDER = None
    db.close()

    failed = [n for n, ok in _results if not ok]
    print(f"\n{len(_results) - len(failed)}/{len(_results)} passed")
    if failed:
        print("FAILED:", failed)
        sys.exit(1)


if __name__ == "__main__":
    run()
