"""
Sprint 3 test — marketing journey orchestration: graph validation, enrollment,
tick() advancing send/wait/branch/exit nodes, dynamic content blocks, and
multivariate weighted variant selection. SQLite + PostgreSQL.
"""
import os
import sys
import random
from datetime import datetime, timedelta

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from database import Base, engine, SessionLocal  # noqa: E402
import models, models_ext, models_p10, models_p11, models_p12, models_s3  # noqa: E402,F401
from abm_platform.services import journeys as jn  # noqa: E402

_results = []


def check(name, cond):
    _results.append((name, bool(cond))); print(("PASS" if cond else "FAIL"), "-", name)


def run():
    Base.metadata.drop_all(bind=engine); Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    # ── graph validation ──
    try:
        jn.define_journey(db, "bad", [{"id": "a", "type": "send", "next": "ghost"}])
        check("dangling next rejected", False)
    except ValueError:
        check("dangling next rejected", True)
    try:
        jn.define_journey(db, "bad2", [{"id": "a", "type": "branch"}])
        check("branch without on rejected", False)
    except ValueError:
        check("branch without on rejected", True)

    # ── a real journey: send -> wait 24h -> branch(opened) -> send/exit ──
    nodes = [
        {"id": "n1", "type": "send", "content": "welcome", "next": "n2"},
        {"id": "n2", "type": "wait", "hours": 24, "next": "n3"},
        {"id": "n3", "type": "branch", "on": "opened", "yes": "n4", "no": "n5"},
        {"id": "n4", "type": "send", "content": "thanks-for-opening", "next": "n6"},
        {"id": "n5", "type": "send", "content": "nudge", "next": "n6"},
        {"id": "n6", "type": "exit"},
    ]
    j = jn.define_journey(db, "Onboarding", nodes)
    check("journey defined", j.entry_node_id == "n1")

    e = jn.enroll(db, j.id, "person-1")
    check("enrolled at entry", e.current_node_id == "n1")

    t0 = datetime.utcnow()
    # tick 1: fires n1 (send), hits n2 (wait) -> schedules +24h
    r1 = jn.tick(db, now=t0)
    db.refresh(e)
    check("tick1 sent welcome", r1["sends"] == 1)
    check("tick1 parked at wait n3-target", e.current_node_id == "n3" and e.status == "active")
    check("tick1 scheduled +24h", e.next_action_at >= t0 + timedelta(hours=23))

    # tick before wait elapses: nothing due
    r_early = jn.tick(db, now=t0 + timedelta(hours=1))
    check("no advance before wait elapses", r_early["processed"] == 0)

    # tick after wait, person DID open -> branch yes -> n4 send -> exit
    r2 = jn.tick(db, now=t0 + timedelta(hours=25), signal=lambda en, n: True)
    db.refresh(e)
    check("tick2 branched + sent", r2["sends"] == 1)
    check("journey completed", e.status == "completed")
    actions = [h["action"] for h in e.history]
    check("history records send,wait,send,branch", actions.count("send") == 2 and "branch" in actions and "wait" in actions)

    # ── second person who does NOT open -> nudge path ──
    e2 = jn.enroll(db, j.id, "person-2", now=t0)
    jn.tick(db, now=t0)  # send + park at wait
    jn.tick(db, now=t0 + timedelta(hours=25), signal=lambda en, n: False)
    db.refresh(e2)
    branch_hist = [h for h in e2.history if h["action"] == "branch"]
    check("non-opener took 'no' branch", branch_hist and branch_hist[0]["result"] is False)
    check("non-opener completed", e2.status == "completed")

    # ── dynamic content blocks ──
    blocks = [
        {"id": "hdr", "html": "Hi"},
        {"id": "vip", "html": "VIP offer", "if": {"field": "tier", "op": "eq", "value": "gold"}},
        {"id": "ksa", "html": "KSA promo", "if": {"field": "country", "op": "in", "value": ["SA", "AE"]}},
    ]
    gold = jn.resolve_content_blocks(blocks, {"tier": "gold", "country": "SA"})
    check("dynamic content: gold+KSA sees all 3", len(gold) == 3)
    plain = jn.resolve_content_blocks(blocks, {"tier": "silver", "country": "US"})
    check("dynamic content: others see only unconditional", [b["id"] for b in plain] == ["hdr"])

    # ── multivariate (>2) weighted selection ──
    variants = [{"key": "A", "weight": 1}, {"key": "B", "weight": 1}, {"key": "C", "weight": 2}]
    rng = random.Random(42)
    counts = {"A": 0, "B": 0, "C": 0}
    for _ in range(4000):
        counts[jn.pick_variant(variants, rng=rng)] += 1
    check("multivariate supports 3 arms", all(counts[k] > 0 for k in "ABC"))
    check("multivariate respects weights (C≈2x A)", counts["C"] > counts["A"] * 1.4)

    passed = sum(1 for _, ok in _results if ok); total = len(_results)
    is_pg = db.bind.dialect.name == "postgresql"
    print(f"\n{passed}/{total} checks passed  [DB: {'postgresql' if is_pg else 'sqlite'}]")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)


def test_journeys():
    assert run()
