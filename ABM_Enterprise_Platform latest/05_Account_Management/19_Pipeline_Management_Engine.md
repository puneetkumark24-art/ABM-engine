# Module 19 — Pipeline Management Engine

> **Domain folder:** `05_Account_Management`  
> **Replaces / equivalent to:** HubSpot deal pipelines + forecasting.

## 1. Purpose
Deal pipeline configuration and progression: multiple pipelines, custom stages with entry/exit criteria and probabilities, weighted forecasting, gap-to-quota and pipeline-health analytics — the revenue spine the CRM deals move along.

## 2. Scope
**In scope**
- Pipeline & stage config (per product/segment)
- Stage entry/exit criteria & default probabilities
- Weighted forecast (commit/likely/worst)
- Pipeline health: stalled deals, single-threaded, hygiene
- Quota & gap analysis

**Out of scope**
- Deal object CRUD (CRM Engine holds deals; Pipeline defines structure)
- Score math (Lead Scoring)
- Reporting UI (Reporting Engine)

## 3. Personas
| Persona | Relationship to module |
|---|---|
| Manager | Configures pipelines, forecasts |
| AE | Moves deals |
| Exec | Reviews forecast |

## 4. Data Entities & Schema

### `pipeline`
A pipeline.

```
id UUID pk; tenant_id UUID; name text; product_id UUID null; stages jsonb; default bool; created_at
```

### `stage`
A stage.

```
id UUID pk; pipeline_id UUID; name text; order int; probability numeric(4,3); entry_criteria jsonb; exit_criteria jsonb; rotting_days int
```

### `forecast`
A forecast snapshot.

```
id UUID pk; tenant_id UUID; period text; commit numeric; likely numeric; worst numeric; weighted numeric; quota numeric; gap numeric; computed_at
```

### `pipeline_health`
Health flags per deal.

```
deal_id UUID; flags text[]; stalled_days int; single_threaded bool; updated_at
```

## 5. API Contracts
| Method | Path | Purpose | Responses |
|---|---|---|---|
| `POST` | `/v1/pipelines` | Create pipeline + stages. | 201 |
| `GET` | `/v1/pipelines/{id}/forecast` | Weighted forecast + gap. | 200 |
| `GET` | `/v1/pipelines/{id}/health` | Stalled/single-threaded/hygiene flags. | 200 |
| `PATCH` | `/v1/pipelines/{id}/stages` | Edit stages/criteria/probabilities. | 200 |

## 6. Core Workflows
1. Configure pipeline+stages -> CRM deals reference stage -> stage move validated vs entry/exit criteria -> probability & forecast recompute -> health scan flags stalled/single-threaded -> notify
2. Forecast recompute nightly + on stage moves

## 7. State Machine — `deal (via pipeline)`
**States:** stage 1..n, won, lost

**Transitions:** transitions constrained by entry/exit criteria; rotting_days triggers stalled flag

## 8. Events
**Publishes:** `forecast.updated`, `pipeline.deal.stalled`, `pipeline.health.flagged`

**Subscribes:** `deal.stage.changed`, `deal.created`, `activity.logged (single-thread check)`

## 9. Business Rules
- **PIP-001:** Stage moves must satisfy entry criteria; exits require exit criteria or reason.
- **PIP-002:** Weighted forecast = sum(amount*stage_probability) for open deals.
- **PIP-003:** Deal idle > stage.rotting_days => stalled flag + NBA.
- **PIP-004:** Single-threaded deal (one contact) => risk flag.
- **PIP-005:** Close-date in past on open deal => hygiene flag.

## 10. Permissions & RBAC
| Permission | Roles |
|---|---|
| `pipeline.manage` | Manager, Admin |
| `pipeline.read` | All |
| `forecast.read` | Manager, Exec, Admin |

## 11. Validations
- stage order unique
- probabilities in [0,1]
- criteria schema valid

## 12. Error Scenarios
- 409 illegal stage transition
- 422 invalid criteria
- 404 pipeline

## 13. Internal Integrations
CRM (deals), Lead Scoring, Intelligence (NBA on stalled), Analytics/Reporting, Notification

## 14. Testing Requirements
- Entry/exit criteria enforcement
- Weighted forecast math
- Stalled detection
- Single-thread flag
- Hygiene flags

## 15. Acceptance Criteria
- [ ] Configure a product pipeline; forecast reflects weighted open deals; stalled deals flagged with NBA
- [ ] Illegal stage move blocked

## 16. Edge Cases
- Deal on custom pipeline product mismatch -> validation
- Backdated close date -> hygiene flag not silent
- Multi-currency deals -> normalized in forecast

## 17. Implementation Checklist
- [ ] pipeline + stage config
- [ ] transition validator
- [ ] forecast computer
- [ ] health scanner
- [ ] quota/gap calc

## 18. Future Enhancements
- Deeper AI autonomy for this module as trust tier rises.
- Additional provider/channel adapters.
- Arabic-first UX refinements.
