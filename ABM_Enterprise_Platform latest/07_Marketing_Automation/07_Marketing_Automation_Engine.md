# Module 07 — Marketing Automation Engine (Mailchimp Replica)

> **Domain folder:** `07_Marketing_Automation`  
> **Replaces / equivalent to:** Mailchimp + Customer.io + Brevo — audience, segmentation, templates, sending, tracking, automation, deliverability.

## 1. Purpose
A full native marketing-automation system: audiences & dynamic segments, suppression lists, template/email builder with AI generation, sending with open/click/bounce tracking, A/B & multivariate testing, personalization/merge tags/dynamic blocks, transactional + drip automation, deliverability (IP warming, domain/DKIM/SPF/DMARC, SMTP), scheduling with timezone/send-time optimization — replacing Mailchimp entirely.

## 2. Scope
**In scope**
- Audiences, Lists, Segments (static+dynamic), Suppression lists
- Template Builder / Drag-drop Email Builder / AI Email + Subject generator
- Preview, Spam checker, Link/Open/Click/Bounce tracking, Heatmaps
- A/B + Multivariate testing
- Personalization: merge tags, dynamic blocks
- Automation: triggers, drip campaigns, transactional emails, webhooks
- Deliverability: IP warming, domain mgmt, SMTP, DKIM/SPF/DMARC
- Scheduling: timezone send, send-time optimization, AI optimization

**Out of scope**
- Multi-step cross-channel journeys (Journey Engine 08)
- Raw MTA internals delegated to Email Delivery Engine (11)
- Landing pages/forms (13)

## 3. Personas
| Persona | Relationship to module |
|---|---|
| Marketer | Builds campaigns & audiences |
| Deliverability admin | Manages domains/IPs/warmup |
| AE | Triggers 1:1 sends from CRM |
| System | Fires transactional + automation |

## 4. Data Entities & Schema

### `audience`
A managed set of contacts.

```
id UUID pk; tenant_id UUID; name text; kind enum(list,segment); dynamic bool; definition jsonb; size_cache int; updated_at
```

### `suppression`
Global/list suppression entry.

```
id UUID pk; tenant_id UUID; scope enum(global,list); list_id UUID null; email citext; reason enum(unsub,bounce,complaint,manual,invalid); created_at
```

### `template`
Reusable email template.

```
id UUID pk; tenant_id UUID; name text; html text; mjml text null; blocks jsonb; merge_tags text[]; created_by; version int
```

### `email_campaign`
A one-to-many send.

```
id UUID pk; tenant_id UUID; name text; template_id UUID; audience_id UUID; from_domain_id UUID; subject text; preheader text; status enum(draft,scheduled,sending,sent,paused); ab_config jsonb null; schedule jsonb; created_at
```

### `email_message`
Per-recipient message instance.

```
id UUID pk; campaign_id UUID null; journey_step_id UUID null; contact_id UUID; status enum(queued,sent,delivered,opened,clicked,bounced,complained,unsub); variant text null; provider_msg_id text; sent_at; events jsonb
```

### `ab_test`
Test config & result.

```
id UUID pk; campaign_id UUID; type enum(ab,multivariate); variants jsonb; metric enum(open,click,reply); winner text null; status enum(running,decided)
```

### `domain`
Sending domain + auth.

```
id UUID pk; tenant_id UUID; domain text; dkim_status enum; spf_status enum; dmarc_status enum; ip_pool text; warmup_stage int; reputation numeric(4,3)
```

## 5. API Contracts
| Method | Path | Purpose | Responses |
|---|---|---|---|
| `POST` | `/v1/mkt/audiences` | Create list/segment (dynamic definition). | 201 |
| `GET` | `/v1/mkt/audiences/{id}/members` | Resolve members. | 200 paged |
| `POST` | `/v1/mkt/templates` | Create/version a template. | 201 |
| `POST` | `/v1/mkt/templates:generate` | AI-generate template/subject from brief. | 200 |
| `POST` | `/v1/mkt/campaigns` | Create campaign (audience+template+schedule+AB). | 201 |
| `POST` | `/v1/mkt/campaigns/{id}:schedule` | Schedule/send (timezone/STO). | 200 |
| `POST` | `/v1/mkt/campaigns/{id}:spamcheck` | Run spam/deliverability preflight. | 200 |
| `GET` | `/v1/mkt/campaigns/{id}/report` | Opens/clicks/bounces/heatmap. | 200 |
| `POST` | `/v1/mkt/suppressions` | Add suppression. | 201 |
| `POST` | `/v1/mkt/domains` | Add sending domain + auth checks. | 201 |

