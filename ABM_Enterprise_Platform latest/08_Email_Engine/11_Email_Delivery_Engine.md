# Module 11 — Email Delivery Engine

> **Domain folder:** `08_Email_Engine`  
> **Replaces / equivalent to:** Mandrill/SendGrid MTA + Postfix — the actual send + event pipeline.

## 1. Purpose
The low-level send-and-track layer: accept a rendered message, deliver it via MTA/provider with IP-pool + reputation management, and capture the full event pipeline (delivered/open/click/bounce/complaint) that everything upstream depends on — the native replacement for Mailchimp's real moat.

## 2. Scope
**In scope**
- Send API (single + batch) with queueing & rate control
- Provider/MTA adapters (SMTP, Mandrill-style API) + failover
- Open pixel, click redirect, bounce/complaint webhooks
- Feedback-loop registration, suppression sync
- IP pool & warmup enforcement, throttling
- Event normalization -> platform event bus

**Out of scope**
- Audience/template/compose (Marketing Engine)
- Journey logic (Journey Engine)
- Deliverability domain config UI (Marketing/Admin)

## 3. Personas
| Persona | Relationship to module |
|---|---|
| System | Primary caller |
| Deliverability admin | Monitors reputation/queues |

## 4. Data Entities & Schema

### `send_request`
A queued send.

```
id UUID pk; tenant_id UUID; message_id UUID; to_email citext; from_domain_id UUID; ip_pool text; rendered_html text; headers jsonb; status enum(queued,sending,sent,failed,throttled); attempts int; scheduled_at; sent_at
```

### `delivery_event`
Normalized event.

```
id UUID pk; message_id UUID; type enum(delivered,open,click,bounce,complaint,deferral,unsub); meta jsonb; occurred_at timestamptz; provider text
```

### `ip_pool`
Sending IP pool.

```
id UUID pk; tenant_id UUID; name text; ips text[]; warmup_stage int; daily_cap int; reputation numeric(4,3)
```

### `provider_route`
MTA/provider config + failover order.

```
id UUID pk; tenant_id UUID; name text; kind enum(smtp,api); priority int; config jsonb; healthy bool
```

## 5. API Contracts
| Method | Path | Purpose | Responses |
|---|---|---|---|
| `POST` | `/v1/delivery/send` | Enqueue a rendered message. | 202 |
| `POST` | `/v1/delivery/send:batch` | Batch enqueue. | 202 |
| `POST` | `/v1/delivery/webhooks/{provider}` | Ingest provider events (public HTTPS). | 200 |
| `GET` | `/v1/delivery/messages/{id}/events` | Event trail for a message. | 200 |
| `GET` | `/v1/delivery/health` | Queue depth, provider health, reputation. | 200 |

## 6. Core Workflows
1. send enqueued -> throttle/warmup check -> MTA send via highest-priority healthy route (failover) -> provider webhooks -> normalize to delivery_event -> emit email.event.* -> update message + suppression + engagement
2. Bounce/complaint -> suppression + negative engagement + reputation adjust

## 7. State Machine — `send_request`
**States:** queued, throttled, sending, sent, failed

**Transitions:** queued->throttled on cap; ->sending on slot; ->sent on accept; ->failed after retries/failover exhausted

## 8. Events
**Publishes:** `email.event.delivered`, `email.event.opened`, `email.event.clicked`, `email.event.bounced`, `email.event.complained`, `email.reply.received`

**Subscribes:** `email.campaign.sent (enqueue)`, `journey.step.email`

## 9. Business Rules
- **DEL-001:** Requires a public HTTPS webhook endpoint to receive provider events (deployment prerequisite).
- **DEL-002:** Warmup + daily cap per IP pool enforced; overflow queues to next window.
- **DEL-003:** Hard bounce/complaint => immediate suppression sync to Marketing Engine.
- **DEL-004:** Provider failover on 5xx/timeout to next healthy route; idempotent by message_id.
- **DEL-005:** All events normalized to one schema regardless of provider.

## 10. Permissions & RBAC
| Permission | Roles |
|---|---|
| `delivery.send` | system, Marketer(indirect) |
| `delivery.ops` | Deliverability Admin, Admin |

## 11. Validations
- from_domain authenticated
- to_email valid & not suppressed
- ip_pool within cap

## 12. Error Scenarios
- 503 no healthy route
- 429 throttled
- 409 duplicate message_id (idempotent no-op)

## 13. Internal Integrations
Marketing Engine (suppression/engagement), Contact Engagement rollup, Lead Scoring (reachability), Analytics, Admin (domains/IPs)

## 14. Testing Requirements
- Idempotent webhook ingestion
- Failover on primary down
- Warmup cap enforcement
- Event normalization across 2 providers
- Open/click attribution to message

## 15. Acceptance Criteria
- [ ] Send 10k with tracking; opens/clicks/bounces captured & normalized
- [ ] Primary provider outage fails over transparently
- [ ] Complaint suppresses instantly

## 16. Edge Cases
- Duplicate provider event -> dedup by (message,type,ts)
- Webhook replay attack -> signature verification
- Recipient MX greylists -> deferral + retry with backoff

## 17. Implementation Checklist
- [ ] send queue + workers
- [ ] MTA/API adapters + failover
- [ ] pixel + redirect + webhook receivers (public HTTPS)
- [ ] event normalizer
- [ ] warmup/throttle controller
- [ ] reputation tracker

## 18. Future Enhancements
- Deeper AI autonomy for this module as trust tier rises.
- Additional provider/channel adapters.
- Arabic-first UX refinements.
