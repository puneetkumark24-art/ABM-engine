"""Provider-neutral Mailchimp lifecycle acceptance test.

No network and no real delivery: it proves message preparation, canonical
events, suppression, tracking, reporting, and ABM feedback as one flow.
"""
import os
import sys
import tempfile
import base64
import hashlib
import hmac
import json
from urllib.parse import urlencode

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
DBFILE = os.path.join(tempfile.gettempdir(), "drip_mailchimp_e2e.db")
if os.path.exists(DBFILE):
    os.remove(DBFILE)
os.environ["DATABASE_URL"] = f"sqlite:///{DBFILE}"
os.environ["AUTH_ENFORCED"] = "false"
os.environ["EMAIL_TRACKING_ENABLED"] = "true"
os.environ["PUBLIC_BASE_URL"] = "https://tracking.example.invalid"
os.environ["EMAIL_WEBHOOK_SECRET"] = "local-test-webhook-secret"
os.environ["MANDRILL_WEBHOOK_KEY"] = "local-mandrill-webhook-key"
os.environ["MANDRILL_WEBHOOK_URL"] = "https://tracking.example.invalid/px/delivery/webhook/mandrill"

from database import Base, engine, SessionLocal  # noqa: E402
import models, models_ext as mx, models_p10, models_p11, models_p12  # noqa: E402,F401
import models_audit, models_crm2, models_s3, models_s6, models_s8  # noqa: E402,F401
from abm_platform.services import marketing, delivery, tracking, unified  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from main import app  # noqa: E402

Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)


