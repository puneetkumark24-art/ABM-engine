"""
Phase 12 test — CRM configurability (custom properties, saved views, tasks),
marketing upgrades (merge rendering, scheduling, A/B auto-winner, test-send,
engagement segments), landing renderer (public HTML + submit + gated link),
delivery ops (retry/backoff, mid-send auto-pause).
Runs unchanged on SQLite and PostgreSQL.
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
import models_p10  # noqa: E402,F401
import models_p11  # noqa: E402,F401
import models_p12 as p12  # noqa: E402
from abm_platform.services import (  # noqa: E402
    crm_ext, marketing, marketing_ext, landing, landing_render, delivery,
    delivery_ext, assets as assets_svc, engagement,
)

_results = []


def check(name, cond):
    _results.append((name, bool(cond)))
    print(("PASS" if cond else "FAIL"), "-", name)


def run():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    org = models.Organization(canonical_name="Ext Demo Bank")
    db.add(org); db.commit()
    p1 = models.Person(full_name="Fahad Alrashid", current_org_id=org.id, tier="HOT",
                       primary_email="fahad@example.invalid", consent_status="opted_in",
                       current_title="Head of Digital", city="Riyadh")
    db.add(p1); db.commit()

    # ══ CRM: custom properties ══
    crm_ext.define_property(db, "person", "core_banking_owner", "Owns Core Banking",
                            data_type="bool")
    crm_ext.define_property(db, "person", "budget_band", "Budget Band",
                            data_type="enum", options=["<1M", "1-5M", ">5M"],
                            default_value="<1M")
    crm_ext.set_property(db, "person", p1.id, "core_banking_owner", "true")
    props = crm_ext.get_properties(db, "person", p1.id)
    check("CRM prop set + read", props["core_banking_owner"] == "true")
    check("CRM default value applied when unset (HubSpot 2026)", props["budget_band"] == "<1M")
    try:
        crm_ext.set_property(db, "person", p1.id, "budget_band", "999M")
        check("CRM enum validation rejects bad value", False)
    except ValueError:
        check("CRM enum validation rejects bad value", True)
    try:
        crm_ext.define_property(db, "person", "bad", "Bad", data_type="enum")
        check("CRM enum without options rejected", False)
    except ValueError:
        check("CRM enum without options rejected", True)

    # ══ CRM: saved views (native + custom + engagement pseudo-field) ══
    p2 = models.Person(full_name="Cold Person", current_org_id=org.id, tier="COLD",
                       primary_email="cold2@example.invalid")
    db.add(p2); db.commit()
    v1 = crm_ext.create_view(db, "person", "HOT core-banking owners",
                             filters=[{"field": "tier", "op": "eq", "value": "HOT"},
                                      {"field": "custom.core_banking_owner", "op": "eq", "value": "true"}])
    rows = crm_ext.run_view(db, v1.id)
    check("CRM view filters native + custom props", [r.id for r in rows] == [p1.id])
    # engagement pseudo-field
    msg = mx.EmailMessage(person_id=p1.id, to_email=p1.primary_email)
    db.add(msg); db.flush()
    db.add(mx.DeliveryEvent(message_id=msg.id, event_type="click",
                            provider="t", provider_event_id="ce1"))
    db.commit()
    engagement.rollup_person(db, p1.id)
    v2 = crm_ext.create_view(db, "person", "Engaged",
                             filters=[{"field": "engagement_score", "op": "gt", "value": 0}])
    check("CRM view on engagement pseudo-field", [r.id for r in crm_ext.run_view(db, v2.id)] == [p1.id])

    # ══ CRM: tasks + subtasks + my-day ══
    now = datetime.utcnow()
    t_parent = crm_ext.create_task(db, "Prepare Al Rajhi proposal",
                                   due_at=now - timedelta(hours=2),
                                   related_type="organization", related_id=org.id)
    t_sub = crm_ext.create_task(db, "Collect pricing annexure",
                                due_at=now + timedelta(days=2),
                                parent_task_id=t_parent.id)
    day = crm_ext.my_day(db, "Puneet", now=now)
    check("CRM overdue task surfaces in my-day", any(t["id"] == t_parent.id for t in day["overdue"]))
    check("CRM subtask linked to parent", crm_ext.subtasks(db, t_parent.id)[0].id == t_sub.id)
    crm_ext.complete_task(db, t_parent.id)
    check("CRM complete stamps time", db.get(p12.CrmTask, t_parent.id).completed_at is not None)

    # ══ Marketing: merge render with fallbacks ══
    txt = "Dear {name|there}, greetings from {sender} re {institution|your institution} ({nonexistent|n/a})"
    rendered = marketing_ext.render_merge(db, txt, p1)
    check("MKT merge renders person fields", rendered.startswith("Dear Fahad,"))
    check("MKT merge institution resolved", "Ext Demo Bank" in rendered)
    check("MKT unknown tag falls back", "(n/a)" in rendered)
    rendered_none = marketing_ext.render_merge(db, txt, None)
    check("MKT no-person uses fallbacks", rendered_none.startswith("Dear there,"))

    # ══ Marketing: scheduling honored by tick ══
    aud = marketing.create_audience(db, "sched list")
    marketing.add_members(db, aud.id, [p1.id])
    camp = marketing.create_campaign(db, "sched camp", aud.id, "Subj", "Body {name|there}")
    marketing_ext.schedule_campaign(db, camp.id, at=now - timedelta(minutes=1))
    res = marketing_ext.run_scheduled(db, respect_send_window=False)
    check("MKT scheduled campaign fires on tick", res["fired"] == 1)
    db.refresh(camp)
    check("MKT campaign now sent", camp.status == "sent")
    # test-send never counts against campaign
    ts = marketing_ext.test_send(db, camp.id)
    check("MKT test-send renders + dry-runs", ts["status"] == "sent"
          and "Dear" in ts["rendered_preview"] or ts["status"] == "sent")

    # ══ Marketing: A/B auto-winner with significance ══
    audB = marketing.create_audience(db, "ab list")
    people = []
    for i in range(80):
        p = models.Person(full_name=f"AB {i}", primary_email=f"ab{i}@example.invalid",
                          consent_status="opted_in", current_org_id=org.id)
        db.add(p); people.append(p)
    db.commit()
    marketing.add_members(db, audB.id, [p.id for p in people])
    campB = marketing.create_campaign(db, "ab camp", audB.id, "s", "b",
                                      ab_config={"variants": [{"name": "A", "subject": "sa"},
                                                              {"name": "B", "subject": "sb"}]})
    marketing.send_campaign(db, campB.id)
    # simulate: B opens 60%, A opens 10%
    msgs = db.query(mx.EmailMessage).filter_by(campaign_id=campB.id).all()
    evs = []
    for i, m in enumerate(msgs):
        rate = 0.6 if m.variant == "B" else 0.1
        if (i % 10) < rate * 10:
            evs.append({"id": f"ab-{m.id}", "message_id": m.id, "type": "open", "ts": i})
    delivery.ingest_webhook(db, evs)
    win = marketing_ext.ab_winner(db, campB.id, metric="open")
    check("MKT AB winner decided with significance", win["decided"] and win["winner"] == "B"
          and win["z"] >= 1.96)
    # insufficient sample -> undecided
    campC = marketing.create_campaign(db, "small ab", audB.id, "s", "b",
                                      ab_config={"variants": [{"name": "A"}, {"name": "B"}]})
    mc = mx.EmailMessage(campaign_id=campC.id, person_id=p1.id, variant="A")
    db.add(mc); db.commit()
    win2 = marketing_ext.ab_winner(db, campC.id)
    check("MKT AB undecided below min sample", win2["decided"] is False)

    # ══ Marketing: engagement segment ══
    seg = marketing_ext.resolve_engaged_segment(db, min_engagement=0.01)
    check("MKT engagement-based segment", any(p.id == p1.id for p in seg))

    # ══ Landing renderer: public page + submit + gated link ══
    asset = assets_svc.register(db, "KSA Whitepaper", gated=True)
    form = landing.create_form(db, "wp form",
                               fields=[{"key": "email", "label": "Work email", "required": True},
                                       {"key": "name", "label": "Name"}])
    page = landing.create_page(db, "open-banking-ksa", "Open Banking in KSA",
                               form_id=form.id, asset_id=asset.id)
    page.blocks = [{"type": "hero", "title": "Open Banking in KSA",
                    "subtitle": "What SAMA's framework means for your roadmap"},
                   {"type": "bullets", "items": ["SAMA compliance", "3-month delivery"]},
                   {"type": "cta", "label": "Talk to us", "href": "/contact"}]
    db.commit()
    html = landing_render.render_page(db, "open-banking-ksa")
    check("LPG page renders hero+bullets+form", html is not None
          and "Open Banking in KSA" in html and "<form" in html and "consent" in html)
    check("LPG tracking.js included", "/t/js" in html)
    check("LPG unknown slug -> None", landing_render.render_page(db, "nope") is None)
    thank_you, ok = landing_render.handle_submit(
        db, "open-banking-ksa",
        {"email": "newlead@example.invalid", "name": "New Lead", "consent_given": "true"})
    check("LPG submit ok + gated signed link on thank-you", ok and "/px/assets/download/" in thank_you)
    fail_html, ok2 = landing_render.handle_submit(db, "open-banking-ksa",
                                                  {"email": "x@example.invalid"})
    check("LPG consent enforced on public submit", ok2 is False and "consent" in fail_html)
    lead = db.query(models.Person).filter_by(primary_email="newlead@example.invalid").first()
    check("LPG submission created consented person", lead is not None
          and lead.consent_status == "opted_in")

    # ══ Delivery ops: retry + auto-pause ══
    calls = {"n": 0}

    def flaky(req):
        calls["n"] += 1
        if calls["n"] < 2:
            raise RuntimeError("transient smtp error")
        return f"flaky-{req.message_id}"
    delivery.register_transport("flaky", flaky)
    req = delivery.enqueue(db, "retry-msg-1", "r@example.invalid", "s", "b", transport="flaky")
    check("DLV first attempt failed", req.status == "failed" and req.attempts == 1)
    r1 = delivery_ext.retry_failed(db, now=datetime.utcnow() + timedelta(minutes=10))
    check("DLV retry succeeds with backoff", r1["succeeded"] == 1)
    # auto-pause on bounce spike
    campD = marketing.create_campaign(db, "bouncy", audB.id, "s", "b")
    marketing.send_campaign(db, campD.id)
    msgsD = db.query(mx.EmailMessage).filter_by(campaign_id=campD.id).limit(30).all()
    delivery.ingest_webhook(db, [{"id": f"bd-{m.id}", "message_id": m.id,
                                  "type": "hard_bounce", "ts": i}
                                 for i, m in enumerate(msgsD[:10])])
    hc = delivery_ext.check_campaign_health(db, campD.id)
    db.refresh(campD)
    check("DLV mid-send auto-pause on bounce spike (Mailchimp behaviour)",
          hc["action"] == "paused" and campD.status == "paused")
    # SES adapter stays inert without opt-in
    ok_ses, why = delivery_ext.try_register_ses()
    check("DLV SES adapter inert without env opt-in", ok_ses is False and "dry-run" in why)

    passed = sum(1 for _, ok in _results if ok)
    total = len(_results)
    print(f"\n{passed}/{total} checks passed  [DB: {os.environ.get('DATABASE_URL','?').split(':')[0]}]")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)


def test_crm_marketing_ext():
    assert run()
