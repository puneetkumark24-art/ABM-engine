# DRIP Disaster Recovery & Backup Runbook (Sprint 10)

## Objectives
- **RPO** (max data loss): ≤ 5 minutes (continuous WAL archiving / PITR).
- **RTO** (max downtime): ≤ 60 minutes (managed multi-AZ failover + restore).

## Backups (managed Postgres 16 — provisioned in `deploy/terraform/main.tf`)
- Automated daily snapshots, **14-day PITR** window, encrypted at rest.
- WAL archived continuously to object storage in-region (`me-south-1`, KSA
  residency).
- **Verification**: a monthly restore drill into an isolated database validates
  snapshot integrity and measures actual RTO. Record results in the DR log.

## Restore procedure (point-in-time)
1. Identify the target timestamp (just before the incident).
2. Trigger managed PITR restore to a new instance at that timestamp.
3. Run `alembic current` to confirm schema revision matches app expectation.
4. Repoint the app's `DATABASE_URL` secret; recycle API + worker pods.
5. Validate `/health/ready`, run smoke tests, confirm RLS (`app_rw`) is enforced.

## Regional failover
Multi-AZ writer failover is automatic. Cross-region DR (if required for the
bank's BCP) restores the latest snapshot + WAL into the secondary region; DNS/
secret repointing as above.

## Application-consistent concerns
- The transactional outbox + durable job queue mean in-flight side effects are
  replayed idempotently after restore (Sprint 6 idempotency keys prevent double
  execution).
- Outbound webhook deliveries resume from their durable rows.

## BLOCKED-EXTERNAL
Automated backup scheduling, PITR, and cross-region replication are managed-
infrastructure features that require the provisioned cloud account and cannot be
exercised from application code. The Terraform declares them; final DR
certification requires an actual restore drill in the target account.
