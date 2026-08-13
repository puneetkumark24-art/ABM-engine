"""Dedicated SES SNS-to-SQS receipt consumer. Configure an SQS DLQ."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import SessionLocal  # noqa: E402
from abm_platform.services import ses_receipts  # noqa: E402


def main():
    queue_url = os.environ.get("SES_EVENT_QUEUE_URL", "").strip()
    topic_arn = os.environ.get("SES_EVENT_TOPIC_ARN", "").strip()
    region = os.environ.get("AWS_SES_REGION", "").strip()
    if not queue_url or not topic_arn or not region:
        raise RuntimeError("SES_EVENT_QUEUE_URL, SES_EVENT_TOPIC_ARN and AWS_SES_REGION are required")
    import boto3
    client = boto3.client("sqs", region_name=region)
    print("[ses-events] consumer up; SQS auth and SNS topic allowlist active", flush=True)
    while True:
        result = ses_receipts.poll_once(SessionLocal, client, queue_url, topic_arn)
        if result["received"]:
            print(f"[ses-events] {result}", flush=True)


if __name__ == "__main__":
    main()
