"""
AI Intelligence Layer Sprint 3 test — graph_query.py's bounded read tools
and the Tier B Bank Intelligence Agent, wired through ai_orchestrator and
writing to the new signal_clusters/intelligence_records/hypotheses/
nba_recommendations/evidence_refs tables. Runs unchanged on SQLite and
PostgreSQL.
"""
import os
import sys
import json

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from database import Base, engine, SessionLocal  # noqa: E402
import models  # noqa: E402
import models_llm  # noqa: E402,F401
import models_ai  # noqa: E402,F401
import models_intel as mi  # noqa: E402
from abm_platform.services import llm_core  # noqa: E402
from abm_platform.services import ai_orchestrator as orch  # noqa: E402
from abm_platform.services import graph_query  # noqa: E402
from abm_platform.services.agents import bank_intelligence_agent as bia  # noqa: E402

_results = []


def check(name, cond):
    _results.append((name, bool(cond)))
    print(("PASS" if cond else "FAIL"), "-", name)


def run():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    orch.reset_circuit_breaker()

    # ── fixtures: a bank with a subsidiary, a vendor relationship, a
    # buying-committee member with a warm path ──
    bank = models.Organization(canonical_name="Gulf National Bank")
    sub = models.Organization(canonical_name="GNB Digital")
    vendor = models.Organization(canonical_name="Backbase")
    db.add_all([bank, sub, vendor]); db.commit()

    db.add(models.OrgRelationship(from_org_id=sub.id, to_org_id=bank.id, relationship_type="subsidiary_of"))
    db.add(models.OrgRelationship(from_org_id=bank.id, to_org_id=vendor.id, relationship_type="vendor_of"))
    db.add(models.VendorIntelligence(org_id=vendor.id, products=["digital banking suite"]))
    db.commit()

    cio = models.Person(full_name="Layla Hassan", current_org_id=bank.id, current_title="CIO",
                        seniority_level="c_suite")
    db.add(cio); db.commit()
    db.add(models.BuyingCommitteeMember(org_id=bank.id, person_id=cio.id, committee_role="Decision Maker",
                                        engagement="Warm"))
    db.add(models.PersonRelationship(from_name="Puneet Kumar", from_type="decimal", to_person_id=cio.id,
                                     relationship_type="knows", strength="Medium"))
    db.commit()

    account = models.AccountIntelligence(org_id=bank.id, tier="Tier 1", priority="WARM", score=62)
    db.add(account); db.commit()

    sig1 = models.Signal(org_id=bank.id, signal_type="rfp", title="GNB issues core banking RFP",
                         summary="Gulf National Bank is soliciting bids for a core banking replacement.",
                         urgency="CRITICAL")
    sig2 = models.Signal(org_id=bank.id, signal_type="leadership_change", title="GNB names new CIO",
                         summary="Layla Hassan appointed CIO.", urgency="MEDIUM")
    db.add_all([sig1, sig2]); db.commit()

    # ── graph_query direct tests ──
    committee = graph_query.get_buying_committee(db, bank.id)
    check("graph: buying committee has 1 member", committee["count"] == 1)
    check("graph: buying committee member name correct", committee["buying_committee"][0]["name"] == "Layla Hassan")

    warm = graph_query.get_warm_paths(db, bank.id)
    check("graph: warm path found (decimal contact knows CIO)", warm["count"] == 1)
    check("graph: warm path from_name correct", warm["warm_paths"][0]["from_name"] == "Puneet Kumar")

    subs = graph_query.get_subsidiary_tree(db, bank.id)
    check("graph: subsidiary tree finds GNB Digital", subs["count"] == 1
          and subs["subsidiaries"][0]["name"] == "GNB Digital")

    vendors = graph_query.get_vendor_relationships(db, bank.id)
    check("graph: vendor relationship finds Backbase", vendors["count"] == 1
          and vendors["vendor_relationships"][0]["name"] == "Backbase")

    ctx = graph_query.build_context_block(db, bank.id)
    check("graph: build_context_block bundles all four", set(ctx.keys()) == {
        "buying_committee", "warm_paths", "subsidiaries", "vendor_relationships"})

    # ── Bank Intelligence Agent ──
    cluster = mi.SignalCluster(org_id=bank.id, signal_ids=[sig1.id, sig2.id], cluster_theme="RFP + CIO change")
    db.add(cluster); db.commit()

    def _provider(system: str, user: str) -> str:
        payload = json.loads(user)
        check("agent context: graph_context reached the prompt", "graph_context" in payload)
        check("agent context: buying committee reached the prompt",
              len(payload["graph_context"]["buying_committee"]) == 1)
        return json.dumps({
            "hypotheses": [
                {"statement": "GNB is replacing its core banking vendor and the new CIO will drive the decision.",
                 "confidence": 0.72, "supporting_signal_ids": [sig1.id, sig2.id], "contradicting_signal_ids": []},
                {"statement": "Alternatively, the RFP may be a routine renewal not tied to the CIO change.",
                 "confidence": 0.3, "supporting_signal_ids": [sig1.id], "contradicting_signal_ids": []},
            ],
            "narrative": {"why_now": "New CIO arriving alongside an active core banking RFP signals a "
                                     "buying-committee reset worth engaging early.", "confidence": 0.68},
            "risk_flags": [{"statement": "Backbase already vendor-of relationship increases incumbent advantage.",
                            "confidence": 0.55, "severity": "medium"}],
            "nba_candidates": [{"action_code": "schedule_briefing", "rationale": "Engage new CIO before RFP shortlist closes.",
                                "confidence": 0.75, "expected_value_hint": "high"}],
        })

    llm_core.set_test_provider(_provider)
    result = bia.run_for_cluster(db, cluster)

    check("agent: status ok", result.status == "ok")
    check("agent: wrote 2 hypothesis intelligence_records + 1 narrative + 1 risk = 4",
          len(result.intelligence_record_ids) == 4)
    check("agent: wrote 2 Hypothesis rows", len(result.hypothesis_ids) == 2)
    check("agent: wrote 1 nba_recommendation", len(result.nba_recommendation_ids) == 1)

    recs = db.query(mi.IntelligenceRecord).filter_by(signal_cluster_id=cluster.id).all()
    check("db: 4 intelligence_records persisted", len(recs) == 4)
    kinds = sorted(r.kind for r in recs)
    check("db: kinds are hypothesis x2, narrative, risk", kinds == ["hypothesis", "hypothesis", "narrative", "risk"])

    for r in recs:
        check(f"db: {r.kind} confidence <= 0.95 (EPIS-RCM-05)", r.confidence <= 0.95)

    ev = db.query(mi.EvidenceRef).all()
    check("db: evidence_refs written for supporting signals", len(ev) >= 2)

    cluster_row = db.query(mi.SignalCluster).filter_by(id=cluster.id).first()
    check("db: cluster status advanced to processed", cluster_row.status == "processed")
    check("db: cluster processed_at stamped", cluster_row.processed_at is not None)

    # ── incremental reasoning: prior intelligence feeds the next run ──
    cluster2 = mi.SignalCluster(org_id=bank.id, signal_ids=[sig1.id], cluster_theme="RFP follow-up")
    db.add(cluster2); db.commit()

    def _provider2(system: str, user: str) -> str:
        payload = json.loads(user)
        check("agent: prior_intelligence populated on 2nd cluster for same account",
              len(payload["prior_intelligence"]) > 0)
        return json.dumps({"hypotheses": [], "narrative": {"why_now": "Follow-up, no new material change.", "confidence": 0.4}})

    llm_core.set_test_provider(_provider2)
    result2 = bia.run_for_cluster(db, cluster2)
    check("agent: 2nd run ok", result2.status == "ok")

    # ── failure path: model unavailable -> cluster flagged needs_review, not silently dropped ──
    llm_core._TEST_PROVIDER = None
    for var in ("QWEN_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
        os.environ.pop(var, None)
    orch.reset_circuit_breaker()
    cluster3 = mi.SignalCluster(org_id=bank.id, signal_ids=[sig1.id])
    db.add(cluster3); db.commit()
    result3 = bia.run_for_cluster(db, cluster3)
    check("agent: degraded run does not raise, returns status", result3.status == "model_unavailable")
    cluster3_row = db.query(mi.SignalCluster).filter_by(id=cluster3.id).first()
    check("agent: failed cluster flagged needs_review (EDGE-UNK-02), not dropped",
          cluster3_row.status == "needs_review")

    db.close()

    failed = [n for n, ok in _results if not ok]
    print(f"\n{len(_results) - len(failed)}/{len(_results)} passed")
    if failed:
        print("FAILED:", failed)
        sys.exit(1)


if __name__ == "__main__":
    run()
