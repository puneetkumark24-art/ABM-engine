# Module 16 — Workflow Engine (n8n-style)

> **Domain folder:** `11_Workflow_Engine`  
> **Replaces / equivalent to:** n8n / Zapier / Make — visual node-based automation inside the platform.

## 1. Purpose
A visual, node-based automation builder (like n8n but native): drag nodes — Email, LinkedIn, Webhook, CRM, Condition, Delay, Wait, Decision, Loop, Merge, Split, HTTP, Python, LLM, News/RSS, Slack, Teams, WhatsApp, SMS, Call, Meeting, Calendar, Approval, Manual Step, AI Step — wire them into durable, resumable workflows that power everything from onboarding to complex multi-branch plays.

## 2. Scope
**In scope**
- Visual DAG builder with 25+ node types
- Durable execution (resumable across waits/restarts)
- Triggers: event, schedule, webhook, manual
- Data mapping between nodes; expressions
- Error handling, retries, timeouts per node
- Sub-workflows, loops, merges, splits, approvals
- Run history, logs, replay

**Out of scope**
- Marketing-specific journeys (Journey Engine — though it may compile to workflows)
- No-code IF/THEN business rules (Rules Engine — Rules can invoke Workflows)

## 3. Personas
| Persona | Relationship to module |
|---|---|
| Ops/Automation builder | Designs workflows |
| Admin | Governs credentials/limits |
| System | Executes runs |

## 4. Data Entities & Schema

### `workflow`
A workflow definition (DAG).

```
id UUID pk; tenant_id UUID; name text; nodes jsonb; edges jsonb; triggers jsonb; status enum(draft,active,paused); version int; created_at
```

### `workflow_run`
An execution instance.

```
id UUID pk; workflow_id UUID; status enum(running,waiting,succeeded,failed,cancelled); trigger_ctx jsonb; started_at; finished_at; cursor jsonb
```

### `node_execution`
One node's execution in a run.

```
id UUID pk; run_id UUID; node_id text; status enum(pending,running,done,failed,skipped,waiting); input jsonb; output jsonb; attempts int; error text null; at timestamptz
```

### `credential`
Stored credential/connection for nodes.

```
id UUID pk; tenant_id UUID; kind text; name text; secret_ref text; scopes text[]
```

## 5. API Contracts
| Method | Path | Purpose | Responses |
|---|---|---|---|
| `POST` | `/v1/workflows` | Create workflow (nodes+edges). | 201 |
| `POST` | `/v1/workflows/{id}:run` | Trigger a run (manual/test). | 202 |
| `GET` | `/v1/workflows/runs/{id}` | Run status + node executions. | 200 |
| `POST` | `/v1/workflows/runs/{id}:resume` | Resume a waiting run (approval/callback). | 200 |
| `GET` | `/v1/workflows/{id}/history` | Run history + logs. | 200 |

## 6. Core Workflows
1. Trigger -> create run -> execute nodes along DAG -> Delay/Wait/Approval suspends run (durable) -> external callback/schedule resumes -> Condition/Decision branches, Loop iterates, Merge/Split combine -> terminal success/fail; retries per node policy
2. Sub-workflow node invokes another workflow synchronously/async

## 7. State Machine — `workflow_run`
**States:** running, waiting, succeeded, failed, cancelled

**Transitions:** running<->waiting on durable pauses; ->succeeded/failed terminal; ->cancelled manual

## 8. Events
**Publishes:** `workflow.run.started`, `workflow.run.finished`, `workflow.node.failed`, `workflow.approval.requested`

**Subscribes:** `rule.fired (invoke)`, `schedule.tick`, `webhook.received`, `approval.decided`

## 9. Business Rules
- **WFL-001:** Execution is durable — a run survives process restart and resumes from cursor.
- **WFL-002:** Each node has retry/timeout policy; exhausted retries -> failure path or run fail.
- **WFL-003:** Credentials are referenced by secret_ref, never inlined; scoped per tenant.
- **WFL-004:** Outreach nodes (email/linkedin/etc.) still pass all compliance gates.
- **WFL-005:** Loops require max-iteration bounds; unbounded loops rejected at validate.

## 10. Permissions & RBAC
| Permission | Roles |
|---|---|
| `workflow.build` | Ops, Admin |
| `workflow.run` | Ops, Admin, system |
| `credential.manage` | Admin |

## 11. Validations
- DAG valid (no illegal cycles; loops bounded)
- node configs schema-valid
- credentials exist & scoped

## 12. Error Scenarios
- 422 invalid DAG
- 401 missing credential scope
- 408 node timeout -> failure policy

## 13. Internal Integrations
All engines via nodes, Rules Engine (invocation), Integration Layer (HTTP/3rd-party nodes), Admin (credentials), Notification (Slack/Teams nodes)

## 14. Testing Requirements
- Durability: kill worker mid-run, resume correctly
- Retry/timeout policy
- Approval suspend/resume
- Bounded loop
- Compliance gate in outreach nodes

## 15. Acceptance Criteria
- [ ] Build a workflow with Delay + Approval + Condition + Email that survives a restart and completes
- [ ] Failed node follows failure path

## 16. Edge Cases
- Approval never answered -> timeout -> escalation path
- External HTTP node flaky -> retries then failure branch
- Large fan-out (Split 1000) -> throttled batching

## 17. Implementation Checklist
- [ ] DAG model + validator
- [ ] durable executor + cursor persistence
- [ ] 25+ node implementations
- [ ] retry/timeout/error policy
- [ ] credential vault ref
- [ ] run history/logs/replay

## 18. Future Enhancements
- Deeper AI autonomy for this module as trust tier rises.
- Additional provider/channel adapters.
- Arabic-first UX refinements.
