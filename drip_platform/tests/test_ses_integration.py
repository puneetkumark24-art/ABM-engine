import json
import os
import tempfile
import uuid

os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.gettempdir(), "drip_ses_integration.db")
from database import Base, engine, SessionLocal
import models
import models_ext as mx
import models_p11
from abm_platform.services import delivery, ses_delivery, ses_events, ses_receipts

Base.metadata.drop_all(engine)
Base.metadata.create_all(engine)


class FakeSes:
    def __init__(self): self.calls = []
    def send_email(self, **kwargs):
        self.calls.append(kwargs)
        return {"MessageId": "ses-provider-123"}


class ReadTimeoutError(Exception):
    pass


class TimeoutSes:
    def send_email(self, **kwargs): raise ReadTimeoutError("timed out")


def _ses_event(message_id, event_type="Delivery", provider_id="ses-provider-123", **detail):
    key = event_type.lower()
    return {"eventType": event_type,
            "mail": {"messageId": provider_id, "timestamp": "2026-08-13T08:00:00Z",
                     "tags": {"drip_message_id": [message_id]}},
            key: {"timestamp": "2026-08-13T08:00:01Z", **detail}}


def test_ses_sender_tags_and_correlates_then_ingests_sns_sqs_receipt():
    db = SessionLocal()
    org = models.Organization(canonical_name=f"SES Bank {uuid.uuid4().hex[:8]}")
    db.add(org); db.flush()
    person = models.Person(full_name="SES Seed", primary_email="seed@example.invalid",
                           current_org_id=org.id, is_active=True, consent_status="opted_in")
    db.add(person); db.flush()
    message_id = str(uuid.uuid4())
    db.add(mx.EmailMessage(id=message_id, person_id=person.id,
                           to_email=person.primary_email, status="queued")); db.commit()

    fake = FakeSes()
    config = ses_delivery.SesConfig("me-south-1", "sender@example.invalid",
                                    "drip-test", "reply@example.invalid")
    delivery.register_transport("ses_test", ses_delivery.build_transport(fake, config))
    req = delivery.enqueue(db, message_id, person.primary_email, "Hello", "<p>Body</p>",
                           transport="ses_test")
    assert req.status == "sent" and req.provider_message_id == "ses-provider-123"
    call = fake.calls[0]
    assert call["ConfigurationSetName"] == "drip-test"
    assert call["EmailTags"] == [{"Name": "drip_message_id", "Value": message_id}]
    assert call["ReplyToAddresses"] == ["reply@example.invalid"]
    # Production registers as provider 'ses'; mirror that opaque correlation.
    delivery.bind_provider_message(db, "ses", "ses-provider-123", message_id); db.commit()

    payload = _ses_event(message_id)
    envelope = json.dumps({"Type": "Notification", "TopicArn": "arn:allowed",
                           "Message": json.dumps(payload)})
    result = ses_receipts.process_body(db, envelope, "arn:allowed")
    assert result["accepted"] == 1 and result["acknowledge"] is True
    assert db.get(mx.EmailMessage, message_id).status == "delivered"
    replay = ses_receipts.process_body(db, envelope, "arn:allowed")
    assert replay["duplicates"] == 1 and replay["acknowledge"] is True
    send_payload = _ses_event(message_id, "Send")
    send_envelope = json.dumps({"Type": "Notification", "TopicArn": "arn:allowed",
                                "Message": json.dumps(send_payload)})
    accepted_replay = ses_receipts.process_body(db, send_envelope, "arn:allowed")
    assert accepted_replay["duplicates"] == 1
    db.close()


def test_ses_translation_and_fail_closed_envelope():
    mid = str(uuid.uuid4())
    hard, rejected = ses_events.translate(_ses_event(
        mid, "Bounce", bounceType="Permanent", bouncedRecipients=[{"emailAddress": "x"}]))
    assert not rejected and hard[0]["type"] == "hard_bounce"
    soft, _ = ses_events.translate(_ses_event(mid, "Bounce", bounceType="Transient"))
    assert soft[0]["type"] == "soft_bounce"
    complaint, _ = ses_events.translate(_ses_event(mid, "Complaint"))
    assert complaint[0]["type"] == "complaint"
    provider_open, rejected = ses_events.translate(_ses_event(mid, "Open"))
    assert not provider_open and rejected
    provider_open, rejected = ses_events.translate(_ses_event(mid, "Open"), True)
    assert provider_open[0]["type"] == "open" and not rejected
    unknown, rejected = ses_events.translate(_ses_event(mid, "FutureNewEvent"))
    assert not unknown and rejected
    try:
        ses_receipts.decode_sqs_body(json.dumps({"Type": "Notification",
            "TopicArn": "arn:evil", "Message": "{}"}), "arn:allowed")
        assert False
    except ValueError as exc:
        assert "allowlisted" in str(exc)


def test_ses_config_stays_inactive_without_explicit_flag():
    os.environ.pop("ENABLE_SES_TRANSPORT", None)
    before = set(delivery._TRANSPORTS)
    ok, _ = ses_delivery.try_register()
    assert ok is False and set(delivery._TRANSPORTS) == before


def test_ambiguous_ses_timeout_is_never_automatically_retried():
    db = SessionLocal()
    mid = str(uuid.uuid4())
    delivery.register_transport("ses_timeout", ses_delivery.build_transport(
        TimeoutSes(), ses_delivery.SesConfig("me-south-1", "sender@example.invalid", "cfg")))
    req = delivery.enqueue(db, mid, "seed@example.invalid", "Subject", "Body",
                           transport="ses_timeout")
    assert req.status == "unknown" and req.attempts == 1
    from abm_platform.services import delivery_ext
    result = delivery_ext.retry_failed(db)
    assert result["retried"] == 0 and req.status == "unknown"
    db.close()


def test_ses_activation_accepts_iam_role_configuration_without_static_keys():
    from abm_platform.services import send_activation
    db = SessionLocal()
    domain = f"ses-{uuid.uuid4().hex[:8]}.example.invalid"
    db.add(models_p11.DomainHealth(domain=domain, spf_ok=True, dkim_ok=True, dmarc_ok=True))
    db.commit()
    values = {
        "EMAIL_LIVE_SENDING_ENABLED": "true", "EMAIL_TRANSPORT": "ses",
        "AWS_SES_REGION": "me-south-1", "SES_FROM": f"mail@{domain}",
        "SES_CONFIGURATION_SET": "drip-test", "SES_EVENT_QUEUE_URL": "https://sqs.invalid/q",
        "SES_EVENT_TOPIC_ARN": "arn:aws:sns:me-south-1:123:test",
        "PUBLIC_BASE_URL": "https://track.example.invalid", "EMAIL_SENDING_DOMAIN": domain,
        "EMAIL_RETURN_PATH": f"bounce@{domain}",
        "EMAIL_UNSUBSCRIBE_URL": "https://track.example.invalid/unsubscribe",
    }
    old = {k: os.environ.get(k) for k in values}
    for key, value in values.items(): os.environ[key] = value
    os.environ.pop("AWS_ACCESS_KEY_ID", None); os.environ.pop("AWS_SECRET_ACCESS_KEY", None)
    delivery.register_transport("ses", lambda req: "not-called")
    try:
        report = send_activation.activation_report(db)
        assert report.live is True and report.transport == "ses"
        assert not any("AWS_ACCESS_KEY" in blocker for blocker in report.blockers)
    finally:
        for key, value in old.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value
        delivery._TRANSPORTS.pop("ses", None)
        db.close()
