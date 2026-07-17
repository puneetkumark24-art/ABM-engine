# Module 21 — Notification Engine

> **Domain folder:** `14_Admin`  
> **Replaces / equivalent to:** HubSpot notifications + Slack/Teams alerts.

## 1. Purpose
Central multi-channel notification and alerting: in-app, email, Slack, Teams, WhatsApp — delivering NBAs, replies, hot-account alerts, approvals, anomalies and digests to the right person with preferences, batching and escalation.

## 2. Scope
**In scope**
- Notification templates + channels (in-app/email/Slack/Teams/WhatsApp)
- User notification preferences & quiet hours
- Real-time alerts (reply, hot account, approval needed, anomaly)
- Batching/digest + escalation policies
- Delivery tracking of notifications

**Out of scope**
- Marketing sends (Marketing/Delivery)
- The events themselves (produced by other engines)

## 3. Personas
| Persona | Relationship to module |
|---|---|
| AE | Gets reply/hot-account alerts |
| Manager | Approvals/escalations |
| Admin | Configures channels/policies |

## 4. Data Entities & Schema

### `notification`
A notification instance.

```
id UUID pk; tenant_id UUID; user_id UUID; kind text; channel enum(in_app,email,slack,teams,whatsapp); payload jsonb; status enum(pending,sent,read,failed); priority enum(low,med,high,urgent); created_at; read_at
```

### `notify_pref`
Per-user preferences.

```
user_id UUID pk; channels jsonb; quiet_hours jsonb; digest enum(off,daily,weekly)
```

### `escalation`
Escalation policy.

```
id UUID pk; tenant_id UUID; kind text; steps jsonb; timeout_min int
```

## 5. API Contracts
| Method | Path | Purpose | Responses |
|---|---|---|---|
| `POST` | `/v1/notifications:send` | Emit a notification (internal). | 202 |
| `GET` | `/v1/notifications` | User inbox (in-app). | 200 |
| `POST` | `/v1/notifications/{id}:read` | Mark read. | 200 |
| `PUT` | `/v1/notifications/preferences` | Set channels/quiet hours/digest. | 200 |

## 6. Core Workflows
1. Event -> notification rule maps to users+channels -> respect prefs/quiet hours -> deliver (channel adapter) -> track read -> unacknowledged high-priority escalates per policy
2. Digest batches low-priority into daily/weekly

## 7. State Machine — `notification`
**States:** pending, sent, read, failed

**Transitions:** pending->sent on deliver; ->read on ack; ->failed on channel error (retry/next channel)

## 8. Events
**Publishes:** `notification.sent`, `notification.escalated`

**Subscribes:** `email.reply.received`, `account.tiered (hot)`, `workflow.approval.requested`, `analytics.anomaly.detected`, `intelligence.nba.created`

## 9. Business Rules
- **NOT-001:** Respect user quiet hours + KSA calendar for non-urgent notifications.
- **NOT-002:** Urgent (reply on live deal) bypasses digest & quiet hours.
- **NOT-003:** Unacknowledged high-priority escalates after timeout.
- **NOT-004:** Notification delivery uses platform Email engine for email channel.

## 10. Permissions & RBAC
| Permission | Roles |
|---|---|
| `notifications.read.own` | All |
| `notify.policy.manage` | Admin |

## 11. Validations
- channel enabled for tenant
- recipient exists
- priority valid

## 12. Error Scenarios
- 422 channel not configured
- 429 rate-limited per user
- failover to next channel on failure

## 13. Internal Integrations
All engines (sources), Email Delivery, Integration Layer (Slack/Teams/WhatsApp), Admin (channel config)

## 14. Testing Requirements
- Quiet-hours honored except urgent
- Escalation on timeout
- Channel failover
- Digest batching

## 15. Acceptance Criteria
- [ ] Reply on a hot deal alerts AE instantly across in-app+Slack
- [ ] Low-priority items batch into daily digest

## 16. Edge Cases
- User offline all channels -> escalate to manager
- Slack workspace disconnected -> failover email
- Notification storm -> per-user rate limit + batch

## 17. Implementation Checklist
- [ ] notification + prefs + escalation tables
- [ ] channel adapters (in-app/email/slack/teams/whatsapp)
- [ ] preference + quiet-hours logic
- [ ] escalation engine
- [ ] digest batcher

## 18. Future Enhancements
- Deeper AI autonomy for this module as trust tier rises.
- Additional provider/channel adapters.
- Arabic-first UX refinements.
