# Claude integration prompt — Amazon SES

Integrate this SES candidate into the latest DRIP repository, rebasing rather than replacing newer files.

Do not enable live sending, contact AWS, alter provider accounts, or push/deploy without Puneet's separate authorization. Preserve Mandrill as inactive optional code and do not touch SendGrid.

Preserve all load-bearing controls: C-suite `db.flush()`, preflight and approval, stable message IDs, provider-message mapping, tenant routing, batch ledgers, cancellation, lease recovery, webhook fail-closed behavior, and current dashboard fixes.

Review the SES implementation specifically for:

1. SES v2 configuration-set use and `drip_message_id` tags.
2. IAM role credential chain—do not reintroduce mandatory static AWS keys.
3. SNS-to-SQS topic allowlisting, encryption, visibility timeout and DLQ/redrive requirements.
4. Mapping-race retries and replay idempotency.
5. SES SEND deduplication against the local accepted event.
6. DRIP versus SES open/click tracking: exactly one must be authoritative.
7. Permanent/transient bounce, complaint and suppression behavior.
8. Explicit live dispatch gates and `SEND_LIVE` confirmation.
9. Registration in API, worker and scheduler processes while disabled by default.
10. No Alembic migration should be added unless the latest repository actually requires schema changes.
11. Preserve the pre-provider `sending` commit and `unknown` terminal state for ambiguous SES timeouts; do not automatically retry an outcome that might already have been accepted by SES.
12. Confirm failed or unknown deliveries cannot mark an email or campaign as successfully sent.

Run SES tests with fake AWS clients and all existing mailing, lifecycle, dispatch, tracking, queue and dashboard suites in isolated processes. Then test against a disposable PostgreSQL schema. Report the final commit, files changed, test results, any conflicts, and confirmation that only dry-run is active.

Before a real seed handshake, provide a separate infrastructure checklist for SES identity, configuration set, SNS topic, encrypted SQS queue, DLQ, queue policy, least-privilege roles, production-access state, and the exact internal seed list. Do not send until Puneet explicitly approves that later step.
