# Module 08 — Journey Builder Engine

> **Domain folder:** `07_Marketing_Automation`  
> **Replaces / equivalent to:** HubSpot Workflows + Customer.io journeys — visual multi-step, multi-channel orchestration.

## 1. Purpose
Visual, multi-channel journey orchestration: an account/contact enters a journey and moves through steps, conditions, triggers, actions, delays, goals and exit conditions across email, LinkedIn, WhatsApp, tasks and webhooks — the drip/sequence brain that replaces Smartlead/Instantly sequencing natively, with pause-on-reply and the account-centric rule enforced.

## 2. Scope
**In scope**
- Journey canvas: steps, branches, delays, waits
- Enrollment (from segment/list/trigger/rule)
- Conditions & decision splits
- Multi-channel actions (email/LinkedIn/WhatsApp/task/webhook/AI)
- Goals & exit conditions
- Pause-on-reply, account-centric pause
- Per-journey analytics

**Out of scope**
- Single blast campaigns (Marketing Engine)
- Channel delivery internals (Delivery/LinkedIn engines)
- Arbitrary internal automations (Workflow Engine 16)

## 3. Personas
| Persona | Relationship to module |
|---|---|
| Marketer | Designs nurture journeys |
| AE | Enrolls target accounts |
| System | Advances enrollments on schedule/events |

## 4. Data Entities & Schema

### `journey`
A journey definition.

```
id UUID pk; tenant_id UUID; name text; status enum(draft,active,paused,archived); entry enum(segment,trigger,manual,rule); definition jsonb; goal jsonb; exit jsonb; version int; created_at
```

### `journey_step`
A node in the journey.

```
id UUID pk; journey_id UUID; type enum(email,linkedin,whatsapp,task,delay,wait,condition,split,goal,webhook,ai,manual); config jsonb; position jsonb; next_ids uuid[]
```

### `enrollment`
A contact/account moving through a journey.

```
id UUID pk; journey_id UUID; contact_id UUID; account_id UUID; current_step_id UUID; status enum(active,waiting,completed,exited,paused); enrolled_at; next_run_at timestamptz; context jsonb
```

### `journey_event`
Step execution record.

```
id UUID pk; enrollment_id UUID; step_id UUID; result enum(done,skipped,failed,branched); at timestamptz; detail jsonb
```

## 5. API Contracts
| Method | Path | Purpose | Responses |
|---|---|---|---|
| `POST` | `/v1/journeys` | Create journey (canvas definition). | 201 |
| `POST` | `/v1/journeys/{id}:activate` | Validate + activate. | 200 |
| `POST` | `/v1/journeys/{id}:enroll` | Enroll contacts/accounts (or by segment). | 202 |
| `GET` | `/v1/journeys/{id}/analytics` | Funnel by step, conversion, goal rate. | 200 |
| `POST` | `/v1/enrollments/{id}:pause` | Pause an enrollment. | 200 |
| `GET` | `/v1/enrollments` | Query enrollments by status/step. | 200 |

## 6. Core Workflows
1. Enroll (consent+suppression+hold checks) -> scheduler advances enrollment at next_run_at -> step executes via channel engine -> branch on condition/event -> goal met => exit(success); reply => account-centric pause; exit condition => exit
2. Worker loop: due enrollments -> execute step -> compute next_run_at (delay + timezone/KSA calendar)

## 7. State Machine — `enrollment`
**States:** active, waiting, paused, completed, exited

**Transitions:** active<->waiting on delays; ->paused on hold/reply; ->completed on goal; ->exited on exit condition/suppression

## 8. Events
**Publishes:** `journey.enrolled`, `journey.step.executed`, `journey.goal.met`, `journey.exited`, `journey.step.email`, `journey.step.linkedin`

**Subscribes:** `email.reply.received`, `account.held`, `contact.consent.changed`, `segment.member.added`

## 9. Business Rules
- **JRN-001:** Enrollment blocked if do_not_contact / suppressed / account on hold — checked at enroll AND at each step.
- **JRN-002:** Any positive reply pauses the enrollment and triggers account-centric pause (all enrollments for the account).
- **JRN-003:** Max touches per contact per journey respects global cap (default 4 email).
- **JRN-004:** Step timing obeys timezone + KSA calendar (no Fri/Sat/Ramadan sends).
- **JRN-005:** A contact cannot be active in two journeys that target the same channel simultaneously (collision guard).

## 10. Permissions & RBAC
| Permission | Roles |
|---|---|
| `journey.manage` | Marketer, Admin |
| `journey.enroll` | AE, Marketer |
| `enrollment.pause` | AE, Marketer, Admin |

## 11. Validations
- journey graph acyclic except explicit loops with max-iter
- every path reaches goal/exit
- channel steps reference valid templates/sequences

## 12. Error Scenarios
- 422 unreachable step / no exit
- 409 channel collision
- 423 enrollment blocked by hold

## 13. Internal Integrations
Marketing Engine (email send), LinkedIn Engine (12), Email Delivery (11), Contact/Account Engines (gates), Analytics, Rules Engine (triggers)

## 14. Testing Requirements
- Pause-on-reply halts within one cycle
- Account-centric cascade
- KSA calendar delay math
- Collision guard across journeys
- Goal detection ends enrollment

## 15. Acceptance Criteria
- [ ] Design a 4-touch journey with a reply exit and run it end-to-end in a sandbox
- [ ] Reply pauses all account enrollments
- [ ] Timezone-correct step firing

## 16. Edge Cases
- Contact enrolled then unsubscribes -> exit immediately
- Journey edited while enrollments live -> versioning, existing keep old version
- Loop step with max-iter guard prevents infinite drip

## 17. Implementation Checklist
- [ ] journey + step + enrollment + event tables
- [ ] canvas validator (graph)
- [ ] scheduler/worker advancing enrollments
- [ ] channel dispatch adapters
- [ ] pause/cascade logic
- [ ] per-step analytics

## 18. Future Enhancements
- Deeper AI autonomy for this module as trust tier rises.
- Additional provider/channel adapters.
- Arabic-first UX refinements.
