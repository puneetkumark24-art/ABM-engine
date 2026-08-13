"""Mailchimp-style email lifecycle, end to end, through the real HTTP surface.

audience -> campaign -> personalization -> link/pixel instrumentation ->
enqueue -> signed provider events -> reporting -> suppression + consent ->
account engagement -> dashboard payload.

Also pins the things that would quietly ruin a real send:
  * provider acceptance is not delivery
  * a missing event type is not delivery
  * retries do not duplicate tracked links or messages
  * /t/c/<token> cannot become an open redirect
  * webhooks without a valid signature change nothing
  * live sending stays off unless every activation condition is met
"""
import base64
import hashlib
import hmac
import json
import os
from urllib.parse import quote
import sys

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("EMAIL_WEBHOOK_SECRET", "test-webhook-secret")
os.environ.setdefault("PUBLIC_BASE_URL", "https://drip.example.com")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from fastapi.testclient import TestClient  # noqa: E402

from database import Base, engine, SessionLocal  # noqa: E402
import models  # noqa: E402
import models_ext as mx  # noqa: E402
import models_p11 as p11  # noqa: E402
import models_ai, models_audit, models_collectors, models_crm2  # noqa: E402,F401
import models_final, models_intel, models_jobs, models_llm  # noqa: E402,F401
import models_p10, models_p12, models_s3, models_s6, models_s8  # noqa: E402,F401
import models_segments, models_tenant  # noqa: E402,F401
from abm_platform.services import (  # noqa: E402
    marketing, tracking, delivery, send_activation, email_events,
    mandrill_events, unified,
)

_results = []
BASE = "https://drip.example.com"


def check(name, cond, detail=""):
    _results.append((name, bool(cond)))
    print(("PASS" if cond else "FAIL"), "-", name, ("| " + str(detail)) if detail else "")


def _sign(body: bytes) -> str:
    return base64.b64encode(
        hmac.new(b"test-webhook-secret", body, hashlib.sha256).digest()).decode()


