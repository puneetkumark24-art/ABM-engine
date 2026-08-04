# Production Readiness Decision

## Decision

The codebase is a production-candidate shadow signal engine, but production
activation and DRIP migration are **not approved yet**. This distinction is
intentional: code integrity tests pass, while live evidence coverage and human
quality calibration remain below their gates.

## Verified locally

- 36 engine tests and 1 one-way bridge integration test pass.
- Existing v8 SQLite data upgrades to schema version 3.
- SQLite uses foreign keys, WAL, bounded lock waiting and migration-safe upserts.
- Raw capture payloads are bounded and common credentials/contact fields redacted.
- Watch URLs require public, credential-free HTTPS endpoints.
- Correction/retraction matching uses event type, date window and lexical evidence.
- Correction decisions retain an immutable relation audit trail.
- Shadow mode forces `action_eligible=0`.
- Generic webhooks require a five-minute HMAC timestamp window.
- DRIP preview performs no writes; export validates schema and is transactional,
  idempotent, quality-gated and uncontested-signal-only.

## Gates that remain closed

- Required live 360 coverage is 35.61%, below the 90% migration threshold.
- LinkedIn company/people/jobs have no authorized live connector.
- CRM, email engagement and website intent have adapters but no verified live
  account-specific event coverage.
- Quality has 607 computed assessments but zero human calibration decisions;
  the required sample is 100 with at least 90% agreement.
- Only one independent source family exists in the current legacy evidence.
- PostgreSQL export is not implemented; the supplied bridge is SQLite-specific.
- Distributed scheduler locking, dead-letter replay, production observability,
  load testing and disaster-recovery drills still require the target environment.

## Activation rule

Do not migrate or enable scoring until the 90% capture gate and quality gate are
both true, target-schema migration is reviewed, a backup/rollback rehearsal is
completed, and Puneet explicitly authorizes changes to original DRIP.
