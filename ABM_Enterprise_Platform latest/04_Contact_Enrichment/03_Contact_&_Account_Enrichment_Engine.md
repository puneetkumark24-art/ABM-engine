# Module 03 — Contact & Account Enrichment Engine

> **Domain folder:** `04_Contact_Enrichment`  
> **Replaces / equivalent to:** Apollo + Clay + ZoomInfo + Lusha — data acquisition, waterfall enrichment, verification.

## 1. Purpose
Acquire, resolve, verify and continuously refresh contact and company data into the graph — a native waterfall enrichment pipeline with provider adapters, email/phone verification, and identity resolution, so the platform owns its data instead of renting Apollo.

## 2. Scope
**In scope**
- Provider adapter framework (pluggable data sources)
- Waterfall enrichment (try sources in priority order)
- Email/phone verification & scoring
- Identity resolution & merge
- Refresh scheduling & staleness detection

**Out of scope**
- Signal capture (Signal Engine)
- Relationship inference (Relationship Graph Engine, 05-graph)
- Outreach

## 3. Personas
| Persona | Relationship to module |
|---|---|
| System | Runs enrichment jobs |
| Data Steward | Configures providers, resolves merge conflicts |
| AE | Requests enrichment on a target |

## 4. Data Entities & Schema

### `enrichment_job`
One enrichment request for an entity.

```
id UUID pk; tenant_id UUID; entity_type enum(contact,company); entity_id UUID; status enum(queued,running,partial,done,failed); providers_tried text[]; result jsonb; cost_credits int; created_at; finished_at
```

### `provider`
A configured data source adapter.

```
id UUID pk; name text; kind enum(contact,company,email_verify,phone_verify); priority int; cost_per_call numeric; rate_limit int; enabled bool; config jsonb
```

### `verification`
Email/phone verification result.

```
id UUID pk; contact_id UUID; channel enum(email,phone); status enum(valid,invalid,risky,unknown,catch_all); score numeric(4,3); verified_at timestamptz
```

### `merge_candidate`
Two records suspected identical.

```
id UUID pk; entity_type enum; a_id UUID; b_id UUID; similarity numeric(4,3); signals jsonb; status enum(pending,merged,rejected)
```

## 5. API Contracts
| Method | Path | Purpose | Responses |
|---|---|---|---|
| `POST` | `/v1/enrichment/jobs` | Enqueue enrichment for a contact/company. | 202 job |
| `GET` | `/v1/enrichment/jobs/{id}` | Job status + result. | 200 |
| `POST` | `/v1/enrichment/verify` | Verify an email/phone synchronously. | 200 Verification |
| `GET` | `/v1/enrichment/merge-candidates` | List pending merges. | 200 |
| `POST` | `/v1/enrichment/merge-candidates/{id}:resolve` | Merge or reject. | 200 |
| `POST` | `/v1/providers` | Register/configure a provider adapter. | 201 |

## 6. Core Workflows
1. Job queued -> waterfall: call providers by priority until fields filled or exhausted -> verify email/phone -> upsert to graph via Identity Resolution -> emit enrichment.entity.updated
2. Nightly staleness scan -> re-enqueue contacts older than N days

## 7. State Machine — `enrichment_job`
**States:** queued, running, partial, done, failed

**Transitions:** queued->running on worker pick; running->partial if some fields found; ->done when verified & upserted; ->failed on all providers exhausted

## 8. Events
**Publishes:** `enrichment.entity.updated`, `enrichment.verification.completed`, `enrichment.merge.detected`

**Subscribes:** `contact.created`, `signal.created (leadership/hiring -> enrich)`, `account.tiered (HOT -> enrich committee)`

## 9. Business Rules
- **ENR-001:** Waterfall stops at first source that satisfies required fields (cost control).
- **ENR-002:** Never overwrite a verified field with an unverified value (Identity Resolution guard).
- **ENR-003:** Email status 'invalid'/'risky' sets contact do_not_email until re-verified.
- **ENR-004:** Merge requires similarity>=0.9 OR a hard key match (LinkedIn URL / verified email).
- **ENR-005:** Enrichment credit spend per account capped by tier (HOT>WARM>COLD=0).

## 10. Permissions & RBAC
| Permission | Roles |
|---|---|
| `enrichment.request` | AE, Steward, system |
| `providers.manage` | Admin |
| `merge.resolve` | Steward, Admin |

## 11. Validations
- entity resolves in tenant
- provider priority unique per kind
- similarity in [0,1]

## 12. Error Scenarios
- 402 credit cap exceeded
- 409 merge conflict on verified fields
- 429 provider rate limit -> waterfall to next

## 13. Internal Integrations
Identity Resolution (05/graph), Contact & Account Engines, Signal Engine (triggers), Admin (credit quotas)

## 14. Testing Requirements
- Waterfall stops early when field satisfied
- Verified value not clobbered
- Credit cap enforced
- Merge on hard-key match

## 15. Acceptance Criteria
- [ ] HOT account committee auto-enriched within SLA
- [ ] Invalid emails auto-suppressed
- [ ] Duplicate contact from 2 providers merges to one

## 16. Edge Cases
- All providers fail -> job.failed, entity keeps prior data
- Catch-all domain -> status catch_all, score mid, flagged
- Conflicting titles across providers -> keep highest-reliability, log others

## 17. Implementation Checklist
- [ ] provider adapter interface + 2 stub adapters
- [ ] waterfall orchestrator
- [ ] email/phone verifier
- [ ] merge engine
- [ ] credit metering hook
- [ ] staleness scanner

## 18. Future Enhancements
- Deeper AI autonomy for this module as trust tier rises.
- Additional provider/channel adapters.
- Arabic-first UX refinements.
