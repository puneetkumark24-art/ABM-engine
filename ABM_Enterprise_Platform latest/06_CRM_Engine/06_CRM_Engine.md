# Module 06 — CRM Engine (HubSpot Replica)

> **Domain folder:** `06_CRM_Engine`  
> **Replaces / equivalent to:** HubSpot CRM in full — accounts, contacts, deals, activities, custom objects, properties, timelines, workflows.

## 1. Purpose
A full native CRM: the relational spine tying accounts, contacts, companies, buying committees, relationship graph, deals, pipelines, activities, tasks, notes, custom objects and properties into one auditable system of record with AI timeline, engagement scoring, next-best-action, forecasting, duplicate/merge, search, views, lists and segments — reproducing HubSpot CRM capability natively.

## 2. Scope
**In scope**
- Objects: Account, Contact, Company, Deal, Opportunity, Activity, Task, Note, Meeting, Call, Email, Custom Object
- Buying Committee & Relationship Graph
- Properties framework (custom fields) + Lead Status + Lifecycle
- Pipelines & stages (thin ref to Pipeline Engine 19)
- Owners/Teams/Permissions, Views/Lists/Segments/Tags
- AI Timeline, Engagement Score, Next-Best-Action surfacing, Forecasting hooks
- Duplicate detection, Merge engine, Search, Audit logs

**Out of scope**
- Score math (18)
- Marketing sends (07)
- Journey logic (08)

## 3. Personas
| Persona | Relationship to module |
|---|---|
| AE | Lives in the CRM daily |
| Manager | Forecasts, reviews pipeline |
| Ops/Admin | Defines objects, properties, pipelines |
| System | Writes activities & NBAs to timeline |

## 4. Data Entities & Schema

### `crm_object`
Polymorphic object registry (built-in + custom).

```
id UUID pk; tenant_id UUID; object_type text; is_custom bool; label text; schema jsonb; created_at
```

### `property`
Custom/standard field definition.

```
id UUID pk; tenant_id UUID; object_type text; key text; label text; data_type enum(text,number,date,enum,bool,ref,calc); options jsonb; required bool; unique bool; group text
```

### `deal`
Sales deal/opportunity.

```
id UUID pk; tenant_id UUID; account_id UUID; name text; pipeline_id UUID; stage_id UUID; amount numeric; currency text; probability numeric(4,3); close_date date; owner_id UUID; status enum(open,won,lost); lost_reason text; created_at; updated_at
```

### `activity`
Any interaction (universal activity).

```
id UUID pk; tenant_id UUID; type enum(email,call,meeting,linkedin,whatsapp,note,task,demo,rfp,poc); subject_type enum(account,contact,deal); subject_id UUID; owner_id UUID; occurred_at timestamptz; outcome text; body jsonb; source enum(user,system)
```

### `committee_member`
Buying committee role mapping.

```
id UUID pk; account_id UUID; contact_id UUID; product_id UUID; role enum(decision_maker,influencer,champion,blocker,approver,user); influence numeric(4,3); engagement numeric(4,3)
```

### `relationship`
Graph edge (org/person/vendor/tech).

```
id UUID pk; from_type enum; from_id UUID; to_type enum; to_id UUID; rel_type text; strength numeric(4,3); confidence numeric(4,3); source text; start_date date; end_date date null
```

### `view`
Saved filter/segment/list.

```
id UUID pk; tenant_id UUID; object_type text; name text; kind enum(view,list,segment); definition jsonb; dynamic bool; owner_id UUID
```

### `crm_task`
Task.

```
id UUID pk; tenant_id UUID; title text; due_at timestamptz; assignee_id UUID; related_type enum; related_id UUID; status enum(open,done,skipped); priority enum(low,med,high)
```

### `audit_log`
Change history.

```
id UUID pk; tenant_id UUID; actor_id UUID; object_type text; object_id UUID; action text; before jsonb; after jsonb; at timestamptz
```

