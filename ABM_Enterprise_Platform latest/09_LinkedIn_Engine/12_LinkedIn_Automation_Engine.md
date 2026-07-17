# Module 12 — LinkedIn Automation Engine

> **Domain folder:** `09_LinkedIn_Engine`  
> **Replaces / equivalent to:** Smartlead/Expandi/Dux-Soup — LinkedIn touches, gated by ban-risk controls.

## 1. Purpose
Native, safety-first LinkedIn outreach: connection requests, messages, InMail, profile views and post engagement as journey/sequence steps — behind a strict ban-risk circuit breaker, human-like pacing, and per-seat daily limits. Deliberately the last capability activated.

## 2. Scope
**In scope**
- LinkedIn action steps: connect, message, InMail, view, follow, like
- Per-seat daily limits + human-like randomized pacing
- Ban-risk circuit breaker + anomaly halt
- Seat/session management (per-user auth)
- Reply detection -> pause-on-reply

**Out of scope**
- Scraping/enrichment (Enrichment Engine)
- Content generation (AI Engine)
- Signal capture from LinkedIn (Signal Engine SIG-EXEC)

## 3. Personas
| Persona | Relationship to module |
|---|---|
| AE | Owns a LinkedIn seat, runs sequences |
| Admin | Sets limits & risk policy |
| System | Executes paced actions |

## 4. Data Entities & Schema

### `li_seat`
A connected LinkedIn account/seat.

```
id UUID pk; tenant_id UUID; user_id UUID; status enum(active,cooldown,disconnected,banned_suspected); daily_limits jsonb; health numeric(4,3); last_action_at
```

### `li_action`
A queued/executed action.

```
id UUID pk; seat_id UUID; contact_id UUID; type enum(connect,message,inmail,view,follow,like); status enum(queued,sent,accepted,replied,failed,skipped); scheduled_at; executed_at; detail jsonb
```

### `li_sequence`
A LinkedIn-only sequence (or journey steps).

```
id UUID pk; tenant_id UUID; name text; steps jsonb; pacing jsonb
```

## 5. API Contracts
| Method | Path | Purpose | Responses |
|---|---|---|---|
| `POST` | `/v1/linkedin/seats` | Connect/register a seat. | 201 |
| `POST` | `/v1/linkedin/actions` | Queue an action (paced). | 202 |
| `GET` | `/v1/linkedin/seats/{id}/health` | Seat health + limits + risk. | 200 |
| `POST` | `/v1/linkedin/circuit-breaker:status` | Query/trip circuit breaker. | 200 |

## 6. Core Workflows
1. Action queued -> circuit breaker healthy? -> within seat daily limit & pacing window? -> execute with human-like delay -> detect accept/reply -> reply => pause-on-reply + account-centric pause
2. Anomaly (spike in failures/captcha) -> trip breaker -> seat cooldown -> notify

## 7. State Machine — `li_seat`
**States:** active, cooldown, disconnected, banned_suspected

**Transitions:** active->cooldown on limit/anomaly; ->banned_suspected on hard signals; ->disconnected on auth loss

## 8. Events
**Publishes:** `linkedin.action.sent`, `linkedin.reply.received`, `linkedin.seat.cooldown`, `linkedin.circuit_breaker.tripped`

**Subscribes:** `journey.step.linkedin`, `account.held`

## 9. Business Rules
- **LI-001:** No LinkedIn action executes unless the ban-risk circuit breaker is healthy (hard gate).
- **LI-002:** Per-seat daily caps + randomized human-like pacing strictly enforced.
- **LI-003:** Reply => pause-on-reply + account-centric pause.
- **LI-004:** Suspected-ban => immediate seat halt + human notification; no auto-retry.
- **LI-005:** This engine is activated last in the roadmap, after the breaker service is proven.

## 10. Permissions & RBAC
| Permission | Roles |
|---|---|
| `linkedin.seat.manage` | AE(own), Admin |
| `linkedin.action.queue` | AE, system |
| `linkedin.policy.manage` | Admin |

## 11. Validations
- action within seat limits
- seat active
- contact has linkedin_url

## 12. Error Scenarios
- 503 breaker tripped
- 429 seat daily cap
- 409 duplicate pending action

## 13. Internal Integrations
Journey Engine, Contact Engine (reply->pause), Account Engine (cascade), Notification

## 14. Testing Requirements
- Breaker halts all actions
- Pacing randomization within human bounds
- Cap enforcement per seat
- Reply triggers cascade

## 15. Acceptance Criteria
- [ ] Run a connect+message sequence within limits; reply pauses account
- [ ] Simulated anomaly trips breaker and halts seats

## 16. Edge Cases
- Seat auth expires mid-sequence -> queue holds, notify, no data loss
- Two AEs target same contact -> collision guard
- Captcha detected -> cooldown not retry

## 17. Implementation Checklist
- [ ] seat/session mgmt
- [ ] paced action executor
- [ ] circuit breaker service
- [ ] reply detector
- [ ] limit config
- [ ] cooldown state machine

## 18. Future Enhancements
- Deeper AI autonomy for this module as trust tier rises.
- Additional provider/channel adapters.
- Arabic-first UX refinements.