def test_mailchimp_e2e():
    db = SessionLocal()
    org = models.Organization(canonical_name="Lifecycle Bank")
    db.add(org); db.commit()
    people = []
    for i in range(7):
        p = models.Person(current_org_id=org.id, full_name=f"Contact {i}",
                          primary_email=f"contact{i}@example.invalid",
                          consent_status="opted_in", is_active=True)
        db.add(p); people.append(p)
    db.commit()
    audience = marketing.create_audience(db, "Lifecycle audience")
    marketing.add_members(db, audience.id, [p.id for p in people])
    campaign = marketing.create_campaign(
        db, "Lifecycle campaign", audience.id, "Hello {name}",
        '<html><body><a href="https://example.invalid/demo">Book demo</a>'
        '<a href="https://example.invalid/preferences">Unsubscribe</a></body></html>')

    preflight = marketing.campaign_preflight(db, campaign.id)
    assert preflight["ready_for_live"] is True
    assert preflight["audience"] == {"total": 7, "sendable": 7, "blocked": 0,
                                     "blocked_reasons": {}}

    result = marketing.send_campaign(db, campaign.id)
    assert result["sent"] == 7
    messages = db.query(mx.EmailMessage).filter_by(campaign_id=campaign.id).all()
    assert len(messages) == 7
    requests = {r.message_id: r for r in db.query(mx.SendRequest).all()}
    assert all("/t/o/" in requests[m.id].body for m in messages)
    assert all("/t/c/" in requests[m.id].body for m in messages)
    tracked_before = db.query(models_p11.TrackedLink).count()
    # Preparing the same message again must reuse tokens, not create duplicate links.
    tracking.prepare_email(db, campaign.body, messages[0].id,
                           base_url="https://tracking.example.invalid")
    assert db.query(models_p11.TrackedLink).count() == tracked_before
    unknown_events = db.query(mx.DeliveryEvent).count()
    tracking.record_open(db, "not-a-real-message")
    assert db.query(mx.DeliveryEvent).count() == unknown_events

    by_person = {m.person_id: m for m in messages}
    m = [by_person[p.id] for p in people]
    delivery.ingest_webhook(db, [
        {"id": "d0", "message_id": m[0].id, "type": "delivered"},
        {"id": "d1", "message_id": m[1].id, "type": "delivery"},
        {"id": "s1", "message_id": m[2].id, "type": "deferred"},
        {"id": "s2", "message_id": m[2].id, "type": "soft-bounce"},
        {"id": "s3", "message_id": m[2].id, "type": "soft_bounce"},
        {"id": "h1", "message_id": m[3].id, "type": "hard-bounce"},
        {"id": "c1", "message_id": m[4].id, "type": "spam"},
        {"id": "u1", "message_id": m[5].id, "type": "unsub"},
        {"id": "r1", "message_id": m[6].id, "type": "rejected"},
    ])
    tracking.record_open(db, m[0].id)
    tracking.record_open(db, m[1].id)
    link = db.query(models_p11.TrackedLink).filter_by(message_id=m[0].id).first()
    assert tracking.record_click(db, link.token).startswith("https://example.invalid/demo")

    assert marketing.is_suppressed(db, people[2].primary_email)
    assert marketing.is_suppressed(db, people[3].primary_email)
    assert marketing.is_suppressed(db, people[4].primary_email)
    assert marketing.is_suppressed(db, people[5].primary_email)
    db.refresh(people[3]); db.refresh(people[4]); db.refresh(people[5])
    assert people[3].do_not_contact
    assert people[4].do_not_contact and people[4].consent_status == "denied"
    assert people[5].do_not_contact and people[5].consent_status == "denied"

    report = unified.email_analytics(db, campaign_id=campaign.id)
    t, rates = report["totals"], report["rates"]
    assert t["attempted"] == 7 and t["delivered"] == 2
    assert t["soft_bounces"] == 1 and t["hard_bounces"] == 1
    assert t["complaints"] == 1 and t["unsubscribes"] == 1
    assert t["rejected"] == 1
    assert t["unique_opens"] == 2 and t["unique_clicks"] == 1
    assert rates["delivery_rate"] == round(200 / 7, 2)
    assert rates["open_rate"] == 100.0 and rates["ctor"] == 50.0
    assert report["top_links"][0]["clicks"] == 1
    assert report["notes"]["opens_are_approximate"] is True

    # Provider callbacks cannot mutate delivery/suppression state unsigned.
    payload = json.dumps([{"id": "signed-replay", "message_id": m[0].id,
                           "type": "delivered"}]).encode()
    client = TestClient(app)
    assert client.post("/px/delivery/webhook", content=payload,
                       headers={"content-type": "application/json"}).status_code == 401
    sig = base64.b64encode(hmac.new(b"local-test-webhook-secret", payload,
                                   hashlib.sha256).digest()).decode()
    ok = client.post("/px/delivery/webhook", content=payload,
                     headers={"content-type": "application/json",
                              "X-DRIP-Signature": sig})
    assert ok.status_code == 200 and ok.json()["accepted"] == 1

    malformed = json.dumps([{"id": "bad-1", "message_id": m[0].id},
                            {"id": "bad-2", "message_id": "unknown", "type": "delivered"}]).encode()
    bad_sig = base64.b64encode(hmac.new(b"local-test-webhook-secret", malformed,
                                       hashlib.sha256).digest()).decode()
    bad = client.post("/px/delivery/webhook", content=malformed,
                      headers={"content-type": "application/json",
                               "X-DRIP-Signature": bad_sig})
    assert bad.status_code == 200 and bad.json()["rejected"] == 2

    native_events = json.dumps([
        {"event": "open", "ts": 1770000000,
         "msg": {"_id": "provider-message-1", "email": m[0].to_email,
                 "metadata": {"drip_message_id": m[0].id}}},
        {"event": "hard_bounce", "ts": 1770000001,
         "msg": {"_id": "provider-message-2", "email": m[1].to_email,
                 "metadata": {"drip_message_id": m[1].id}}},
        {"event": "open", "ts": 1770000002,
         "msg": {"_id": "missing-drip-metadata"}},
    ], separators=(",", ":"))
    requests[m[0].id].transport = "mandrill"
    requests[m[0].id].provider_message_id = "provider-message-1"
    requests[m[1].id].transport = "mandrill"
    requests[m[1].id].provider_message_id = "provider-message-2"
    delivery.bind_provider_message(db, "mandrill", "provider-message-1", m[0].id)
    delivery.bind_provider_message(db, "mandrill", "provider-message-2", m[1].id)
    db.commit()
    native_params = {"mandrill_events": native_events}
    native_body = urlencode(native_params).encode()
    signed = os.environ["MANDRILL_WEBHOOK_URL"] + "mandrill_events" + native_events
    native_sig = base64.b64encode(hmac.new(
        b"local-mandrill-webhook-key", signed.encode(), hashlib.sha1).digest()).decode()
    native = client.post("/px/delivery/webhook/mandrill", content=native_body,
                         headers={"content-type": "application/x-www-form-urlencoded",
                                  "X-Mandrill-Signature": native_sig})
    assert native.status_code == 200
    assert native.json()["provider"] == "mandrill"
    assert native.json()["accepted"] == 2 and native.json()["mapping_rejected"] == 1
    unsigned_native = client.post("/px/delivery/webhook/mandrill", content=native_body,
                                  headers={"content-type": "application/x-www-form-urlencoded"})
    assert unsigned_native.status_code == 401
    replay = client.post("/px/delivery/webhook/mandrill", content=native_body,
                         headers={"content-type": "application/x-www-form-urlencoded",
                                  "X-Mandrill-Signature": native_sig})
    assert replay.json()["duplicates"] == 2
