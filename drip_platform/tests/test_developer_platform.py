"""
Sprint 8 test — developer platform: API key issue/verify/revoke (hash-at-rest,
shown once), webhook subscribe + signed fan-out, delivery with HMAC signature,
retry/backoff, and dead-letter. SQLite + PostgreSQL.
"""
import os
import sys
import hmac
import hashlib
import json
from datetime import datetime, timedelta

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from database import Base, engine, SessionLocal  # noqa: E402
import models, models_ext, models_p10, models_p11, models_p12, models_s8  # noqa: E402,F401
from abm_platform.services import developer_platform as dp  # noqa: E402

_results = []


def check(name, cond):
    _results.append((name, bool(cond))); print(("PASS" if cond else "FAIL"), "-", name)


def run():
    Base.metadata.drop_all(bind=engine); Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    # ── API keys ──
    issued = dp.create_api_key(db, "CI key", scopes=["crm.read"])
    check("api key returned once (plaintext)", issued["api_key"].startswith("dk_"))
    check("plaintext NOT stored", db.query(models_s8.ApiKey).first().key_hash
          == hashlib.sha256(issued["api_key"].encode()).hexdigest())
    check("verify good key", dp.verify_api_key(db, issued["api_key"]) is not None)
    check("verify bad key", dp.verify_api_key(db, "dk_nope_wrong") is None)
    check("last_used recorded", db.query(models_s8.ApiKey).first().last_used_at is not None)
    dp.revoke_api_key(db, issued["id"])
    check("revoked key rejected", dp.verify_api_key(db, issued["api_key"]) is None)

    # ── webhook subscription + signed fan-out ──
    sub_all = dp.create_subscription(db, "https://a.invalid/hook", event_types=[])
    sub_filt = dp.create_subscription(db, "https://b.invalid/hook", event_types=["deal.won"])

    n = dp.emit_event(db, "deal.won", {"id": "opp-1", "amount_minor": 250_000_000})
    check("fan-out to both matching subs", n == 2)
    n2 = dp.emit_event(db, "contact.created", {"id": "p-1"})
    check("filtered sub excluded (only all-sub matches)", n2 == 1)

    # verify signature is a valid HMAC of the body
    d = db.query(models_s8.WebhookDelivery).filter_by(subscription_id=sub_filt.id).first()
    body = json.dumps({"event": "deal.won", "data": {"id": "opp-1", "amount_minor": 250_000_000}},
                      sort_keys=True).encode()
    expect = "sha256=" + hmac.new(sub_filt.secret.encode(), body, hashlib.sha256).hexdigest()
    check("delivery signed with HMAC-SHA256", d.signature == expect)

    # ── delivery success ──
    captured = {}

    def ok_sender(url, headers, body):
        captured["sig"] = headers["X-DRIP-Signature"]
        return 200

    res = dp.deliver_pending(db, ok_sender, now=datetime.utcnow())
    check("all pending delivered on 2xx", res["delivered"] == 3 and res["failed"] == 0)
    check("signature header sent", captured["sig"].startswith("sha256="))

    # ── retry + dead-letter on persistent 500 ──
    dp.create_subscription(db, "https://down.invalid/hook", event_types=["x"])
    dp.emit_event(db, "x", {"n": 1})

    def bad_sender(url, headers, body):
        return 500

    t0 = datetime.utcnow()
    r1 = dp.deliver_pending(db, bad_sender, now=t0)
    # "x" matches the down sub AND the subscribe-to-all sub, so >=1 fails
    check("first attempt fails + schedules", r1["failed"] >= 1)
    dlv = (db.query(models_s8.WebhookDelivery)
           .filter_by(event_type="x", subscription_id=db.query(models_s8.WebhookSubscription)
                      .filter_by(url="https://down.invalid/hook").first().id).first())
    # drive to max_attempts (5) by advancing past each backoff
    t = t0
    for _ in range(6):
        t = t + timedelta(hours=24)
        dp.deliver_pending(db, bad_sender, now=t)
    db.refresh(dlv)
    check("dead-lettered after max attempts", dlv.status == "dead_letter" and dlv.attempts == 5)

    passed = sum(1 for _, ok in _results if ok); total = len(_results)
    is_pg = db.bind.dialect.name == "postgresql"
    print(f"\n{passed}/{total} checks passed  [DB: {'postgresql' if is_pg else 'sqlite'}]")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)


def test_developer_platform():
    assert run()
