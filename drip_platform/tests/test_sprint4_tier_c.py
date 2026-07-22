"""
AI Intelligence Layer Sprint 4 test — Tier C content agents (Email
Personalisation, Executive Briefing) writing to the existing ai_generations
table with AIP-001/002/003 discipline reused, plus the Mandrill transport
adapter's opt-in-flag safety (inert without ENABLE_MANDRILL_TRANSPORT=true).
Runs unchanged on SQLite and PostgreSQL.
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
from abm_platform.services import delivery, delivery_ext  # noqa: E402
from abm_platform.services.agents import email_personalisation_agent as epa  # noqa: E402
from abm_platform.services.agents import executive_briefing_agent as eba  # noqa: E402

_results = []


def check(name, cond):
    _results.append((name, bool(cond)))
    print(("PASS" if cond else "FAIL"), "-", name)


def run():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    orch.reset_circuit_breaker()

    org = models.Organization(canonical_name="Gulf National Bank")
    db.add(org); db.commit()
    exec_person = models.Person(full_name="Layla Hassan", current_org_id=org.id,
                                current_title="CIO", seniority_level="c_suite",
                                primary_email="layla@example.invalid")
    vp_person = models.Person(full_name="Omar Saeed", current_org_id=org.id,
                              current_title="VP Technology", seniority_level="vp",
                              primary_email="omar@example.invalid")
    db.add_all([exec_person, vp_person]); db.commit()

    rec = mi.IntelligenceRecord(org_id=org.id, kind="narrative",
                                statement="GNB is running an active core banking RFP with a new CIO in place.",
                                confidence=0.7)
    db.add(rec); db.commit()

    # ── Email Personalisation: non-c-suite contact, grounded, cites evidence ──
    def _good_email(system: str, user: str) -> str:
        payload = json.loads(user)
        check("email: intelligence_brief reached the prompt", len(payload["intelligence_brief"]) == 1)
        check("email: contact_context anonymized (no raw email)", "email" not in payload["contact_context"])
        return json.dumps({
            "subject": "A note on your core banking initiative",
            "body": "Hi {name},\n\nI noticed your institution's active core banking evaluation. "
                    "Decimal Technologies has helped similar KSA banks modernize in months, not years. "
                    "Would a short call make sense?\n\nBest,\n{sender}",
            "cited_evidence_refs": [rec.id],
        })

    llm_core.set_test_provider(_good_email)
    gen1 = epa.generate(db, person_id=vp_person.id, org_id=org.id, intelligence_record_ids=[rec.id])
    check("email: generation written", gen1 is not None)
    check("email: status qc_passed (non-c-suite, grounded, clean)", gen1.status == "qc_passed")
    check("email: cited_evidence_refs stored", gen1.input_context.get("cited_evidence_refs") == [rec.id])
    check("email: model recorded as test (not offline-template)", gen1.model == "test-model" or gen1.model == "test")

    # ── c-suite hard gate: even a QC-clean grounded email needs human approval ──
    orch.reset_circuit_breaker()
    gen2 = epa.generate(db, person_id=exec_person.id, org_id=org.id, intelligence_record_ids=[rec.id])
    check("email: c-suite generation still marked qc_passed (content itself clean)", gen2.status == "qc_passed")
    check("email: c-suite requires human approval flag present (AIP-003)",
          any("human approval" in i for i in gen2.qc.get("issues", [])))

    # ── ungrounded generation with available context -> QC failure ──
    def _ungrounded(system: str, user: str) -> str:
        return json.dumps({"subject": "hi", "body": "Just checking in — hope all is well at your bank!",
                           "cited_evidence_refs": []})

    llm_core.set_test_provider(_ungrounded)
    orch.reset_circuit_breaker()
    gen3 = epa.generate(db, person_id=vp_person.id, org_id=org.id, intelligence_record_ids=[rec.id])
    check("email: ungrounded output with available context -> qc_failed",
          gen3.status == "qc_failed" and any("ungrounded" in i for i in gen3.qc.get("issues", [])))

    # ── degraded path: no provider -> falls back to ai_gen's offline template, doesn't crash ──
    llm_core._TEST_PROVIDER = None
    for var in ("QWEN_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
        os.environ.pop(var, None)
    orch.reset_circuit_breaker()
    gen4 = epa.generate(db, person_id=vp_person.id, org_id=org.id, intelligence_record_ids=[rec.id])
    check("email: degraded path returns a generation via offline fallback, no crash", gen4 is not None)
    check("email: degraded path model is offline-template", gen4.model == "offline-template")

    # ── Executive Briefing: meeting_prep and portfolio_review share the same intelligence ──
    def _good_brief(system: str, user: str) -> str:
        return json.dumps({"subject": "Pre-call brief: Layla Hassan (GNB)",
                           "body": "Layla Hassan is CIO at GNB. Why now: active core banking RFP with new "
                                   "leadership in place. No major risk flags. Suggested opener: ask about "
                                   "RFP timeline.",
                           "cited_evidence_refs": [rec.id]})

    llm_core.set_test_provider(_good_brief)
    orch.reset_circuit_breaker()
    brief1 = eba.generate(db, role="meeting_prep", person_id=exec_person.id, org_id=org.id,
                          intelligence_record_ids=[rec.id])
    check("brief: meeting_prep generation written, kind=meeting_prep", brief1.kind == "meeting_prep")
    check("brief: cites the same intelligence_record", brief1.input_context.get("cited_evidence_refs") == [rec.id])

    orch.reset_circuit_breaker()
    brief2 = eba.generate(db, role="portfolio_review", person_id=None, org_id=org.id,
                          intelligence_record_ids=[rec.id])
    check("brief: portfolio_review generation written, kind=brief", brief2.kind == "brief")

    # only ONE ai_traces row worth of orchestrator calls per generation — no
    # double-reasoning between the two brief roles (each is its own formatting call)
    total_generations = db.query(mx.AiGeneration).count()
    check("db: 6 ai_generations rows written across the test", total_generations == 6)

    # ── Mandrill transport: inert without opt-in ──
    for var in ("ENABLE_MANDRILL_TRANSPORT", "MANDRILL_API_KEY"):
        os.environ.pop(var, None)
    ok, why = delivery_ext.try_register_mandrill()
    check("mandrill: stays inert without ENABLE_MANDRILL_TRANSPORT=true", ok is False)
    check("mandrill: reason mentions the env flag", "ENABLE_MANDRILL_TRANSPORT" in why)
    check("mandrill: transport NOT registered in delivery._TRANSPORTS", "mandrill" not in delivery._TRANSPORTS)

    os.environ["ENABLE_MANDRILL_TRANSPORT"] = "true"
    ok2, why2 = delivery_ext.try_register_mandrill()
    check("mandrill: still inert with flag but no API key", ok2 is False and "MANDRILL_API_KEY" in why2)

    os.environ["MANDRILL_API_KEY"] = "test-key-not-real"
    ok3, why3 = delivery_ext.try_register_mandrill()
    check("mandrill: registers once flag + key both present", ok3 is True)
    check("mandrill: now present in delivery._TRANSPORTS", "mandrill" in delivery._TRANSPORTS)

    os.environ.pop("ENABLE_MANDRILL_TRANSPORT", None)
    os.environ.pop("MANDRILL_API_KEY", None)

    db.close()

    failed = [n for n, ok in _results if not ok]
    print(f"\n{len(_results) - len(failed)}/{len(_results)} passed")
    if failed:
        print("FAILED:", failed)
        sys.exit(1)


if __name__ == "__main__":
    run()
