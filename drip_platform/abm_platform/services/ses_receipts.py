"""Durable SES receipt processing for SNS notifications delivered through SQS."""
from __future__ import annotations
import json
import logging
import os
from sqlalchemy.orm import Session
from . import delivery, ses_events

MAX_SQS_BODY = 262_144
logger = logging.getLogger("drip.ses_receipts")


def decode_sqs_body(body: str, allowed_topic_arn: str) -> dict:
    if not body or len(body.encode("utf-8")) > MAX_SQS_BODY:
        raise ValueError("SQS body is empty or too large")
    envelope = json.loads(body)
    if not isinstance(envelope, dict) or envelope.get("Type") != "Notification":
        raise ValueError("expected an SNS Notification envelope")
    if not allowed_topic_arn or envelope.get("TopicArn") != allowed_topic_arn:
        raise ValueError("SNS topic is not allowlisted")
    message = envelope.get("Message")
    if not isinstance(message, str):
        raise ValueError("SNS Message must be JSON text")
    payload = json.loads(message)
    if not isinstance(payload, dict):
        raise ValueError("SES event must be an object")
    return payload


def process_body(db: Session, body: str, allowed_topic_arn: str) -> dict:
    payload = decode_sqs_body(body, allowed_topic_arn)
    canonical, mapping_errors = ses_events.translate(
        payload, allow_provider_engagement=(
            os.environ.get("SES_USE_PROVIDER_ENGAGEMENT", "false").lower() == "true"))
    if not canonical:
        return {"provider": "ses", "accepted": 0, "duplicates": 0,
                "rejected": 0, "mapping_rejected": len(mapping_errors),
                "mapping_errors": mapping_errors[:20], "acknowledge": True}
    result = delivery.ingest_webhook(db, canonical)
    result.update(provider="ses", mapping_rejected=len(mapping_errors),
                  mapping_errors=mapping_errors[:20])
    # A canonical event rejected here usually raced the provider-map commit.
    # Leave it in SQS; visibility retry resolves the race and a DLQ bounds it.
    result["acknowledge"] = result.get("rejected", 0) == 0
    return result


def poll_once(db_factory, sqs_client, queue_url: str, topic_arn: str,
              wait_seconds: int = 20, max_messages: int = 10) -> dict:
    response = sqs_client.receive_message(
        QueueUrl=queue_url, MaxNumberOfMessages=max(1, min(max_messages, 10)),
        WaitTimeSeconds=max(0, min(wait_seconds, 20)),
        VisibilityTimeout=int(os.environ.get("SES_SQS_VISIBILITY_SECONDS", "120")),
    )
    received = acknowledged = retried = failed = 0
    for message in response.get("Messages", []):
        received += 1
        db = db_factory()
        try:
            result = process_body(db, message.get("Body", ""), topic_arn)
            if result["acknowledge"]:
                sqs_client.delete_message(QueueUrl=queue_url,
                                          ReceiptHandle=message["ReceiptHandle"])
                acknowledged += 1
            else:
                logger.warning("SES receipt retained for retry: %s", result)
                retried += 1
        except Exception:
            logger.exception("SES receipt processing failed; message retained for retry")
            db.rollback(); failed += 1
        finally:
            db.close()
    return {"received": received, "acknowledged": acknowledged,
            "retried": retried, "failed": failed}