## 5. API Contracts
| Method | Path | Purpose | Responses |
|---|---|---|---|
| `GET` | `/v1/crm/{object}/{id}` | Fetch any object with expandable associations. | 200 |
| `POST` | `/v1/crm/{object}` | Create record (validates against properties). | 201 |
| `PATCH` | `/v1/crm/{object}/{id}` | Update (audited). | 200 |
| `POST` | `/v1/crm/properties` | Define a custom property. | 201 |
| `POST` | `/v1/crm/objects` | Define a custom object. | 201 |
| `GET` | `/v1/crm/{object}/{id}/timeline` | Unified AI timeline. | 200 |
| `POST` | `/v1/crm/deals/{id}:move` | Move deal stage (guarded transitions). | 200 |
| `GET` | `/v1/crm/duplicates` | List duplicate candidates. | 200 |
| `POST` | `/v1/crm/{object}:merge` | Merge two records. | 200 |
| `POST` | `/v1/crm/views` | Create view/list/segment (static or dynamic). | 201 |
| `GET` | `/v1/crm/search` | Cross-object search (Search Engine backed). | 200 |

## 6. Core Workflows
1. Record CRUD -> property validation -> audit_log -> emit crm.{object}.changed -> Search index update + timeline entry
2. Deal stage move -> guarded transition -> probability recalced -> forecast refresh -> activity logged
3. Duplicate detected -> surfaced -> merge -> associations re-pointed, loser soft-deleted, audit

## 7. State Machine — `deal.status/stage`
**States:** open(stage 1..n), won, lost

**Transitions:** stage transitions constrained by pipeline definition; open->won/lost terminal; reopen creates new deal or audited revert

## 8. Events
**Publishes:** `crm.contact.changed`, `crm.deal.changed`, `deal.stage.changed`, `crm.merged`, `crm.task.completed`

**Subscribes:** `intelligence.nba.created`, `email.event.*`, `meeting.booked`, `score.updated`, `enrichment.entity.updated`

## 9. Business Rules
- **CRM-001:** Every mutation writes an audit_log with before/after.
- **CRM-002:** Custom property keys are immutable once data exists; type changes require migration.
- **CRM-003:** Deal stage transitions must follow the pipeline's allowed graph; illegal moves rejected.
- **CRM-004:** Merge re-points all associations and never deletes activity history.
- **CRM-005:** NBA and AI-timeline entries are system-authored and read-only to users.
- **CRM-006:** Dynamic segments re-evaluate on member field changes; static lists do not.

## 10. Permissions & RBAC
| Permission | Roles |
|---|---|
| `crm.read` | All (row-level by owner/team) |
| `crm.write` | AE, Manager, Admin |
| `crm.schema.manage` | Admin/Ops |
| `crm.merge` | Manager, Admin |
| `crm.delete` | Admin |

## 11. Validations
- property schema enforced on write
- unique properties enforced
- stage belongs to deal's pipeline

## 12. Error Scenarios
- 422 property validation
- 409 illegal stage transition
- 409 merge across tenants
- 403 row-level denial

## 13. Internal Integrations
Pipeline (19), Lead Scoring (18), Marketing/Journey (enrollment source lists), Analytics/Attribution, Search Engine, Notification

## 14. Testing Requirements
- Custom object + property lifecycle
- Illegal stage move rejected
- Merge preserves history
- Row-level permission matrix
- Timeline ordering across sources

## 15. Acceptance Criteria
- [ ] Create a custom object with fields and CRUD it via API/UI
- [ ] Deal forecast updates on stage move
- [ ] Duplicate contacts merge cleanly with full history
- [ ] Dynamic segment updates as fields change

## 16. Edge Cases
- Property type change with existing data -> guided migration, not silent
- Circular association (A parent of B parent of A) rejected
- Merging owner-conflicting records -> ownership rule applied + audit
- 10M activities on one account -> timeline paginated & indexed

## 17. Implementation Checklist
- [ ] polymorphic object + property framework
- [ ] deal/activity/task/note/meeting tables
- [ ] committee + relationship graph tables
- [ ] views/lists/segments engine
- [ ] duplicate + merge engine
- [ ] audit log
- [ ] search integration
- [ ] forecasting hook
- [ ] AI timeline assembler

## 18. Future Enhancements
- Deeper AI autonomy for this module as trust tier rises.
- Additional provider/channel adapters.
- Arabic-first UX refinements.