def run():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    import main
    client = TestClient(main.app)

    # ── seed ────────────────────────────────────────────────────────────
    org = models.Organization(canonical_name="Lifecycle Bank")
    db.add(org); db.commit()
    people = [
        models.Person(full_name="Aisha Manager", current_org_id=org.id,
                      primary_email="aisha@lifecycle.invalid", consent_status="opted_in",
                      seniority_level="manager", current_title="Head of Digital"),
        models.Person(full_name="Omar Director", current_org_id=org.id,
                      primary_email="omar@lifecycle.invalid", consent_status="opted_in",
                      seniority_level="director", current_title="Director Ops"),
    ]
    db.add_all(people); db.commit()
    aisha, omar = people

    # ── 1. audience + campaign + personalization ────────────────────────
    aud = marketing.create_audience(db, "Lifecycle audience")
    marketing.add_members(db, aud.id, [aisha.id, omar.id])
    camp = marketing.create_campaign(
        db, "Lifecycle campaign", aud.id, "Hello {name}",
        '<html><body>Dear {name|there} at {institution|your bank}, '
        '<a href="https://decimal.example.com/onboarding">see this</a>. '
        '<a href="javascript:alert(1)">bad</a></body></html>')
    res = marketing.send_campaign(db, camp.id)
    check("campaign sent in dry-run", res["sent"] == 2, res)

    msgs = db.query(mx.EmailMessage).filter_by(campaign_id=camp.id).all()
    check("one message per recipient", len(msgs) == 2, len(msgs))
    reqs = {r.message_id: r for r in db.query(mx.SendRequest).all()}
    body = reqs[msgs[0].id].body
    check("merge fields rendered, no literal tags",
          "{name" not in body and "Dear" in body, body[:70])

    # ── 2. instrumentation ──────────────────────────────────────────────
    check("open pixel injected with the absolute base url",
          f'{BASE}/t/o/{msgs[0].id}.gif' in body)
    check("real link rewritten to a tracked redirect", f"{BASE}/t/c/" in body)
    check("original destination no longer appears verbatim",
          "https://decimal.example.com/onboarding" not in body)
    check("javascript: link was NOT tracked and NOT rewritten",
          "javascript:alert(1)" in body and body.count(f"{BASE}/t/c/") == 1)
    links = db.query(p11.TrackedLink).filter_by(message_id=msgs[0].id).all()
    check("exactly one tracked link row", len(links) == 1, len(links))
    check("utm captured for the redirect",
          links and links[0].utm.get("utm_campaign") == camp.id, links[0].utm)

    # ── 3. re-render / retry must not duplicate ─────────────────────────
    again = tracking.prepare_email(db, body, msgs[0].id, utm={"utm_source": "drip"},
                                   base_url=BASE)
    check("re-preparing the same body is a no-op", again == body)
    check("no duplicate tracked links after retry",
          db.query(p11.TrackedLink).filter_by(message_id=msgs[0].id).count() == 1)
    check("no duplicate pixel", again.count(f"/t/o/{msgs[0].id}.gif") == 1)
    res2 = marketing.send_campaign(db, camp.id)
    check("re-sending the campaign creates no new messages",
          res2["sent"] == 0 and db.query(mx.EmailMessage).count() == 2, res2)

    # ── 4. acceptance is not delivery ───────────────────────────────────
    evs = db.query(mx.DeliveryEvent).filter_by(message_id=msgs[0].id).all()
    kinds = {e.event_type for e in evs}
    check("dry-run recorded simulated_delivered, never delivered",
          "simulated_delivered" in kinds and "delivered" not in kinds, kinds)
    a = unified.email_analytics(db, campaign_id=camp.id)
    check("analytics separates simulated from delivered",
          a["totals"]["delivered"] == 0 and a["totals"]["simulated_delivered"] == 2,
          a["totals"])

    # ── 5. an unsigned webhook changes nothing ──────────────────────────
    payload = json.dumps([{"id": "evt-unsigned", "message_id": msgs[0].id,
                           "type": "delivered"}]).encode()
    before = db.query(mx.DeliveryEvent).count()
    r = client.post("/px/delivery/webhook", content=payload,
                    headers={"X-DRIP-Signature": "not-a-signature",
                             "Content-Type": "application/json"})
    check("unsigned webhook is rejected", r.status_code == 401, r.status_code)
    check("and wrote nothing", db.query(mx.DeliveryEvent).count() == before)

    # ── 6. signed provider events drive the lifecycle ───────────────────
    events = [
        {"id": "evt-1", "message_id": msgs[0].id, "type": "delivered", "ts": 1},
        {"id": "evt-2", "message_id": msgs[0].id, "type": "open", "ts": 2},
        {"id": "evt-3", "message_id": msgs[0].id, "type": "click", "ts": 3},
        {"id": "evt-4", "message_id": msgs[1].id, "type": "hard_bounce", "ts": 4},
    ]
    body_bytes = json.dumps(events).encode()
    r = client.post("/px/delivery/webhook", content=body_bytes,
                    headers={"X-DRIP-Signature": _sign(body_bytes),
                             "Content-Type": "application/json"})
    check("signed webhook accepted", r.status_code == 200, r.text[:120])
    check("all four events ingested", r.json().get("accepted") == 4, r.json())

    r2 = client.post("/px/delivery/webhook", content=body_bytes,
                     headers={"X-DRIP-Signature": _sign(body_bytes),
                              "Content-Type": "application/json"})
    check("replaying the same batch is deduplicated",
          r2.json().get("accepted") == 0 and r2.json().get("duplicates") == 4, r2.json())

    # ── 7. suppression + consent ────────────────────────────────────────
    db.expire_all()
    omar_fresh = db.get(models.Person, omar.id)
    check("hard bounce set do_not_contact", omar_fresh.do_not_contact is True)
    check("hard bounce suppressed the address",
          marketing.is_suppressed(db, omar.primary_email))
    sendable, why = marketing.is_sendable(db, omar_fresh)
    check("bounced recipient is no longer sendable", not sendable, why)

    comp = [{"id": "evt-5", "message_id": msgs[0].id, "type": "spam", "ts": 5}]
    cb = json.dumps(comp).encode()
    client.post("/px/delivery/webhook", content=cb,
                headers={"X-DRIP-Signature": _sign(cb), "Content-Type": "application/json"})
    db.expire_all()
    aisha_fresh = db.get(models.Person, aisha.id)
    check("complaint set do_not_contact AND denied consent",
          aisha_fresh.do_not_contact is True and aisha_fresh.consent_status == "denied",
          f"{aisha_fresh.do_not_contact}/{aisha_fresh.consent_status}")

    # ── 8. reporting ────────────────────────────────────────────────────
    a = unified.email_analytics(db, campaign_id=camp.id)
    t = a["totals"]
    check("delivered counted only from the provider receipt", t["delivered"] == 1, t)
    check("unique opens and clicks counted",
          t["unique_opens"] == 1 and t["unique_clicks"] == 1, t)
    check("hard bounce counted", t["hard_bounces"] == 1, t)
    check("complaint counted", t["complaints"] == 1, t)
    check("CTOR present", "ctor" in a["rates"], list(a["rates"]))
    rep = marketing.campaign_report(db, camp.id)
    check("campaign_report exposes the same totals",
          rep.get("delivered") == 1 and rep.get("hard_bounces") == 1,
          {k: rep.get(k) for k in ("delivered", "hard_bounces")})

    # ── 9. open redirect is refused ─────────────────────────────────────
    check("javascript: is not a safe redirect",
          not tracking.is_safe_redirect("javascript:alert(1)"))
    check("data: is not a safe redirect",
          not tracking.is_safe_redirect("data:text/html,<script>"))
    check("protocol-relative //evil.com is not a safe redirect",
          not tracking.is_safe_redirect("//evil.com/steal"))
    check("https destination is safe",
          tracking.is_safe_redirect("https://decimal.example.com/x"))
    poisoned = p11.TrackedLink(token="poisoned-token", message_id=msgs[0].id,
                              original_url="javascript:alert(1)", utm={})
    db.add(poisoned); db.commit()
    check("a poisoned link row is refused at redirect time",
          tracking.record_click(db, "poisoned-token") is None)

    # ── 10. Mandrill adapter (native scheme) ────────────────────────────
    mandrill_payload = [{
        "event": "hard_bounce", "_id": "mandrill-evt-1", "ts": 1700000000,
        "msg": {"_id": "mandrill-msg-1", "email": "omar@lifecycle.invalid",
                "metadata": {"drip_message_id": msgs[1].id},
                "bounce_description": "bad_mailbox"}}]
    form = {"mandrill_events": json.dumps(mandrill_payload)}
    url = "https://drip.example.com/px/delivery/webhook/mandrill"
    key = "mandrill-test-key"
    signed = url + "".join(k + form[k] for k in sorted(form))
    sig = base64.b64encode(
        hmac.new(key.encode(), signed.encode(), hashlib.sha1).digest()).decode()
    from webhook_security import verify_mandrill
    raw = ("mandrill_events=" + quote(form["mandrill_events"], safe="")).encode()
    check("Mandrill signature verifies with its own SHA1 scheme",
          verify_mandrill(raw, url, form, sig, key))
    check("a tampered Mandrill body fails verification",
          not verify_mandrill(raw, url, {"mandrill_events": "[]"}, sig, key))
    canon, rejected = mandrill_events.translate(mandrill_payload)
    check("Mandrill payload maps to canonical events",
          len(canon) == 1 and not rejected, rejected)
    check("native hard_bounce maps to canonical hard_bounce",
          canon[0]["type"] == "hard_bounce", canon[0]["type"])
    check("our message id is recovered from metadata",
          canon[0]["message_id"] == msgs[1].id)
    check("provider message id preserved",
          canon[0]["provider_message_id"] == "mandrill-msg-1")
    # fail-closed: no drip_message_id means the event is rejected, not guessed
    bad_canon, bad_rejected = mandrill_events.translate(
        [{"event": "open", "_id": "x", "msg": {"_id": "y", "email": "a@b.invalid"}}])
    check("an event without our message id is rejected, never guessed",
          not bad_canon and bad_rejected
          and "drip_message_id" in bad_rejected[0]["reason"], bad_rejected)
    over = [{"event": "open", "_id": str(i), "msg": {"_id": str(i),
             "metadata": {"drip_message_id": msgs[0].id}}} for i in range(1001)]
    try:
        mandrill_events.translate(over)
        check("an oversized Mandrill batch is refused", False, "no error raised")
    except OverflowError:
        check("an oversized Mandrill batch is refused", True)

    # ── 11. event normalization ─────────────────────────────────────────
    check("a missing type is unknown, NOT delivered",
          email_events.normalize(None) == "unknown")
    check("provider aliases fold onto the canonical set",
          email_events.normalize("Spam") == "complaint"
          and email_events.normalize("deferred") == "soft_bounce"
          and email_events.normalize("SEND") == "accepted")

    # ── 12. live sending stays off ──────────────────────────────────────
    report = send_activation.activation_report(db)
    check("activation report says NOT live", report.live is False)
    check("and names the blockers", len(report.blockers) >= 1, report.blockers[:3])
    check("resolve_transport falls back to dry_run",
          send_activation.resolve_transport(db) == "dry_run")
    os.environ["EMAIL_LIVE_SENDING_ENABLED"] = "true"
    os.environ["EMAIL_TRANSPORT"] = "mandrill"
    try:
        check("flag alone does not enable live sending — credentials still missing",
              send_activation.resolve_transport(db) == "dry_run")
    finally:
        os.environ.pop("EMAIL_LIVE_SENDING_ENABLED", None)
        os.environ.pop("EMAIL_TRANSPORT", None)
    transports = list(delivery._TRANSPORTS)
    check("only the dry-run transport is registered", transports == ["dry_run"], transports)
    non_dry = db.query(mx.SendRequest).filter(mx.SendRequest.transport != "dry_run").count()
    check("every send request used dry_run", non_dry == 0, non_dry)

    db.close()
    passed = sum(1 for _, ok in _results if ok)
    print(f"\n{passed}/{len(_results)} checks passed  "
          f"[DB: {os.environ.get('DATABASE_URL', '?').split(':')[0]}]")
    return passed == len(_results)


if __name__ == "__main__":
    sys.exit(0 if run() else 1)


def test_email_lifecycle_e2e():
    assert run()
