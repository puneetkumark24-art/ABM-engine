"""
Phase 9 test — all 16 newly-implemented platform modules.
Style: in-memory-style SQLite file DB, plain check() accumulator, standalone
`python tests/test_platform_services.py` (also pytest-discoverable).
No real sends anywhere: delivery is dry_run, LinkedIn executor is a stub.
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
import models_p10  # noqa: E402,F401  (registers Phase-10 tables so drop_all/create_all cover FKs)
import models_p11  # noqa: E402,F401  (Phase-11 tables — keep metadata complete for Postgres)
from abm_platform.services import (  # noqa: E402
    enrichment, marketing, campaign, ai_gen, delivery, linkedin, landing,
    assets, rules, workflow, analytics, reporting, notification, attribution,
    admin, copilot,
)

_results = []


def check(name, cond):
    _results.append((name, bool(cond)))
    print(("PASS" if cond else "FAIL"), "-", name)


def run():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    org = models.Organization(canonical_name="Riyad Bank")
    db.add(org); db.commit()
    p1 = models.Person(full_name="Mazen Demo", current_org_id=org.id, tier="HOT",
                       primary_email="mazen.demo@example.invalid", consent_status="opted_in",
                       current_title="CDO", persona="Decision Maker", is_decision_maker=True)
    p2 = models.Person(full_name="Sara Demo", current_org_id=org.id, tier="WARM",
                       primary_email="sara.demo@example.invalid", consent_status="opted_in")
    p3 = models.Person(full_name="Blocked Demo", current_org_id=org.id,
                       primary_email="blocked@example.invalid", do_not_contact=True)
    db.add_all([p1, p2, p3]); db.commit()

    # ── 03 enrichment ──
    enrichment.clear_providers()
    enrichment.register_provider("stub1", lambda p: {"current_title": p.current_title or "VP Digital"})
    enrichment.register_provider("stub2", lambda p: {"linkedin_url": f"https://linkedin.com/in/{p.id[:8]}"})
    p_new = models.Person(full_name="NoTitle Demo", current_org_id=org.id,
                          primary_email="notitle@example.invalid")
    db.add(p_new); db.commit()
    job = enrichment.run_waterfall(db, p_new.id, required=["primary_email", "current_title"])
    check("03 waterfall fills required + stops early", job.status == "done" and job.providers_tried == ["stub1"])
    check("03 email verify: invalid flagged", enrichment.verify_email("not-an-email") == "Invalid")
    dup = models.Person(full_name="Mazen Demo", current_org_id=org.id)
    db.add(dup); db.commit()
    cands = enrichment.detect_duplicates(db)
    check("03 duplicate detected (same name+org)", any({c.a_id, c.b_id} == {p1.id, dup.id} for c in cands))

    # ── 07 marketing (+11 delivery inside) ──
    aud = marketing.create_audience(db, "HOT KSA", kind="segment",
                                    definition=[{"field": "tier", "op": "eq", "value": "HOT"}])
    members = marketing.resolve_members(db, aud.id)
    check("07 dynamic segment resolves HOT only", [m.id for m in members] == [p1.id])
    lst = marketing.create_audience(db, "All demo", kind="list")
    marketing.add_members(db, lst.id, [p1.id, p2.id, p3.id])
    camp7 = marketing.create_campaign(db, "Test blast", lst.id, "Subject A", "Body {name}",
                                      ab_config={"variants": [{"name": "A", "subject": "SA"},
                                                              {"name": "B", "subject": "SB"}]})
    res = marketing.send_campaign(db, camp7.id)   # dry_run
    check("07 send: 2 sent, 1 blocked (do_not_contact)", res["sent"] == 2 and res["blocked"] == 1)
    check("07 AB used 2 variants", res["variants_used"] == 2)
    marketing.suppress(db, "sara.demo@example.invalid", "manual")
    check("07 suppression check", marketing.is_sendable(db, p2)[0] is False)

    # ── 11 delivery events / webhook ──
    msg = db.query(mx.EmailMessage).filter_by(person_id=p1.id).first()
    wh = delivery.ingest_webhook(db, [
        {"id": "ev1", "message_id": msg.id, "type": "open", "ts": 1},
        {"id": "ev1", "message_id": msg.id, "type": "open", "ts": 1},     # replay
        {"id": "ev2", "message_id": msg.id, "type": "hard_bounce", "ts": 2},
    ])
    check("11 webhook dedup (replay ignored)", wh["accepted"] == 2 and wh["duplicates"] == 1)
    check("11 bounce auto-suppresses", marketing.is_suppressed(db, p1.primary_email))
    check("11 send idempotent by message_id",
          delivery.enqueue(db, msg.id and "fixed-id", "x@example.invalid", "s", "b").id ==
          delivery.enqueue(db, "fixed-id", "x@example.invalid", "s", "b").id)

    # ── 10 ai generation ──
    g = ai_gen.generate(db, "email", person_id=p2.id, org_id=org.id,
                        context={"signal_title": "open banking launch", "product": "vHub"})
    check("10 offline generation passes QC", g.status == "qc_passed")
    check("10 anonymization: no real name in model context", "Sara" not in str(g.input_context))
    g2 = ai_gen.generate(db, "email", person_id=p1.id, org_id=org.id, context={})
    db.refresh(p1)
    p1.seniority_level = "c_suite"; db.commit()
    g3 = ai_gen.generate(db, "email", person_id=p1.id, org_id=org.id, context={})
    check("10 c-suite flagged for human approval",
          any("human approval" in i for i in (g3.qc or {}).get("issues", [])))
    bad = ai_gen.qc_check("Short {unknown_tag} with 10 million policyholders leak")
    check("10 QC catches placeholder + leak", not bad["passed"] and len(bad["issues"]) >= 2)

    # ── 12 linkedin ──
    seat = linkedin.create_seat(db, "Puneet", daily_limit=2)
    a1, r1 = linkedin.queue_action(db, seat.id, p1.id)
    a2, r2 = linkedin.queue_action(db, seat.id, p2.id)
    check("12 actions queue when healthy", r1 == r2 == "queued")
    ex = linkedin.execute_pending(db, seat.id)
    check("12 stub executor respects cap", ex["executed"] == 2 and ex["remaining_quota"] == 0)
    a3, r3 = linkedin.queue_action(db, seat.id, p_new.id)
    check("12 daily cap blocks", r3 == "daily_cap")
    linkedin.trip_breaker(db, "test anomaly")
    a4, r4 = linkedin.queue_action(db, seat.id, p_new.id)
    check("12 breaker blocks everything", r4 == "breaker_tripped")
    linkedin.reset_breaker(db)
    # reply -> account-centric pause
    from sequences import engine as seq_engine
    seq_engine.enroll_person(db, p_new.id)
    rep = linkedin.register_reply(db, a1.id)
    check("12 reply cascades account pause", rep["paused_person"] >= 0 and "paused_account" in rep)

    # ── 13 landing/forms ──
    form = landing.create_form(db, "Whitepaper DL",
                               fields=[{"key": "email", "required": True}, {"key": "name"}])
    sub, why = landing.submit(db, form.id, {"email": "lead@example.invalid", "name": "New Lead"},
                              consent_given=True)
    check("13 submission creates consented person", sub is not None and sub.person_id is not None)
    lead = db.get(models.Person, sub.person_id)
    check("13 consent captured with source", lead.consent_status == "opted_in"
          and (lead.consent_source or "").startswith("form:"))
    none_sub, why2 = landing.submit(db, form.id, {"email": "x@example.invalid"}, consent_given=False)
    check("13 consent required enforced", none_sub is None and why2 == "consent_required")
    landing.unsubscribe(db, "lead@example.invalid")
    db.refresh(lead)
    check("13 unsubscribe suppresses + denies", lead.do_not_contact and
          marketing.is_suppressed(db, "lead@example.invalid"))

    # ── 14 assets ──
    a_v1 = assets.register(db, "KSA Case Study", gated=True)
    a_v2 = assets.register(db, "KSA Case Study", gated=True)
    check("14 versioning increments", a_v1.version == 1 and a_v2.version == 2)
    token = assets.sign_link(a_v2.id, ttl_seconds=60)
    got, why = assets.download(db, token)
    check("14 signed link serves gated asset", got is not None and got.version == 2)
    ok, why = assets.verify_link(token + "tampered")
    check("14 tampered link rejected", ok is False)
    expired = assets.sign_link(a_v2.id, ttl_seconds=-1)
    check("14 expired link rejected", assets.verify_link(expired)[0] is False)

    # ── 15 rules ──
    rule = rules.create_rule(
        db, "Hot signal play", "signal.scored",
        conditions=[{"field": "signal_score", "op": "gt", "value": 80},
                    {"field": "cto_exists", "op": "is_true", "value": True}]
        if False else [{"field": "signal_score", "op": "gt", "value": 80},
                       {"field": "cto_exists", "op": "eq", "value": True}],
        actions=[{"action": "create_opportunity", "params": {"stage": "Identified"}},
                 {"action": "notify", "params": {"user": "Puneet", "kind": "hot_account"}},
                 {"action": "enroll_sequence", "params": {}}],
        priority=100)
    rules.activate(db, rule.id)
    sim = rules.fire(db, "signal.scored",
                     {"id": p2.id, "org_id": org.id, "person_id": p2.id,
                      "signal_score": 90, "cto_exists": True, "_type": "account"}, dry_run=True)
    check("15 simulate matches without executing", sim[0].matched and sim[0].actions_result == [])
    real = rules.fire(db, "signal.scored",
                      {"id": p2.id, "org_id": org.id, "person_id": p2.id,
                       "signal_score": 90, "cto_exists": True, "_type": "account"})
    results = real[0].actions_result
    check("15 actions executed in order", list(results[0])[0] == "create_opportunity"
          and list(results[1])[0] == "notify")
    check("15 rule cannot bypass compliance (suppressed person not enrolled)",
          results[2]["enroll_sequence"]["enrolled"] is False)
    nomatch = rules.fire(db, "signal.scored", {"id": "x", "signal_score": 10, "cto_exists": True})
    check("15 non-matching rule doesn't fire actions", nomatch[0].matched is False)

    # ── 16 workflow ──
    wf = workflow.create(db, "Demo flow",
        nodes=[{"id": "s", "type": "start"},
               {"id": "c", "type": "condition", "config": {"field": "score", "op": "gt", "value": 50}},
               {"id": "e1", "type": "email", "config": {"subject": "hi"}},
               {"id": "ap", "type": "approval"},
               {"id": "n", "type": "notify", "config": {"user": "Puneet"}},
               {"id": "end", "type": "end"}],
        edges=[{"from": "s", "to": "c"},
               {"from": "c", "to": "e1", "when": "true"},
               {"from": "c", "to": "end", "when": "false"},
               {"from": "e1", "to": "ap"},
               {"from": "ap", "to": "n"},
               {"from": "n", "to": "end"}])
    workflow.activate(db, wf.id)
    run1 = workflow.start_run(db, wf.id, ctx={"score": 90, "email": "d@example.invalid"})
    check("16 run suspends at approval (durable wait)", run1.status == "waiting" and run1.cursor == "ap")
    run1 = workflow.approve(db, run1.id, "ap")
    check("16 approval resumes to success", run1.status == "succeeded")
    run2 = workflow.start_run(db, wf.id, ctx={"score": 10})
    check("16 false branch goes straight to end", run2.status == "succeeded")
    try:
        workflow.create(db, "bad", nodes=[{"id": "x", "type": "start"}], edges=[])
        check("16 validation rejects no-end workflow", False)
    except ValueError:
        check("16 validation rejects no-end workflow", True)

    # ── 17 analytics ──
    analytics.ingest(db, "email.event.open", subject_id=p1.id)
    analytics.ingest(db, "email.event.open", subject_id=p2.id)
    analytics.ingest(db, "form.submitted", subject_id=p1.id)
    qr = analytics.query(db, group_by="event_type")
    check("17 query groups by event type", qr["groups"].get("email.event.open") == 2)
    fun = analytics.funnel(db, ["email.event.open", "form.submitted"])
    check("17 funnel computes conversion", fun[0]["count"] == 2 and fun[1]["count"] == 1
          and fun[1]["conversion_pct"] == 50.0)

    # ── 20 reporting ──
    rep = reporting.create_report(db, "Opens 30d", {"event_type": "email.event.open"})
    rendered = reporting.render(db, rep.id)
    check("20 report renders analytics", rendered["data"]["total"] == 2)
    # add a decayed + a live signal, brief must include only live
    live_sig = models.Signal(org_id=org.id, title="Open banking push", signal_type="regulatory",
                             urgency="HIGH", url="https://x.invalid/live")
    dead_sig = models.Signal(org_id=org.id, title="Old news", signal_type="hiring",
                             urgency="LOW", url="https://x.invalid/dead",
                             decay_expires_at=datetime.utcnow() - timedelta(days=1))
    db.add_all([live_sig, dead_sig]); db.commit()
    brief = reporting.generate_brief(db, org.id)
    titles = [s["title"] for s in brief.content["live_signals"]]
    check("20 brief includes live, excludes decayed", "Open banking push" in titles
          and "Old news" not in titles)
    check("20 brief maps committee", any(c["name"] == "Mazen Demo"
                                          for c in brief.content["buying_committee"]))

    # ── 21 notification ──
    notification.set_quiet_hours(db, "Puneet", 0, 23)   # quiet basically all day
    n_med = notification.send(db, "Puneet", "digest", priority="med",
                              now=datetime(2026, 7, 16, 12, 0))
    n_urg = notification.send(db, "Puneet", "reply", priority="urgent",
                              now=datetime(2026, 7, 16, 12, 0))
    check("21 quiet hours hold non-urgent", n_med.status == "pending")
    check("21 urgent bypasses quiet hours", n_urg.status == "sent")
    flushed = notification.flush_pending(db, "Puneet")
    check("21 morning flush delivers held", flushed >= 1)

    # ── 22 attribution ──
    t1 = attribution.record_touch(db, org_id=org.id, channel="email", campaign_id="campA",
                                  occurred_at=datetime.utcnow() - timedelta(days=10))
    t2 = attribution.record_touch(db, org_id=org.id, channel="linkedin", campaign_id="campB",
                                  occurred_at=datetime.utcnow() - timedelta(days=5))
    t3 = attribution.record_touch(db, org_id=org.id, channel="event", campaign_id="campA",
                                  occurred_at=datetime.utcnow() - timedelta(days=1))
    lin = attribution.compute(db, org.id, "meeting", model="linear")
    check("22 linear splits evenly & sums to 1",
          abs(sum(lin.credit.values()) - 1.0) < 1e-6 and len(lin.credit) == 3)
    w = attribution.compute(db, org.id, "meeting", model="w_shaped")
    check("22 w-shaped: 30/40/30", abs(w.credit[t1.id] - 0.3) < 1e-6
          and abs(w.credit[t2.id] - 0.4) < 1e-6 and abs(w.credit[t3.id] - 0.3) < 1e-6)
    by_camp = attribution.campaign_credit(db, w.id)
    check("22 campaign rollup", abs(by_camp["campA"] - 0.6) < 1e-6 and abs(by_camp["campB"] - 0.4) < 1e-6)

    # ── 25 admin ──
    role = admin.create_role(db, "AE", ["crm.read", "sequences.*"])
    user = admin.create_user(db, "ae@decimal.invalid", "AE One", role.id)
    check("25 RBAC grants wildcard", admin.check_permission(db, user.id, "sequences.enroll"))
    check("25 RBAC denies ungranted (deny-by-default)",
          not admin.check_permission(db, user.id, "admin.full"))
    admin.ensure_quota(db, "ai_credits", limit=2)
    ok1, _ = admin.consume_quota(db, "ai_credits")
    ok2, _ = admin.consume_quota(db, "ai_credits")
    ok3, rem = admin.consume_quota(db, "ai_credits")
    check("25 quota blocks at limit", ok1 and ok2 and not ok3 and rem == 0)

    # ── 26 copilot ──
    ans = copilot.ask(db, "status")
    check("26 status answer cites registry", "modules" in ans.answer and ans.citations)
    ans2 = copilot.ask(db, "How do I approach Riyad Bank?")
    check("26 approach names decision maker", "Mazen Demo" in ans2.answer)
    check("26 approach grounded with citations", any(c.startswith("org:") for c in ans2.citations))
    ans3 = copilot.ask(db, "who should i call today")
    check("26 call-list answers (due or HOT fallback)", ans3.intent == "call_list")

    passed = sum(1 for _, ok in _results if ok)
    total = len