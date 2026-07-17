# Event Architecture & Master Catalog

The async event bus (Module 24) is the platform's nervous system. **At-least-once** delivery, **per-key ordering** (e.g. per `account_id`), **idempotent** consumers (dedup by event id), a **schema registry** with additive versioning, and **retry -> DLQ -> replay**. Engines are decoupled producers/consumers.

## Representative event catalog
| Event | Producer | Key consumers |
|---|---|---|
| `signal.created` | Signal Engine | Intelligence, Scoring, Account, Enrichment |
| `signal.cluster.promoted` | Signal Engine | Intelligence |
| `intelligence.record.created` | Intelligence | Scoring, CRM, Copilot |
| `intelligence.nba.created` | Intelligence | CRM, Notification, Copilot |
| `enrichment.entity.updated` | Enrichment | Contact, Account, CRM, Scoring |
| `contact.consent.changed` | Contact | Marketing, Journey, Delivery |
| `account.tiered` | Account | Enrichment, Journey, Notification |
| `account.held` | Account | Journey, LinkedIn, Marketing (pause cascade) |
| `score.updated / score.threshold.crossed` | Scoring | Account, Intelligence, Analytics, Notification |
| `deal.stage.changed` | CRM/Pipeline | Pipeline, Attribution, Analytics, Marketing (transactional) |
| `email.campaign.sent` | Marketing | Delivery, Analytics |
| `email.event.opened/clicked/bounced/complained` | Delivery | Marketing, Contact, Scoring, Attribution, Analytics |
| `email.reply.received` | Delivery | Account (pause), Journey (pause), Notification |
| `journey.enrolled / step.executed / goal.met / exited` | Journey | Analytics, Campaign, Attribution |
| `linkedin.reply.received / seat.cooldown / circuit_breaker.tripped` | LinkedIn | Account, Journey, Notification |
| `form.submitted / consent.captured` | Landing/Forms | Contact, Journey, Analytics |
| `rule.fired` | Rules | Audit, target engines |
| `workflow.run.finished / approval.requested` | Workflow | Notification, Analytics |
| `meeting.booked` | Calendar/CRM | Account, Pipeline, Scoring, Attribution, Notification |
| `quota.exhausted` | Admin | Notification, calling engine (block) |

## Delivery guarantees
- At-least-once; consumers idempotent via event-id dedup store.
- Ordering guaranteed per partition key, not globally.
- Failed deliveries retry with backoff, then dead-letter; ops can replay.
- Schema changes are additive; consumers tolerate unknown new fields.
