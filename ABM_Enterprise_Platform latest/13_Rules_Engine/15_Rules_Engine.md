# Module 15 — Rules Engine

> **Domain folder:** `13_Rules_Engine`  
> **Replaces / equivalent to:** HubSpot workflow logic + custom IFTTT — the no-code IF/THEN decision core.

## 1. Purpose
The configurable no-code decision core every enterprise product revolves around: WHEN/IF (conditions over signals, scores, entities, events) THEN (actions across any engine). Non-developers compose rules like 'IF signal_score>80 AND funding>$50M AND CTO exists THEN create opportunity, assign owner, generate brief+email+LinkedIn sequence, start campaign, wait 3 days, check open...' — evaluated deterministically and auditable.

## 2. Scope
**In scope**
- Rule authoring (conditions + actions) no-code
- Condition operators over any entity/field/event/score
- Action catalog (create/assign/generate/enroll/notify/update/wait/branch)
- Rule evaluation engine (event-driven + scheduled)
- Rule versioning, priority, conflict resolution, dry-run/simulate
- Audit of every firing

**Out of scope**
- Long-running visual flows (Workflow Engine 16 — Rules can call Workflows)
- Channel execution internals
- Score math (Lead Scoring)

## 3. Personas
| Persona | Relationship to module |
|---|---|
| Ops/RevOps | Authors rules |
| Admin | Approves/prioritizes |
| System | Evaluates & fires |

## 4. Data Entities & Schema

### `rule`
A rule definition.

```
id UUID pk; tenant_id UUID; name text; trigger enum(event,schedule,manual); event_type text null; conditions jsonb; actions jsonb; priority int; status enum(draft,active,paused); version int; created_by; created_at
```

### `rule_firing`
An evaluation/execution record.

```
id UUID pk; rule_id UUID; subject_type enum; subject_id UUID; matched bool; actions_result jsonb; at timestamptz; dry_run bool
```

### `action_def`
Catalog of available actions.

```
code text pk; label text; params_schema jsonb; target_engine text; idempotent bool
```

### `condition_op`
Catalog of operators.

```
code text pk; label text; applies_to text[]
```

## 5. API Contracts
| Method | Path | Purpose | Responses |
|---|---|---|---|
| `POST` | `/v1/rules` | Create a rule (conditions+actions). | 201 |
| `POST` | `/v1/rules/{id}:simulate` | Dry-run over historical/sample data. | 200 |
| `POST` | `/v1/rules/{id}:activate` | Activate after validation. | 200 |
| `GET` | `/v1/rules/{id}/firings` | Firing history/audit. | 200 |
| `GET` | `/v1/rules/catalog` | Available conditions + actions. | 200 |

## 6. Core Workflows
1. Event arrives OR schedule ticks -> match rules by trigger -> evaluate conditions (short-circuit) -> if matched, execute action list in order (some actions call Workflow Engine for waits/branches) -> record firing + audit
2. Simulate: run against sample without side effects, show what would fire

## 7. State Machine — `rule`
**States:** draft, active, paused

**Transitions:** draft->active on validate; active<->paused

## 8. Events
**Publishes:** `rule.fired`, `rule.action.executed`, `rule.conflict.detected`

**Subscribes:** `* (subscribes to any platform event by trigger config)`

## 9. Business Rules
- **RUL-001:** Conditions are pure/deterministic; same inputs => same match.
- **RUL-002:** Actions execute in defined order; failure policy per action (halt/continue/retry).
- **RUL-003:** Rule priority resolves conflicts; two rules acting on same field => higher priority wins, logged.
- **RUL-004:** Every firing (incl. dry-run) is audited with matched conditions snapshot.
- **RUL-005:** Actions that send/outreach still pass consent/suppression/hold/autonomy gates (rules cannot bypass compliance).

## 10. Permissions & RBAC
| Permission | Roles |
|---|---|
| `rules.author` | Ops, Admin |
| `rules.activate` | Admin |
| `rules.read` | Manager, Ops, Admin |

## 11. Validations
- conditions reference valid fields/ops
- actions reference valid action_def + params schema
- no self-referential infinite fire (guard)

## 12. Error Scenarios
- 422 invalid condition/action schema
- 409 priority conflict unresolved
- 500 action failed (per failure policy)

## 13. Internal Integrations
Every engine (action targets), Workflow Engine (delegation), Lead Scoring, Signals, CRM (condition inputs), Audit

## 14. Testing Requirements
- Determinism
- Priority conflict resolution
- Compliance gate cannot be bypassed
- Simulate has no side effects
- Ordered action execution + failure policy

## 15. Acceptance Criteria
- [ ] Author the sample 'IF score>80 AND funding>50M AND CTO exists THEN...' rule and simulate it, then activate
- [ ] Conflicting rules resolve by priority with audit

## 16. Edge Cases
- Rule fires on entity later suppressed -> downstream send still blocked by gate
- Circular rule (A triggers B triggers A) -> loop guard
- Bulk event storm -> batched evaluation

## 17. Implementation Checklist
- [ ] condition + action catalogs
- [ ] evaluator (event + schedule)
- [ ] simulate mode
- [ ] priority/conflict resolver
- [ ] firing audit
- [ ] compliance-gate enforcement in actions

## 18. Future Enhancements
- Deeper AI autonomy for this module as trust tier rises.
- Additional provider/channel adapters.
- Arabic-first UX refinements.
