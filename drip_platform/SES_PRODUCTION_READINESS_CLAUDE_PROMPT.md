# Claude prompt — integrate SES production readiness

Rebase the attached SES production-readiness files onto the latest DRIP main branch. Do not replace newer files wholesale. Do not apply Terraform, contact AWS, send email, alter DNS, push, deploy, or enable live sending without Puneet's separate approval.

Preserve all existing campaign, C-suite approval, preflight, tenant, idempotency, suppression, tracking, dashboard and ambiguous-send protections. Keep SendGrid untouched and Mandrill optional/inactive.

Review and adapt:

1. Terraform SES identity, custom MAIL FROM, configuration set, encrypted SNS/SQS/DLQ and exact-topic queue policy.
2. Event types must exclude SES OPEN/CLICK while DRIP open/click tracking is authoritative.
3. Attach least-privilege IAM policies to separate sender and receipt-consumer workload identities; no static AWS keys.
4. Ensure the SQS visibility timeout exceeds worst-case receipt processing and the DLQ/redrive values match operational SLOs.
5. Wire the receipt consumer into the actual deployment system while keeping both live-send flags false.
6. Map the backlog/DLQ alerts to the real CloudWatch exporter metric names in this environment.
7. Preserve the operational runbook and add exact log/dashboard queries used by the deployed stack.

Run formatting/validation for Terraform, Kubernetes YAML and Compose; run all SES, lifecycle, campaign dispatch, queue, suppression, analytics and dashboard tests against disposable PostgreSQL. Return the plan output only—do not apply it. Report conflicts, security findings, final commit, test evidence and confirmation that dry-run is still the only active transport.
