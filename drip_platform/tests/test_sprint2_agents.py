"""
AI Intelligence Layer Sprint 2 test — Tier A Signal Classification agent
(batched) and Executive Movement agent, both routed through
ai_orchestrator.run_agent(). Verifies: batch classification returns one
result per input in order, deterministic partnership layer runs regardless
of AI outcome, executive movement extraction validates required fields and
degrades cleanly on failure. Runs unchanged on SQLite and PostgreSQL.
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
import models_ai  # noqa: E402,F401
from abm_platform.services import llm_core  # noqa: E402
from abm_platform.services import ai_orchestrator as orch  # noqa: E402
from abm_platform.services.agents import signal_classification_agent as sca  # noqa: E402
from abm_platform.services.agents import executive_movement_agent as ema  # noqa: E402

_results = []


def check(name, cond):
    _results.append((name, bool(cond)))
    print(("PASS" if cond else "FAIL"), "-", name)


def run():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    orch.reset_circuit_breaker()

    # ── Signal Classification: batch of 3, one AI call ──
    items = [
        sca.SignalInput(ref_id="s1", title="Bank X signs MOU with Backbase",
                        summary="Bank X announced a partnership with Backbase for digital banking.",
                        source="news"),
        sca.SignalInput(ref_id="s2", title="Bank Y appoints new CIO",
                        summary="Bank Y named a new Chief Information Officer effective next month.",
                        source="news"),
        sca.SignalInput(ref_id="s3", title="Bank Z issues RFP for core banking replacement",
                        summary="Bank Z is soliciting bids for a core banking platform replacement.",
                        source="manual"),
    ]

    def _batch_provider(system: str, user: str) -> str:
        return json.dumps({"results": [
            {"signal_type": "partnership", "urgency": "HIGH", "decay_category": "TACTICAL",
             "product_match": "core banking", "rationale": "competitor MOU", "confidence": 0.8},
            {"signal_type": "leadership_change", "urgency": "MEDIUM", "decay_category": "STRATEGIC",
             "product_match": "", "rationale": "new CIO", "confidence": 0.75},
            {"signal_type": "rfp", "urgency": "CRITICAL", "decay_category": "OPERATIONAL",
             "product_match": "core banking", "rationale": "active RFP", "confidence": 0.9},
        ]})

    llm_core.set_test_provider(_batch_provider)
    results = sca.classify_batch(db, items)
    check("batch: returns one result per input", len(results) == 3)
    check("batch: order preserved (s1 first)", results[0].ref_id == "s1")
    check("batch: s1 classified as partnership", results[0].signal_type == "partnership")
    check("batch: s1 deterministic partner layer ran (Backbase = competitor)",
          results[0].partner_classification == "COMPETITIVE_CLOSURE")
    check("batch: s3 urgency CRITICAL", results[2].urgency == "CRITICAL")
    check("batch: only ONE llm_calls row written for 3 signals (batched)",
          db.query(models_llm.LlmCall).count() == 1)

    # single-item convenience wrapper
    def _single_provider(system: str, user: str) -> str:
        return json.dumps({"results": [
            {"signal_type": "hiring", "urgency": "LOW", "decay_category": "OPERATIONAL",
             "product_match": "", "rationale": "hiring push", "confidence": 0.6},
        ]})

    llm_core.set_test_provider(_single_provider)
    one = sca.classify_one(db, "s4", "Bank W hires 50 engineers", "Expansion of tech team.")
    check("classify_one: works via classify_batch under the hood", one.signal_type == "hiring")

    # batch size guard
    too_many = [sca.SignalInput(ref_id=str(i), title="t", summary="s") for i in range(sca.BATCH_SIZE + 1)]
    raised = False
    try:
        sca.classify_batch(db, too_many)
    except ValueError:
        raised = True
    check("batch: raises ValueError above BATCH_SIZE (caller must chunk)", raised)

    # AI unavailable → still returns deterministic partnership read
    llm_core._TEST_PROVIDER = None
    for var in ("QWEN_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
        os.environ.pop(var, None)
    orch.reset_circuit_breaker()
    degraded = sca.classify_batch(db, [items[0]])
    check("batch degraded: status reflects model_unavailable", degraded[0].status == "model_unavailable")
    check("batch degraded: deterministic partner layer STILL ran",
          degraded[0].partner_classification == "COMPETITIVE_CLOSURE")

    # ── Executive Movement extraction ──
    def _exec_provider(system: str, user: str) -> str:
        return json.dumps({
            "person_name": "Fahad Al-Otaibi", "organization_name": "Bank Y",
            "new_title": "Chief Information Officer", "previous_title": "VP Technology",
            "previous_organization": "Bank Y", "effective_date_text": "next month",
            "is_incoming": True, "seniority_level": "c_suite",
            "commercial_implication": "New CIO from within signals continuity; may still reset vendor evaluations.",
            "confidence": 0.82,
        })

    llm_core.set_test_provider(_exec_provider)
    orch.reset_circuit_breaker()
    mv = ema.extract(db, "Bank Y appoints new CIO", "Bank Y named a new CIO effective next month.")
    check("exec movement: person_name extracted", mv.person_name == "Fahad Al-Otaibi")
    check("exec movement: confidence within EPIS-RCM-05 bound", mv.confidence <= 0.95)
    check("exec movement: matched_person_hint present for human confirmation",
          mv.matched_person_hint == {"name": "Fahad Al-Otaibi", "organization": "Bank Y"})
    check("exec movement: commercial_implication populated (Phase 6 inference)",
          bool(mv.commercial_implication))

    # required-field validator: missing person_name should fail validation and degrade
    def _bad_exec_provider(system: str, user: str) -> str:
        return json.dumps({"organization_name": "Bank Y", "confidence": 0.5})

    llm_core.set_test_provider(_bad_exec_provider)
    orch.reset_circuit_breaker()
    mv_bad = ema.extract(db, "vague headline", "no clear person named")
    check("exec movement: missing person_name -> validation_failed, not fabricated",
          mv_bad.status == "validation_failed" and mv_bad.person_name is None)

    llm_core._TEST_PROVIDER = None
    db.close()

    failed = [n for n, ok in _results if not ok]
    print(f"\n{len(_results) - len(failed)}/{len(_results)} passed")
    if failed:
        print("FAILED:", failed)
        sys.exit(1)


if __name__ == "__main__":
    run()
