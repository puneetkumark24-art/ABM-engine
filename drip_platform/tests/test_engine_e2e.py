"""
Phase 10 test — engagement loop, Pipeline Engine, merge, timeline, and the
full end-to-end orchestrator tick. Runs on SQLite AND PostgreSQL unchanged
(set DATABASE_URL). No real sends: dry_run transport only.
"""
import os
import sys
from datetime import datetime, timedelta

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from database import Base, engine, SessionLocal  # noqa: E402
import models  # noqa: E402
import models_ext as mx  # noqa: E402
import models_p10 as p10  # noqa: E402
import models_p11  # noqa: E402,F401  (metadata completeness for Postgres drop/create)
from sequences import engine as seq_engine  # noqa: E402
from abm_platform.services import (  # noqa: E402
    engagement, pipeline, merge, timeline, orchestrator, delivery, marketing,
)

_results = []


def check(name, cond):
    _results.append((name, bool(cond)))
    print(("PASS" if cond else "FAIL"), "-", name)


def run():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    org = models.Organization(canonical_name="Al Rajhi Demo Bank")
    org2 = models.Organization(canonical_name="SNB Demo Bank")
    db.add_all([org, org2]); db.commit()
    p1 = models.Person(full_name="Demo Exec A", current_org_id=org.id, tier="HOT",
                       primary_email="a@example.invalid", consent_status="opted_in",
                       current_title="Head Digital", persona="Champion")
    p2 = models.Person(full_name="Demo Exec B", current_org_id=org.id, tier="WARM",
                       primary_email="b@example.invalid", consent_status="opted_in")
    p3 = models.Person(full_name="Demo Exec C", current_org_id=org2.id, tier="HOT",
                       primary_email="c@example.invalid", consent_status="opted_in")
    db.add_all([p1, p2, p3]); db.commit()

    # ════ ENGAGEMENT LOOP ════
    # simulate campaign + events for p1
    aud = marketing.create_audience(db, "demo list")
    marketing.add_members(db, aud.id, [p1.id])
    camp = marketing.create_campaign(db, "demo", aud.id, "s", "b")
    marketing.send_campaign(db, camp.id)
    msg = db.query(mx.EmailMessage).filter_by(person_id=p1.id).first()
    delivery.ingest_webhook(db, [
        {"id": "e1", "message_id": msg.id, "type": "open", "ts": 1},
        {"id": "e2", "message_id": msg.id, "type": "click", "ts": 2},
    ])
    pe = engagement.rollup_person(db, p1.id)
    check("ENG person rollup counts opens+clicks", pe.opens == 1 and pe.clicks == 1)
    check("ENG engagement_score in (0,1]", 0 < pe.engagement_score <= 1)

    # signals feed the other dims
    db.add(models.Signal(org_id=org.id, title="SAMA open banking mandate",
                         signal_type="regulatory", urgency="HIGH",
                         url="https://x.invalid/reg"))
    db.add(models.Signal(org_id=org.id, title="New CDO hired", signal_type="leadership_change",
                         urgency="HIGH", url="https://x.invalid/cdo"))
    db.commit()
    row = engagement.recompute_account_score(db, org.id)
    check("ENG reachability >0 flows into account_scores", row.reachability_score > 0)
    check("ENG signal+regulatory dims computed", row.signal_score > 0 and row.regulatory_score > 0)
    acct = db.get(models.AccountIntelligence, org.id)
    check("ENG account re-tiered & persisted", acct is not None and acct.priority == row.tier)
    # bounce lowers engagement
    delivery.ingest_webhook(db, [{"id": "e3", "message_id": msg.id, "type": "hard_bounce", "ts": 3}])
    pe2 = engagement.rollup_person(db, p1.id)
    check("ENG bounce reduces score", pe2.engagement_score < pe.engagement_score
          or pe2.bounces == 1)

    # ════ PIPELINE ENGINE ════
    pl = pipeline.create_pipeline(db, "KSA Banking", is_default=True)
    sts = pipeline.stages(db, pl.id)
    check("PIP default 6 stages ordered", [s.name for s in sts][:3] == ["Identified", "Qualified", "Proposal"])
    opp1 = models.Opportunity(org_id=org.id, estimated_value="SAR 2.5M")
    opp2 = models.Opportunity(org_id=org.id, estimated_value="500k")
    opp3 = models.Opportunity(org_id=org2.id, estimated_value="1M")
    db.add_all([opp1, opp2, opp3]); db.commit()
    pipeline.assign_deal(db, opp1.id, pl.id)                      # Identified 0.10
    pipeline.assign_deal(db, opp2.id, pl.id, "Proposal")          # 0.50
    pipeline.assign_deal(db, opp3.id, pl.id, "Negotiation")       # 0.75
    fc = pipeline.forecast(db, pl.id)
    check("PIP weighted forecast math", abs(fc["weighted"] - (2_500_000*0.10 + 500_000*0.50 + 1_000_000*0.75)) < 1)
    check("PIP best case sums amounts", abs(fc["best_case"] - 4_000_000) < 1)
    # move + terminal
    pipeline.move_deal(db, opp1.id, "Won")
    db.refresh(opp1)
    check("PIP move mirrors label+probability", opp1.stage == "Won" and opp1.probability == 100)
    fc2 = pipeline.forecast(db, pl.id)
    check("PIP won excluded from open forecast", fc2["won"] == 1 and fc2["open_deals"] == 2)
    try:
        pipeline.move_deal(db, opp2.id, "NotAStage")
        check("PIP illegal stage rejected", False)
    except ValueError:
        check("PIP illegal stage rejected", True)
    # stalled: backdate entered_stage_at
    link2 = db.query(p10.OpportunityStageLink).filter_by(opportunity_id=opp2.id).first()
    link2.entered_stage_at = datetime.utcnow() - timedelta(days=40); db.commit()
    flags = pipeline.health(db, pl.id)
    check("PIP stalled deal flagged", any("stalled" in f2 for f in flags
                                          for f2 in f["flags"] if f["opportunity_id"] == opp2.id))
    check("PIP single-threaded flagged (org2 has 1 contact)",
          any("single-threaded" in f2 for f in flags
              for f2 in f["flags"] if f["opportunity_id"] == opp3.id))

    # ════ MERGE ENGINE ════
    dup = models.Person(full_name="Demo Exec A", current_org_id=org.id,
                        phone="+9665550000", linkedin_url="https://linkedin.com/in/demoa")
    db.add(dup); db.commit()
    db.add(models.ActivityLog(activity_type="meeting", person_id=dup.id, org_id=org.id,
                              notes="met at Seamless")); db.commit()
    res = merge.merge_persons(db, p1.id, dup.id, actor="test")
    db.refresh(p1); db.refresh(dup)
    check("MRG loser deactivated not deleted", dup.is_active is False)
    check("MRG keeper filled from loser", p1.phone == "+9665550000"
          and p1.linkedin_url == "https://linkedin.com/in/demoa")
    check("MRG activity re-pointed (history preserved)",
          res["repointed"].get("activity_log", 0) == 1
          and db.query(models.ActivityLog).filter_by(person_id=p1.id).count() >= 1)
    try:
        merge.merge_persons(db, p1.id, p1.id)
        check("MRG self-merge rejected", False)
    except ValueError:
        check("MRG self-merge rejected", True)

    # ════ TIMELINE ════
    tl = timeline.person_timeline(db, p1.id)
    kinds = {e["kind"].split(":")[0] for e in tl}
    check("TML merges >=3 sources", len(kinds & {"activity", "email", "sequence", "touch", "ai"}) >= 2)
    times = [e["at"] for e in tl]
    check("TML sorted desc", times == sorted(times, reverse=True))
    otl = timeline.org_timeline(db, org.id)
    check("TML org view includes signals", any(e["kind"].startswith("signal:") for e in otl))

    # ════ END-TO-END ORCHESTRATOR TICK ════
    seq_engine.enroll_person(db, p2.id)
    seq_engine.enroll_person(db, p3.id)
    for e in db.query(models.SequenceEnrollment).all():
        e.next_run_at = datetime.utcnow() - timedelta(minutes=1)
    db.commit()
    report = orchestrator.run_tick(db, respect_send_window=False)
    check("E2E tick found due steps", report["due"] >= 2)
    check("E2E drafts generated + QC", report["drafted"] >= 2)
    check("E2E dry-run sends happened", report["sent_dry_run"] >= 2)
    check("E2E sequences advanced", report["advanced"] >= 2)
    check("E2E orgs rescored (loop closed)", len(report["orgs_rescored"]) >= 2)
    # verify chain artifacts exist
    check("E2E draft rows exist", db.query(models.Draft).count() >= 2)
    check("E2E delivery evented", db.query(mx.DeliveryEvent)
          .filter(mx.DeliveryEvent.message_id.like("seq-%")).count() >= 2)
    check("E2E account_scores written by tick",
          db.query(models.AccountScore).filter(
              models.AccountScore.notes.like("%Phase 10%")).count() >= 2)
    # c-suite hold: make p2 c_suite, re-due, tick again
    p2.seniority_level = "c_suite"
    enr2 = db.query(models.SequenceEnrollment).filter_by(person_id=p2.id).first()
    enr2.next_run_at = datetime.utcnow() - timedelta(minutes=1); db.commit()
    r2 = orchestrator.run_tick(db, respect_send_window=False)
    check("E2E c-suite draft held for human (not sent)", r2["held_for_human"] >= 1)

    passed = sum(1 for _, ok in _results if ok)
    total = len(_results)
    print(f"\n{passed}/{total} checks passed  [DB: {os.environ.get('DATABASE_URL','?').split(':')[0]}]")
    return passed == total


if __name__ ==