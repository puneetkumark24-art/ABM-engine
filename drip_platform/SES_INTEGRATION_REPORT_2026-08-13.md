# Amazon SES integration — local candidate

## Outcome

DRIP now has an end-to-end Amazon SES v2 implementation candidate while remaining dry-run by default. No AWS API, live provider, GitHub repository, working PostgreSQL database, Mandrill account, or SendGrid account was contacted or changed.

## Implemented

- SES v2 `SendEmail` adapter using UTF-8 HTML, a required verified sender, optional reply-to, and a required configuration set.
- Opaque `drip_message_id` SES tag and the existing PII-free `provider_message_maps` correlation directory.
- IAM credential-chain support; static AWS access keys are no longer incorrectly mandatory.
- Native SES event translation for send, delivery, bounce, complaint, rejection, rendering failure, delivery delay, and subscription opt-out.
- Hard/transient bounce normalization and reuse of DRIP suppression, consent, analytics and account-rollup behavior.
- Durable SNS → encrypted SQS → DRIP consumer architecture, with topic ARN allowlisting, bounded body size, visibility retry, and expected DLQ use.
- Receipt race handling: canonical events rejected because their provider mapping has not committed remain in SQS for retry.
- Replay idempotency, including deduplication of SES `SEND` against the local provider-acceptance event.
- Engagement-source protection: SES opens/clicks are ignored by default because DRIP already owns the open pixel and redirect. `SES_USE_PROVIDER_ENGAGEMENT=true` is an explicit alternative, not an additive mode.
- API, worker, and scheduler startup registration, which remains inert unless `ENABLE_SES_TRANSPORT=true`.
- Explicit live campaign dispatch requiring all activation checks plus the exact `SEND_LIVE` confirmation. Default dashboard/API dispatch remains dry-run.
- Live sends precommit a `sending` intent before the provider call. Ambiguous network timeouts become `unknown` and are never automatically retried, preventing an accepted SES message from being sent twice after a crash or lost response.
- Campaign/message state now distinguishes confirmed delivery failure and ambiguous delivery from a successful send; affected campaigns move to `attention_required` instead of being falsely marked sent.

## Required AWS shape

1. Verify the sending domain/identity in the chosen SES region.
2. Configure DKIM, SPF, DMARC, and a custom MAIL FROM/return path.
3. Create an SES configuration set.
4. Publish SEND, DELIVERY, BOUNCE, COMPLAINT, REJECT, RENDERING_FAILURE and DELIVERY_DELAY to one SNS topic. Exclude OPEN and CLICK while DRIP tracking is enabled.
5. Subscribe an encrypted SQS queue to that topic and attach a DLQ/redrive policy.
6. Restrict `sqs:SendMessage` on the queue to that exact SNS topic ARN.
7. Give the sender role only `ses:SendEmail`; give the receipt worker only receive/delete/change-visibility on the exact queue.
8. Use IAM task/instance roles or workload identity instead of long-lived keys.

## Activation variables

`ENABLE_SES_TRANSPORT`, `EMAIL_LIVE_SENDING_ENABLED`, `EMAIL_TRANSPORT=ses`, `AWS_SES_REGION`, `SES_FROM`, `SES_REPLY_TO`, `SES_CONFIGURATION_SET`, `SES_EVENT_TOPIC_ARN`, `SES_EVENT_QUEUE_URL`, `PUBLIC_BASE_URL`, `EMAIL_SENDING_DOMAIN`, `EMAIL_RETURN_PATH`, and `EMAIL_UNSUBSCRIBE_URL`.

## Safety gates

- Importing the module neither registers a transport nor makes a network call.
- Missing explicit flags/configuration leaves only `dry_run` operational.
- A live dispatch cannot silently fall back to simulation; it raises a blocker.
- The ordinary dispatch endpoint remains dry-run unless `live=true` and `confirmation=SEND_LIVE` are both supplied.
- Provider events require both the DRIP tag and the precommitted SES provider mapping.

## Verification completed locally

- Fake SES send, configuration set, tags, reply-to and provider correlation.
- SNS topic allowlist rejection.
- Delivery event ingestion and replay deduplication.
- Permanent/transient bounce and complaint translation.
- Unknown-event fail-closed behavior.
- Provider-open opt-in and default duplicate-tracking prevention.
- SES remains unregistered without explicit opt-in.
- Live campaign dispatch is blocked when activation is incomplete.
- Existing campaign workspace and durable batch suites remain green.
- Final focused verification: 11 tests passed; syntax compilation passed; Alembic remains a single head at `x1f3a5b7c9d1`; `git diff --check` passed (line-ending notices only).

## Still external and intentionally not done

- SES account production-access approval.
- Real identity/configuration-set lookup.
- Real SNS/SQS policy and KMS verification.
- Real sandbox seed send and receipt round trip.
- Deliverability warm-up and controlled production pilot.
