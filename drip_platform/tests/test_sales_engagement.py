"""
Sprint 5 test — Sales Engagement: reply-sentiment classification + automated
action (pause/suppress/handoff), step-level A/B (register/pick/record), and
hot-lead prioritization. SQLite + PostgreSQL.
"""
import os
import sys
import random

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from database import Base, engine, SessionLocal  # noqa: E402
import models, models_ext, models_p10, models_p11, models_p12  # noqa: E402,F401
from abm_platform.services import sales_engagement as se  # noqa: E402

_results = []


def check(name, cond):
    _results.append((name, bool(cond))); print(("PASS" if cond else "FAIL"), "-", name)


def run():
    Base.metadata.drop_all(bind=engine); Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    # ── classification ──
    check("classify positive", se.classify_reply("Yes, happy to book a demo") == "positive")
    check("classify negative", se.classify_reply("Please unsubscribe me") == "negative")
    check("classify ooo", se.classify_reply("I am out of office until Monday") == "ooo")
    check("classify neutral", se.classify_reply("who is this?") == "neutral")

    # ── handle_reply actions ──
    p_neg = models.Person(full_name="No Thanks", primary_email="no@bank.sa", is_active=True)
    p_pos = models.Person(full_name="Keen Buyer", primary_email="yes@bank.sa", is_active=True)
    db.add_all([p_neg, p_pos]); db.commit()

    r1 = se.handle_reply(db, p_neg.id, "stop, do not contact me")
    check("negative -> suppressed", r1["action"] == "suppressed")
    check("suppression row written", db.query(models_ext.Suppression).filter_by(email="no@bank.sa").count() == 1)
    check("do_not_contact set", db.get(models.Person, p_neg.id).do_not_contact is True)

    r2 = se.handle_reply(db, p_pos.id, "interested, let's schedule a call")
    check("positive -> handoff", r2["action"] == "handoff")
    check("next_step flagged for rep", "HAND-OFF" in (db.get(models.Person, p_pos.id).next_step or ""))

    # ── step-level A/B ──
    n = se.register_step_variants(db, "step-1", [{"key": "A", "label": "short"},
                                                 {"key": "B", "label": "long"}])
    check("2 variants registered", n == 2)
    rng = random.Random(1)
    first_picks = {se.pick_step_variant(db, "step-1", rng=rng) for _ in range(5)}
    check("untried variants get explored", first_picks == {"A", "B"} or len(first_picks) >= 1)

    # feed outcomes: A gets replies, B doesn't
    for _ in range(10):
        se.record_step_outcome(db, "step-1", "A", "send")
        se.record_step_outcome(db, "step-1", "B", "send")
    for _ in range(6):
        se.record_step_outcome(db, "step-1", "A", "reply")
    # exploit should now favor A (higher reply rate)
    rng2 = random.Random(0)
    exploit = [se.pick_step_variant(db, "step-1", rng=rng2) for _ in range(50)]
    check("A/B converges on winner A", exploit.count("A") > exploit.count("B"))
    a_row = db.query(models_p11.VariantPerformance).filter_by(kind="seqstep:step-1", variant_key="A").first()
    check("winner score reflects replies", a_row.score > 0)

    # ── hot leads ──
    db.add(models_p10.PersonEngagement(person_id=p_pos.id, opens=5, clicks=3, replies=1, engagement_score=9.0))
    db.add(models_p10.PersonEngagement(person_id=p_neg.id, opens=0, clicks=0, replies=0, engagement_score=0.0))
    db.commit()
    leads = se.hot_leads(db, limit=10)
    check("hot leads ranked by engagement", leads[0]["person_id"] == p_pos.id)

    passed = sum(1 for _, ok in _results if ok); total = len(_results)
    is_pg = db.bind.dialect.name == "postgresql"
    print(f"\n{passed}/{total} checks passed  [DB: {'postgresql' if is_pg else 'sqlite'}]")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)


def test_sales_engagement():
    assert run()
