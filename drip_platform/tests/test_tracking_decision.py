"""
Phase 11 test — native tracking stack, deliverability engine, AI Decision
Engine + feedback loop, and the HubSpot-style event chain end to end:
sent → pixel open → click redirect → landing visit → download → pricing view
→ engagement/score update → decision changes accordingly.
Runs unchanged on SQLite and PostgreSQL.
"""
import os
import sys
import random
from datetime import datetime, timedelta

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from database import Base, engine, SessionLocal  # noqa: E402
import models  # noqa: E402
import models_ext as mx  # noqa: E402
import models_p10  # noqa: E402,F401
import models_p11 as p11  # noqa: E402
from sequences import engine as seq_engine  # noqa: E402
from abm_platform.services import (  # noqa: E402
    tracking, deliverability, decision, engagement, marketing, delivery,
)

_results = []


def check(name, cond):
    _results.append((name, bool(cond)))
    print(("PASS" if cond else "FAIL"), "-", name)


def run():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    org = models.Organization(canonical_name="Track Demo Bank")
    db.add(org); db.commit()
    p1 = models.Person(full_name="Track Exec", current_org_id=org.id, tier="WARM",
                       primary_email="track@example.invalid", consent_status="opted_in",
                       linkedin_url="https://linkedin.com/in/trackexec")
    db.add(p1); db.commit()

    # ── TRACKING: prepare an email (rewrite links + pixel) ──
    body = ('<html><body><p>See our <a href="https://decimal.example/case-study">'
            'case study</a> and <a href="https://decimal.example/pricing?x=1">pricing</a>.'
            '</p></body></html>')
    msg = mx.EmailMessage(person_id=p1.id, to_email=p1.primary_email, variant="A")
    db.add(msg); db.flush()
    prepared = tracking.prepare_email(db, body, msg.id,
                                      utm={"utm_source": "email", "utm_campaign": "openbanking"})
    check("TRK links rewritten to /t/c/", prepared.count("/t/c/") == 2
          and "decimal.example/case-study" not in prepared.split("href")[1])
    check("TRK pixel injected before </body>", "/t/o/" + msg.id + ".gif" in prepared
          and prepared.index("/t/o/") < prepared.index("</body>"))
    links = db.query(p11.TrackedLink).filter_by(message_id=msg.id).all()
    check("TRK TrackedLink rows created", len(links) == 2)

    # ── pixel open (deduped per day) ──
    tracking.record_open(db, msg.id, meta={"ua": "test"})
    tracking.record_open(db, msg.id, meta={"ua": "test"})   # prefetch replay
    opens = db.query(mx.DeliveryEvent).filter_by(message_id=msg.id, event_type="open").count()
    check("TRK open recorded once (prefetch dedup)", opens == 1)
    db.refresh(msg)
    check("TRK message status -> opened", msg.status == "opened")

    # ── click redirect with UTM + visitor cookie ──
    pricing_link = next(l for l in links if "pricing" in l.original_url)
    url = tracking.record_click(db, pricing_link.token, visitor_id="v-cookie1")
    check("TRK click 302 target keeps orig query + UTM",
          url and "x=1" in url and "utm_campaign=openbanking" in url)
    check("TRK unknown token -> None", tracking.record_click(db, "bogus") is None)
    db.refresh(msg)
    check("TRK message status -> clicked", msg.status == "clicked")
    v = db.query(p11.WebVisitor).filter_by(visitor_id="v-cookie1").first()
    check("TRK visitor cookie linked to person via click", v is not None and v.person_id == p1.id)

    # ── tracking.js web events: landing → download → pricing_view ──
    tracking.record_web_event(db, "v-cookie1", "page_view", url="/case-study")
    tracking.record_web_event(db, "v-cookie1", "download", url="/case-study.pdf")
    tracking.record_web_event(db, "v-cookie1", "pricing_view", url="/pricing")
    webevs = db.query(p11.WebEvent).filter_by(person_id=p1.id).count()
    check("TRK web events land on the person (identified)", webevs == 3)

    # anonymous visitor identified later -> backfill
    tracking.record_web_event(db, "v-anon9", "page_view", url="/")
    n = tracking.identify_visitor(db, "v-anon9", p1.id)
    check("TRK anonymous events backfilled on identify", n == 1)

    # ── the HubSpot chain closes: engagement + score move ──
    delivery.ingest_webhook(db, [{"id": "d1", "message_id": msg.id, "type": "delivered", "ts": 1}])
    pe = engagement.rollup_person(db, p1.id)
    check("CHAIN engagement counts open+click", pe.opens >= 1 and pe.clicks >= 1)
    row = engagement.recompute_account_score(db, org.id)
    check("CHAIN account score updated from behaviour", row.reachability_score > 0)

    # ── DELIVERABILITY ──
    d = deliverability.set_auth(db, "mail.decimal.example", dkim=True, spf=True, dmarc=True)
    ok, why = deliverability.can_send(db, "mail.decimal.example", volume=10)
    check("DLV auth green + within warmup cap => can send", ok)
    deliverability.consume(db, "mail.decimal.example", 10)
    ok2, why2 = deliverability.can_send(db, "mail.decimal.example", volume=100)
    check("DLV warmup cap enforced (stage 1 = 50/day)", ok2 is False and "warmup cap" in why2)
    d2 = deliverability.ensure_domain(db, "unauth.example")
    ok3, why3 = deliverability.can_send(db, "unauth.example")
    check("DLV unauthenticated domain blocked", ok3 is False and "auth" in why3)
    rates = deliverability.rate_card(db)
    check("DLV rate card computes open/click/CTOR", rates["open_rate"] > 0
          and rates["click_rate_ctr"] > 0 and rates["ctor"] > 0)

    # ── AI DECISION ENGINE ──
    # p1 viewed pricing => evaluation stage => suggest_meeting
    dec1 = decision.decide(db, p1.id)
    check("DEC pricing view => suggest_meeting", dec1.action == "suggest_meeting")
    check("DEC reasons are explainable", any("pricing" in r for r in dec1.reasons))
    check("DEC features captured", dec1.inputs.get("buying_stage") == "evaluation")

    # cold contact with LinkedIn but zero engagement => channel switch
    p2 = models.Person(full_name="Cold Exec", current_org_id=org.id, tier="COLD",
                       primary_email="cold@example.invalid", consent_status="opted_in",
                       linkedin_url="https://linkedin.com/in/coldexec")
    db.add(p2); db.commit()
    dec2 = decision.decide(db, p2.id)
    check("DEC zero engagement => switch to LinkedIn", dec2.action == "linkedin_touch")

    # c-suite hard stop overrides policy
    p3 = models.Person(full_name="CSuite Exec", current_org_id=org.id, tier="HOT",
                       primary_email="cs@example.invalid", consent_status="opted_in",
                       seniority_level="c_suite")
    db.add(p3); db.commit()
    dec3 = decision.decide(db, p3.id)
    check("DEC c-suite => hold_human always", dec3.action == "hold_human")

    # compliance gate pre-empts policy entirely
    p4 = models.Person(full_name="DNC Exec", current_org_id=org.id,
                       primary_email="dnc@example.invalid", do_not_contact=True)
    db.add(p4); db.commit()
    dec4 = decision.decide(db, p4.id)
    check("DEC compliance gate blocks outreach decision", dec4.action == "wait"
          and any("compliance" in r for r in dec4.reasons))

    # replied => notify_sales handoff
    p1.replied = True; db.commit()
    dec5 = decision.decide(db, p1.id)
    check("DEC reply => notify_sales handoff", dec5.action == "notify_sales")
    res = decision.apply_decision(db, dec5.id)
    check("DEC apply notify_sales creates urgent notification", "notification" in res)
    p1.replied = False; db.commit()

    # apply reschedules the enrollment (dynamic timing replaces static wait)
    seq_engine.enroll_person(db, p2.id)
    dec6 = decision.decide(db, p2.id)
    res6 = decision.apply_decision(db, dec6.id)
    check("DEC apply reschedules next touch dynamically",
          "rescheduled_next_run" in res6 or "deferred_to" in res6)

    # ── FEEDBACK LOOP ──
    decision.record_outcome(db, "email", "subj:A", sends=100, opens=30, clicks=5, replies=1)
    decision.record_outcome(db, "email", "subj:B", sends=100, opens=45, clicks=15, replies=4)
    rng = random.Random(42)
    picks = [decision.choose_variant(db, "email", rng).variant_key for _ in range(30)]
    check("FBK better variant wins most picks (epsilon-greedy)",
          picks.count("subj:B") > picks.count("subj:A"))
    check("FBK but exploration still happens", "subj:A" in picks)
    # campaign learning folds real results in
    aud = marketing.create_audience(db, "fbk list")
    marketing.add_members(db, aud.id, [p2.id])
    camp = marketing.create_campaign(db, "fbk", aud.id, "s", "b",
                                     ab_config={"variants": [{"name": "A", "subject": "sa"}]})
    marketing.send_campaign(db, camp.id)
    per = decision.learn_from_campaign(db, camp.id)
    check("FBK campaign results folded into variant store", per.get("A", {}).get("sends", 0) == 1)

    passed = sum(1 for _, ok in _results if ok)
    total = len(_results)
    print(f"\n{passed}/{total} checks passed  [DB: {os.environ.get('DATABASE_URL','?').split(':')[0]}]")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)


def test_tracking_decision():
    assert run()
