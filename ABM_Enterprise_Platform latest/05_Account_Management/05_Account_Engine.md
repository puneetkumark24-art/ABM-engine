# Module 05 — Account Engine

> **Domain folder:** `05_Account_Management`  
> **Replaces / equivalent to:** HubSpot Companies + 6sense account model — the account system of record & tiering.

## 1. Purpose
System of record for target organizations and their structure (parents, subsidiaries, vendors, tech stack), the account scoring inputs, tiering (HOT/WARM/COLD), and the account-centric orchestration rule that one reply pauses the whole account.

## 2. Scope
**In scope**
- Account CRUD & hierarchy (parent/subsidiary)
- Tech stack & vendor mapping on the account
- Account tier assignment & daily budget
- Account-level pause/hold state
- Product-fit mapping (account x product)

**Out of scope**
- Score computation math (Lead Scoring Engine, 18) — Account Engine stores & consumes
- People (Contact Engine)
- Deals (Pipeline/CRM)

## 3. Personas
| Persona | Relationship to module |
|---|---|
| AE | Works target accounts |
| Manager | Allocates tiers/territories |
| System | Tiers & budgets |

## 4. Data Entities & Schema

### `account`
Target organization.

```
id UUID pk; tenant_id UUID; name text; type enum(bank,fintech,subsidiary,vendor,regulator,consulting); parent_id UUID null; segment text; sub_segment text; tier enum(hot,warm,cold); digital_maturity enum(low,med,high); core_banking text; open_banking enum(none,v1,v2); score numeric(5,2); status enum(active,paused,excluded); employees int; website text; country text; created_at; updated_at
```

### `account_tech`
Technology/vendor used by account.

```
id UUID pk; account_id UUID; category enum(core,los,lms,payments,fraud,aml,kyc,cloud,api_gw,crm); vendor text; confidence numeric(4,3); source text; entrenchment numeric(4,3)
```

### `product_fit`
Account x Decimal product fit.

```
id UUID pk; account_id UUID; product_id UUID; fit_score numeric(4,3); pitch_angle text
```

### `account_hold`
Pause/hold record (account-centric rule).

```
id UUID pk; account_id UUID; reason enum(reply,meeting,manual,compliance); started_at; expires_at null; created_by
```

## 5. API Contracts
| Method | Path | Purpose | Responses |
|---|---|---|---|
| `GET` | `/v1/accounts` | Filter by tier/segment/score/status. | 200 paged |
| `POST` | `/v1/accounts` | Create account. | 201 |
| `PATCH` | `/v1/accounts/{id}` | Update (tier/status guarded). | 200 |
| `GET` | `/v1/accounts/{id}/graph` | Account + subsidiaries + vendors + committee. | 200 |
| `POST` | `/v1/accounts/{id}:hold` | Pause the account (reason). | 200 |
| `POST` | `/v1/accounts/{id}:release` | Release a hold. | 200 |

## 6. Core Workflows
1. Score change -> re-tier (HOT>=75/WARM>=50/COLD) -> set daily budget -> HOT triggers committee enrichment
2. Positive reply anywhere -> account_hold(reason=reply) -> all journeys for account pause -> notify owner

## 7. State Machine — `account.status`
**States:** active, paused, excluded

**Transitions:** active->paused on hold; paused->active on release/expiry; ->excluded manual/compliance

## 8. Events
**Publishes:** `account.created`, `account.tiered`, `account.held`, `account.released`

**Subscribes:** `score.updated`, `email.reply.received`, `meeting.booked`, `enrichment.entity.updated`

## 9. Business Rules
- **ACC-001:** Account-centric pause — a hold suspends every active journey/campaign touch for the account.
- **ACC-002:** Max 5 new accounts activated per day per tenant (MVP budget).
- **ACC-003:** Tier thresholds HOT>=75, WARM>=50, else COLD; recomputed on score change.
- **ACC-004:** Enrichment credit only for HOT (full) and WARM (limited); COLD=0.
- **ACC-005:** entrenchment on incumbent vendor lowers Effective-Opportunity (Scoring modifier).

## 10. Permissions & RBAC
| Permission | Roles |
|---|---|
| `accounts.read` | All |
| `accounts.write` | AE, Manager, Admin |
| `accounts.tier.override` | Manager, Admin |
| `accounts.exclude` | Admin |

## 11. Validations
- parent_id != self; no cycles
- tier in enum
- score 0..100

## 12. Error Scenarios
- 409 hierarchy cycle
- 422 invalid tier override without reason
- 423 account locked (held) for outreach

## 13. Internal Integrations
Contact Engine, Lead Scoring, Journey/Campaign (pause gate), Intelligence (narrative), Pipeline

## 14. Testing Requirements
- Hold cascades to all journeys
- Re-tier on score cross
- Cycle prevention in hierarchy
- Daily activation cap

## 15. Acceptance Criteria
- [ ] Reply pauses entire account within seconds
- [ ] HOT auto-enriches committee
- [ ] Subsidiary rolls up to parent in graph view

## 16. Edge Cases
- Subsidiary hot, parent cold -> independent tiers, shared relationships
- Merge two accounts (M&A) -> hierarchy + dedupe
- Excluded account never re-enters via import

## 17. Implementation Checklist
- [ ] account + account_tech + product_fit + hold tables
- [ ] tiering service
- [ ] hold/cascade orchestrator
- [ ] hierarchy graph query
- [ ] budget counter

## 18. Future Enhancements
- Deeper AI autonomy for this module as trust tier rises.
- Additional provider/channel adapters.
- Arabic-first UX refinements.
