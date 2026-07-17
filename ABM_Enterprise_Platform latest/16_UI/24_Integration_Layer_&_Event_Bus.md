# Module 24 — Integration Layer & Event Bus

> **Domain folder:** `16_UI`  
> **Replaces / equivalent to:** Internal Kafka/Redis event bus + connector framework (optional external bridges).

## 1. Purpose
The nervous system: the internal event bus that lets every engine publish/subscribe asynchronously, plus a connector framework for optional external bridges (Slack, Teams, WhatsApp, calendar, model providers) — the plumbing that makes 26 modules one platform while keeping them decoupled.

## 2. Scope
**In scope**
- Internal event bus (publish/subscribe, durable, ordered per key)
- Event schema registry + versioning
- Connector framework for optional externals (Slack/Teams/WhatsApp/Calendar/LLM providers)
- Retry, dead-letter, replay
- Idempotency & exactly-once-ish delivery semantics

**Out of scope**
- Business logic
- External API exposure (API Gateway)
- Credential UI (Admin)

## 3. Personas
| Persona | Relationship to module |
|---|---|
| System | Every engine is a producer/consumer |
| Ops | Monitors bus health, replays DLQ |
| Admin | Manages connectors |

## 4. Data Entities & Schema

### `event`
A platform event.

```
id UUID pk; tenant_id UUID; type text; key text; payload jsonb; schema_version int; occurred_at timestamptz; published_at timestamptz
```

### `subscription`
A consumer subscription.

```
id UUID pk; consumer text; event_types text[]; endpoint text; status enum(active,paused); dlq_count int
```

### `dead_letter`
Failed delivery.

```
id UUID pk; event_id UUID; subscription_id UUID; error text; attempts int; at timestamptz
```

### `connector`
External bridge config.

```
id UUID pk; tenant_id UUID; kind enum(slack,teams,whatsapp,calendar,llm,smtp,other); config jsonb; status enum(connected,error); scopes text[]
```

## 5. API Contracts
| Method | Path | Purpose | Responses |
|---|---|---|---|
| `POST` | `/v1/events:publish` | Publish an event (internal). | 202 |
| `POST` | `/v1/subscriptions` | Register a subscription. | 201 |
| `GET` | `/v1/events/dlq` | List dead letters. | 200 |
| `POST` | `/v1/events/dlq/{id}:replay` | Replay a dead letter. | 200 |
| `POST` | `/v1/connectors` | Configure an external connector. | 201 |

## 6. Core Workflows
1. Producer publishes -> bus persists + fans out to subscriptions -> consumer acks; failure -> retry w/ backoff -> DLQ after N -> ops replay
2. Connector: outbound (Slack message) via connector adapter; inbound (calendar event) normalized to platform event

## 7. State Machine — `event delivery`
**States:** published, delivered, retrying, dead_lettered

**Transitions:** published->delivered on ack; ->retrying on failure; ->dead_lettered after N

## 8. Events
**Publishes:** `bus.dlq.added`, `connector.status.changed`

**Subscribes:** `* (transport for all)`

## 9. Business Rules
- **INT-BUS-001:** Events are schema-registered & versioned; consumers tolerate additive changes.
- **INT-BUS-002:** Delivery is at-least-once; consumers must be idempotent (event id dedup).
- **INT-BUS-003:** Ordering guaranteed per key (e.g. per account_id), not globally.
- **INT-BUS-004:** Failed deliveries retry with backoff then dead-letter; never silently dropped.
- **INT-BUS-005:** External connectors are optional bridges, never load-bearing for core flows.

## 10. Permissions & RBAC
| Permission | Roles |
|---|---|
| `bus.publish` | system |
| `bus.ops` | Ops, Admin |
| `connectors.manage` | Admin |

## 11. Validations
- event matches registered schema
- subscription endpoints reachable
- connector scopes valid

## 12. Error Scenarios
- 422 schema mismatch
- 503 consumer down -> retry/DLQ
- 409 duplicate event id (idempotent)

## 13. Internal Integrations
Every engine, Admin (connectors/credentials), Notification (Slack/Teams/WhatsApp adapters), AI Engine (LLM connector)

## 14. Testing Requirements
- At-least-once + idempotent dedup
- Per-key ordering
- DLQ + replay
- Schema-version tolerance
- Connector failure isolation

## 15. Acceptance Criteria
- [ ] Publish account.tiered and confirm all subscribers react idempotently
- [ ] Kill a consumer, events DLQ and replay cleanly

## 16. Edge Cases
- Poison message -> DLQ not infinite retry
- Schema v2 additive -> v1 consumers unaffected
- Connector outage -> core flows continue

## 17. Implementation Checklist
- [ ] event bus (Redis streams/Kafka)
- [ ] schema registry
- [ ] subscription manager
- [ ] retry + DLQ + replay
- [ ] connector framework + adapters
- [ ] idempotency store

## 18. Future Enhancements
- Deeper AI autonomy for this module as trust tier rises.
- Additional provider/channel adapters.
- Arabic-first UX refinements.
