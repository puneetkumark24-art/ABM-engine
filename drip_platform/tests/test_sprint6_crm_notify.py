"""
AI Intelligence Layer Sprint 6 test — full end-to-end path: one real signal
-> signal_cluster -> Bank Intelligence Agent (Tier B) -> nba_recommendation
-> crm_sync.accept_recommendation() -> ActivityLog + Opportunity +
Notification, plus the Slack/email notification channel adapters' opt-in
inertness (Sprint 6's other half). Runs unchanged on SQLite and PostgreSQL.
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
from abm_platform.services.agents import bank_intelligence_agent as bia  # noqa: E402
from abm_platform.services import crm_sync, notification, notification_channels  # noqa: E402

_results = []


def check(name, cond):
    _results.append((name, bool(cond)))
    print(("PASS" if cond else "FAIL"), "-", name)


def run():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    orch.reset_circuit_breaker()

    # ── one real signal, through the full pipeline ──
    org = models.Organization(canonical_name="Gulf National Bank")
    db.add(org); db.commit()
    sig = models.Signal(org_id=org.id, signal_type="rfp", title="GNB issues core banking RFP",
                        summary="Active RFP for core banking replacement.", urgency="CRITICAL")
    db.add(sig); db.commit()

    cluster = mi.SignalCluster(org_id=org.id, signal_ids=[sig.id], cluster_theme="RFP")
    db.add(cluster); db.commit()

    def _bank_intel_provider(system: str, user: str) -> str:
        return json.dumps({
            "hypotheses": [{"statement": "Active RFP, act now.", "confidence": 0.8,
                            "supporting_signal_ids": [sig.id], "contradicting_signal_ids": []}],
            "narrative": {"why_now": "Active core banking RFP.", "confidence": 0.75},
            "risk_flags": [],
            "nba_candidates": [{"action_code": "escalate_rfp", "rationale": "Active RFP needs immediate follow-up.",
                                "confidence": 0.85, "expected_value_hint": "high"}],
        })

    llm_core.set_test_provider(_bank_intel_provider)
    bia_result = bia.run_for_cluster(db, cluster)
    check("pipeline: bank intelligence agent produced 1 NBA", len(bia_result.nba_recommendation_ids) == 1)

    nba_id = bia_result.nba_recommendation_ids[0]
    nba = db.query(mi.NbaRecommendation).filter_by(id=nba_id).first()
    check("pipeline: NBA starts as proposed", nba.status == "proposed")

    # ── human accepts the NBA -> CRM sync ──
    result = crm_sync.accept_recommendation(db, nba_id, owner="Puneet")
    check("crm_sync: accept returns status=accepted", result["status"] == "accepted")
    check("crm_sync: activity_id returned", result.get("activity_id") is not None)
    check("crm_sync: opportunity_id returned (new Opportunity created)", result.get("opportunity_id") is not None)
    check("crm_sync: notification_id returned", result.get("notification_id") is not None)

    activity = db.query(models.ActivityLog).filter_by(id=result["activity_id"]).first()
    check("db: ActivityLog written with activity_type=rfp", activity.activity_type == "rfp")
    check("db: ActivityLog linked to org", activity.org_id == org.id)
    check("db: ActivityLog next_action = escalate_rfp", activity.next_action == "escalate_rfp")

    opp = db.query(models.Opportunity).filter_by(id=result["opportunity_id"]).first()
    check("db: Opportunity created at stage Identified", opp.stage == "Identified")

    n = db.query(models.ActivityLog).count()
    check("db: exactly 1 ActivityLog row (no duplicates)", n == 1)

    nba_row = db.query(mi.NbaRecommendation).filter_by(id=nba_id).first()
    check("db: NBA flipped to accepted", nba_row.status == "accepted")

    # ── idempotency: accepting again is a no-op ──
    result2 = crm_sync.accept_recommendation(db, nba_id, owner="Puneet")
    check("crm_sync: re-accepting returns already_accepted", result2["status"] == "already_accepted")
    n2 = db.query(models.ActivityLog).count()
    check("crm_sync: idempotent — no duplicate ActivityLog on re-accept", n2 == 1)

    # ── second NBA for the SAME org reuses the existing open Opportunity ──
    cluster2 = mi.SignalCluster(org_id=org.id, signal_ids=[sig.id])
    db.add(cluster2); db.commit()

    def _second_provider(system: str, user: str) -> str:
        return json.dumps({
            "hypotheses": [], "narrative": {"why_now": "Follow-up.", "confidence": 0.5},
            "nba_candidates": [{"action_code": "schedule_briefing", "rationale": "Follow up call.",
                                "confidence": 0.6, "expected_value_hint": "medium"}],
        })

    llm_core.set_test_provider(_second_provider)
    orch.reset_circuit_breaker()
    bia_result2 = bia.run_for_cluster(db, cluster2)
    nba2_id = bia_result2.nba_recommendation_ids[0]
    result3 = crm_sync.accept_recommendation(db, nba2_id, owner="Puneet")
    check("crm_sync: second NBA reuses the SAME open Opportunity, doesn't create a 2nd",
          result3["opportunity_id"] == result["opportunity_id"])
    n_opps = db.query(models.Opportunity).filter_by(org_id=org.id).count()
    check("db: still only 1 Opportunity for this org", n_opps == 1)

    # ── dismiss path ──
    cluster3 = mi.SignalCluster(org_id=org.id, signal_ids=[sig.id])
    db.add(cluster3); db.commit()
    llm_core.set_test_provider(_second_provider)
    orch.reset_circuit_breaker()
    bia_result3 = bia.run_for_cluster(db, cluster3)
    nba3_id = bia_result3.nba_recommendation_ids[0]
    dismissed = crm_sync.dismiss_recommendation(db, nba3_id)
    check("crm_sync: dismiss works", dismissed["status"] == "dismissed")

    # ── notification channel adapters: inert without opt-in ──
    for var in ("SLACK_WEBHOOK_URL", "ENABLE_EMAIL_NOTIFICATIONS", "NOTIFY_EMAIL_TO"):
        os.environ.pop(var, None)
    ok_slack, why_slack = notification_channels.try_register_slack()
    check("slack: inert without SLACK_WEBHOOK_URL", ok_slack is False and "SLACK_WEBHOOK_URL" in why_slack)
    ok_email, why_email = notification_channels.try_register_email()
    check("email: inert without ENABLE_EMAIL_NOTIFICATIONS", ok_email is False)

    # a notification sent on the "slack" channel with no adapter registered
    # records the miss in payload rather than raising
    n_test = notification.send(db, "Puneet", "anomaly", payload={"x": 1}, channel="slack", priority="high")
    check("notification: unregistered channel doesn't raise, records _external miss",
          n_test.payload.get("_external", {}).get("delivered") is False)

    # register a fake slack adapter directly (bypassing env, to test the dispatch wiring itself)
    calls = {"n": 0}

    def _fake_slack(notif_obj):
        calls["n"] += 1
        return "slack:fake-ok"

    notification.register_channel("slack", _fake_slack)
    n_test2 = notification.send(db, "Puneet", "anomaly", payload={"x": 2}, channel="slack", priority="high")
    check("notification: registered adapter gets called", calls["n"] == 1)
    check("notification: successful external delivery recorded", n_test2.payload.get("_external", {}).get("delivered") is True)

    db.close()

    failed = [n for n, ok in _results if not ok]
    print(f"\n{len(_results) - len(failed)}/{len(_results)} passed")
    if failed:
        print("FAILED:", failed)
        sys.exit(1)


if __name__ == "__main__":
    run()
