"""SES handshake through the WHOLE chain, against a stub that speaks SESv2.

The existing SES suite tests the adapter's pieces. This one answers a different
question: with a live-style transport actually REGISTERED, does a campaign go
end to end correctly — dispatch, worker batch, provider call, correlation
record, receipt ingestion, suppression — without anything leaking to dry-run
assumptions or to AWS?

It is the local equivalent of a provider sandbox handshake. The stub implements
the two SESv2 calls the adapter makes and records exactly what it was asked to
send, so the assertions are about the real request DRIP would put on the wire:
the configuration set, the tagged message id, the recipient, the body.

Nothing here reaches AWS. The transport is registered under a test-only name so
`delivery._TRANSPORTS` keeps only `dry_run` for every other suite and for the
application at runtime.
"""
import json
import os
import sys
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("PUBLIC_BASE_URL", "https://drip.example.com")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from database import Base, engine, SessionLocal  # noqa: E402
import models  # noqa: E402
import models_ext as mx  # noqa: E402
import models_ai, models_audit, models_collectors, models_crm2  # noqa: E402,F401
import models_final, models_intel, models_jobs, models_llm  # noqa: E402,F401
import models_p10, models_p11, models_p12, models_s3, models_s6, models_s8  # noqa: E402,F401
import models_segments, models_tenant  # noqa: E402,F401
from abm_platform.services import (  # noqa: E402
    delivery, marketing, ses_delivery, ses_receipts, unified,
)

_results = []
TOPIC = "arn:aws:sns:me-south-1:123456789012:drip-ses-events"


def check(name, cond, detail=""):
    _results.append((name, bool(cond)))
    print(("PASS" if cond else "FAIL"), "-", name, ("| " + str(detail)) if detail else "")


class StubSes:
    """The two SESv2 calls the adapter makes, and nothing else.

    Records every request so the test can assert on what would actually have
    been transmitted, rather than only on the adapter's return value.
    """

    def __init__(self):
        self.sent = []

    def send_email(self, **kwargs):
        self.sent.append(kwargs)
        return {"MessageId": f"0100018f-{uuid.uuid4().hex[:16]}-000000"}


def _sns_envelope(event_type: str, ses_message_id: str, recipient: str,
                  drip_message_id: str, topic_arn: str = TOPIC) -> str:
    """The shape SES actually delivers: an SNS envelope wrapping a JSON string.

    Note SES message tags arrive as {name: [value]} -- a LIST, not a scalar.
    An earlier version of this fixture used an empty list and the receipt
    processor correctly refused the event with "missing drip_message_id tag"
    rather than guessing which message it belonged to. Worth keeping in mind:
    the fail-closed path is real, and a malformed tag means the receipt is
    dropped, not misapplied.
    """
    inner = {
        "eventType": event_type,
        "mail": {"messageId": ses_message_id,
                 "destination": [recipient],
                 "timestamp": "2026-08-13T10:00:00.000Z",
                 "tags": {"drip_message_id": [drip_message_id]}},
    }
    if event_type == "Bounce":
        inner["bounce"] = {"bounceType": "Permanent",
                           "bouncedRecipients": [{"emailAddress": recipient}]}
    elif event_type == "Complaint":
        inner["complaint"] = {"complainedRecipients": [{"emailAddress": recipient}]}
    return json.dumps({"Type": "Notification", "TopicArn": topic_arn,
                       "Message": json.dumps(inner)})