## 6. Core Workflows
1. Build audience -> build/generate template -> create campaign -> spamcheck preflight -> schedule (timezone/STO) -> Email Delivery Engine sends -> track events -> report; AB: split, measure metric, auto-pick winner, send winner to remainder
2. Transactional: event trigger -> template render -> immediate send via delivery engine
3. Suppression: any unsub/bounce/complaint -> global suppression -> excluded from all future sends

## 7. State Machine — `email_campaign`
**States:** draft, scheduled, sending, sent, paused

**Transitions:** draft->scheduled on schedule; ->sending at fire time; ->sent on completion; ->paused on deliverability trip

## 8. Events
**Publishes:** `email.campaign.sent`, `email.event.opened`, `email.event.clicked`, `email.event.bounced`, `email.event.complained`, `email.unsub`

**Subscribes:** `contact.consent.changed`, `journey.step.email`, `deal.stage.changed (transactional)`, `schedule.tick`

## 9. Business Rules
- **MKT-001:** Every send checks global + list suppression AND contact consent/do_not_contact at send time.
- **MKT-002:** A domain below reputation threshold or mid-warmup throttles volume automatically.
- **MKT-003:** Unsub/bounce/complaint => immediate global suppression + feedback to Lead Scoring (negative).
- **MKT-004:** KSA calendar — no sends Fri/Sat or during Ramadan blackout window.
- **MKT-005:** A/B winner auto-selected only after minimum sample & significance; else manual.
- **MKT-006:** Merge-tag with no value uses fallback; never sends a literal {tag}.

## 10. Permissions & RBAC
| Permission | Roles |
|---|---|
| `mkt.campaign.manage` | Marketer, Admin |
| `mkt.send` | Marketer, Admin |
| `mkt.domain.manage` | Deliverability Admin, Admin |
| `mkt.audience.manage` | Marketer, Ops |

## 11. Validations
- audience non-empty at schedule
- domain auth (DKIM/SPF) green before send
- subject/preheader length limits
- AB variants>=2

## 12. Error Scenarios
- 409 send to unauthenticated domain
- 422 empty audience
- 423 blocked by KSA calendar
- 429 warmup throttle

## 13. Internal Integrations
Email Delivery Engine (11), Contact Engine (consent), Journey Engine (08), Analytics/Attribution, AI Personalization (10), Lead Scoring (feedback)

## 14. Testing Requirements
- Suppression enforced at send
- Warmup throttle curve
- AB significance gate
- Timezone send correctness
- Merge-tag fallback
- KSA blackout blocks send

## 15. Acceptance Criteria
- [ ] Send a segmented campaign with tracking & report
- [ ] AB test auto-picks winner and completes send
- [ ] Bounce suppresses contact everywhere
- [ ] DKIM/SPF must be green to send

## 16. Edge Cases
- Dynamic segment shrinks to 0 before send -> abort + notify
- Contact unsubscribes mid-campaign -> excluded from remaining batches
- Shared IP complaint spike -> auto-pause + alert
- Duplicate email in two lists -> single send (identity dedup)

## 17. Implementation Checklist
- [ ] audience/segment engine (shared w/ CRM views)
- [ ] template + block builder + AI generate
- [ ] campaign + message tables
- [ ] tracking pixel + click redirect + bounce/complaint webhooks
- [ ] AB/MVT engine
- [ ] domain/DKIM/SPF/DMARC + warmup
- [ ] suppression service
- [ ] scheduler + STO

## 18. Future Enhancements
- Deeper AI autonomy for this module as trust tier rises.
- Additional provider/channel adapters.
- Arabic-first UX refinements.
