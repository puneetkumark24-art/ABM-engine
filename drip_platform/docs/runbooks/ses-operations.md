# Amazon SES operations runbook

Live sending remains off until the change owner explicitly enables it after a successful seed rehearsal.

## Deployment order

1. Apply the SES infrastructure plan in a non-production AWS account/region.
2. Publish the Terraform DNS outputs through the authorised DNS process and wait for identity/DKIM verification.
3. Attach the generated sender policy only to the API/dispatch worker role and the receipt policy only to the receipt-consumer role.
4. Populate configuration values from Terraform outputs. Do not store AWS access keys; use workload identity.
5. Deploy the receipt consumer while `ENABLE_SES_TRANSPORT=false`, `EMAIL_LIVE_SENDING_ENABLED=false`, and `EMAIL_TRANSPORT=dry_run`.
6. Confirm the queue is empty, the DLQ is empty, and the consumer has no permission errors.
7. Run a separately approved internal seed send. Verify accepted, delivered, open/click (DRIP tracking), bounce and complaint simulations before any customer traffic.

## Receipt backlog

- Keep live sending disabled if the oldest receipt is approaching the analytics or suppression-response SLO.
- Check consumer replicas, IAM denial logs, database connectivity, queue visibility timeout and poison-message receive count.
- Scale consumers only after confirming failures are transient; concurrency does not repair malformed or unmapped events.
- Never delete the queue to clear a backlog.

## Dead letters

- Pause live sending when any bounce or complaint receipt is dead-lettered; suppression state may be incomplete.
- Export message metadata for investigation without recipient addresses or message bodies.
- Classify the cause: invalid SNS envelope, topic mismatch, unknown event, missing provider mapping, database outage, or application defect.
- Fix the cause and redrive through SQS. The ingestion path is idempotent, so accepted replays are safe.
- Do not manually mark a message delivered or suppressed without an auditable provider event.

## Ambiguous send outcome

A request in `unknown` means SES may have accepted the message but DRIP did not receive a definitive response. Never automatically resend it. Reconcile it using the stable DRIP message tag, SES logs/event receipt and provider mapping. An operator may close it as delivered, failed, or explicitly authorise a replacement with a new message ID.

## Emergency stop

Set `EMAIL_LIVE_SENDING_ENABLED=false` and `EMAIL_TRANSPORT=dry_run`, then roll the API and workers. Keep the receipt consumer running so late delivery, bounce and complaint events continue updating suppression and analytics.

## Rollback

Application rollback must preserve `provider_message_maps`, delivery requests, event records and the SQS queue. Infrastructure teardown is not a normal rollback. Disable event publication only after the queue is drained and the retention window has elapsed.