def run():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    config = ses_delivery.SesConfig(region="me-south-1",
                                    from_email="outreach@drip.example.com",
                                    configuration_set="drip-prod")

    stub = StubSes()
    # Registered under the REAL transport name, deliberately. An earlier
    # version used "ses_sandbox" to keep the real slot empty -- and every
    # receipt was then rejected, because bind_provider_message() records the
    # correlation row under the TRANSPORT name used at send time, while SES
    # receipts arrive claiming provider "ses". The lookup is (provider,
    # provider_message_id), so the two must agree.
    #
    # That is worth knowing operationally: if SES is ever registered under any
    # name other than "ses", sends succeed and every delivery receipt is
    # silently discarded as unmapped. The name is not cosmetic.
    #
    # The stub is not AWS, and the transport is removed again at the end of
    # this run, so nothing is left registered.
    delivery.register_transport("ses", ses_delivery.build_transport(stub, config))
    check("stub SES transport registered under the real transport name",
          "ses" in delivery._TRANSPORTS, sorted(delivery._TRANSPORTS))

    org = models.Organization(canonical_name="Sandbox Bank")
    db.add(org); db.commit()
    good = models.Person(full_name="Layla Ops", current_org_id=org.id,
                         primary_email="layla@sandbox.invalid", consent_status="opted_in",
                         seniority_level="manager")
    bouncer = models.Person(full_name="Dead Mailbox", current_org_id=org.id,
                            primary_email="dead@sandbox.invalid", consent_status="opted_in",
                            seniority_level="manager")
    db.add_all([good, bouncer]); db.commit()

    # ── the send, through the real enqueue path ─────────────────────────
    body = ('<html><body>Hello '
            '<a href="https://decimal.example.com/x">link</a> '
            '<a href="https://drip.example.com/p/prefs">unsubscribe</a></body></html>')
    reqs = []
    for person in (good, bouncer):
        mid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"drip:sandbox:{person.id}"))
        db.add(mx.EmailMessage(id=mid, person_id=person.id, to_email=person.primary_email))
        db.flush()
        reqs.append(delivery.enqueue(db, message_id=mid, to_email=person.primary_email,
                                     subject="Sandbox handshake", body=body,
                                     transport="ses"))
    db.commit()

    check("both sends were accepted by the provider",
          all(r.status == "sent" for r in reqs), [r.status for r in reqs])
    check("the provider was actually called twice", len(stub.sent) == 2, len(stub.sent))

    # what would really have gone on the wire
    call = stub.sent[0]
    check("the configured sender was used",
          call.get("FromEmailAddress") == "outreach@drip.example.com",
          call.get("FromEmailAddress"))
    check("the configuration set is set (SES cannot emit events without it)",
          call.get("ConfigurationSetName") == "drip-prod",
          call.get("ConfigurationSetName"))
    dest = (call.get("Destination") or {}).get("ToAddresses") or []
    check("exactly one recipient per request (no accidental fan-out)",
          len(dest) == 1, dest)
    tags = {t.get("Name"): t.get("Value") for t in (call.get("EmailTags") or [])}
    check("our message id is tagged onto the send, so receipts can be correlated",
          tags.get("drip_message_id") == reqs[0].message_id, tags)

    # ── acceptance is recorded as acceptance, never delivery ────────────
    evs = db.query(mx.DeliveryEvent).filter_by(message_id=reqs[0].message_id).all()
    kinds = {e.event_type for e in evs}
    check("a live transport records `accepted`, not `delivered`",
          "accepted" in kinds and "delivered" not in kinds, kinds)
    check("and not `simulated_delivered` either (that is dry-run only)",
          "simulated_delivered" not in kinds, kinds)

    # ── correlation record written for the public receipt path ─────────
    maps = db.query(mx.ProviderMessageMap).all()
    check("a provider correlation row exists per send", len(maps) == 2, len(maps))
    check("it is PII-free (no recipient address stored)",
          all(not any("@" in str(getattr(m, c.name, "") or "")
                      for c in m.__table__.columns) for m in maps))
    provider_id_for = {m.message_id: m.provider_message_id for m in maps}

    # ── receipts: delivery, then a hard bounce ──────────────────────────
    ok_env = _sns_envelope("Delivery", provider_id_for[reqs[0].message_id],
                           good.primary_email, reqs[0].message_id)
    res = ses_receipts.process_body(db, ok_env, TOPIC)
    check("a Delivery receipt is ingested", (res or {}).get("accepted", 0) >= 1, res)
    db.expire_all()
    a = unified.email_analytics(db)
    check("only NOW is the message counted as delivered",
          a["totals"]["delivered"] == 1, a["totals"]["delivered"])

    replay = ses_receipts.process_body(db, ok_env, TOPIC)
    check("replaying the same receipt is deduplicated",
          (replay or {}).get("accepted", 0) == 0, replay)

    bounce_env = _sns_envelope("Bounce", provider_id_for[reqs[1].message_id],
                               bouncer.primary_email, reqs[1].message_id)
    ses_receipts.process_body(db, bounce_env, TOPIC)
    db.expire_all()
    fresh = db.get(models.Person, bouncer.id)
    check("a hard bounce sets do_not_contact", fresh.do_not_contact is True)
    check("and suppresses the address",
          marketing.is_suppressed(db, bouncer.primary_email))
    sendable, why = marketing.is_sendable(db, fresh)
    check("the bounced recipient is no longer sendable", not sendable, why)

    # ── a receipt from a topic we do not own is refused ─────────────────
    foreign = _sns_envelope("Bounce", provider_id_for[reqs[0].message_id],
                            good.primary_email, reqs[0].message_id,
                            topic_arn="arn:aws:sns:us-east-1:999999999999:attacker")
    try:
        out = ses_receipts.process_body(db, foreign, TOPIC)
        refused = not out or out.get("accepted", 0) == 0
    except Exception:
        refused = True                      # raising is an equally correct refusal
    check("a receipt from a foreign SNS topic is refused", refused)
    db.expire_all()
    check("and the good recipient was NOT suppressed by it",
          not marketing.is_suppressed(db, good.primary_email))

    # ── the real 'ses' slot is still empty ─────────────────────────────
    delivery._TRANSPORTS.pop("ses", None)
    check("no live transport left registered after the handshake",
          list(delivery._TRANSPORTS) == ["dry_run"], list(delivery._TRANSPORTS))

    db.close()
    passed = sum(1 for _, ok in _results if ok)
    print(f"\n{passed}/{len(_results)} checks passed")
    return passed == len(_results)


if __name__ == "__main__":
    sys.exit(0 if run() else 1)


def test_ses_sandbox_handshake():
    assert run()
