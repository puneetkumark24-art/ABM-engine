# SES production-readiness phase

## Added

- Terraform-managed SES identity, custom MAIL FROM, TLS-required configuration set and reputation/suppression settings.
- Encrypted SNS topic, encrypted SQS receipt queue, 14-day DLQ, redrive policy and exact-topic queue policy.
- SES event publication excludes provider OPEN/CLICK because DRIP tracking remains authoritative.
- Separate least-privilege sender and receipt-consumer IAM policy documents.
- Optional Docker Compose receipt-consumer profile and a two-replica Kubernetes consumer using workload identity.
- Backlog and DLQ alert definitions plus an incident/rollback runbook.

## Safety state

The application defaults remain `dry_run`; Terraform creation alone cannot make DRIP send. No AWS request, GitHub operation, deployment or database change was performed.

## Integration cautions

- Replace the Kubernetes role ARN placeholder through the deployment secret/configuration process.
- Validate metric names against the deployed CloudWatch exporter; the alert rules express the required conditions but exporters differ in naming.
- Review Terraform against the latest repository and account standards before applying.
- DNS records and SES production access still require an authorised AWS/DNS operator.

## Required next external gate

After Claude rebases this candidate: plan in a non-production AWS account, review IAM/DNS diffs, deploy the receipt plane with sending disabled, then conduct a separately approved internal seed handshake.
