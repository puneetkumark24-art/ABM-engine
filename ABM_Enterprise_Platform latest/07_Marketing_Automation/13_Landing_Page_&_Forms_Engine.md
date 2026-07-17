# Module 13 — Landing Page & Forms Engine

> **Domain folder:** `07_Marketing_Automation`  
> **Replaces / equivalent to:** HubSpot Landing Pages + Forms + Unbounce + popups/preference center.

## 1. Purpose
Native landing pages, forms, popups, preference & unsubscribe centers: a builder + hosting + submission pipeline that captures leads directly into the CRM, powers gated assets (whitepaper/case-study downloads), and manages consent — closing the loop the BFSI whitepaper campaign needed.

## 2. Scope
**In scope**
- Landing page builder (blocks) + hosting + SEO/OG/JSON-LD
- Forms (fields, validation, progressive profiling, hidden UTM)
- Popups & preference center + unsubscribe center
- Submission -> contact create/update + journey enroll + consent capture
- Gated content delivery (asset unlock)

**Out of scope**
- Asset storage (Asset Library 14)
- Email sending (Delivery/Marketing)
- Analytics math (Analytics)

## 3. Personas
| Persona | Relationship to module |
|---|---|
| Marketer | Builds pages/forms |
| Visitor/Lead | Submits form |
| System | Processes submission -> CRM |

## 4. Data Entities & Schema

### `landing_page`
Hosted page.

```
id UUID pk; tenant_id UUID; slug text unique; title text; blocks jsonb; seo jsonb; status enum(draft,published); form_id UUID null; asset_id UUID null; created_at
```

### `form`
Form definition.

```
id UUID pk; tenant_id UUID; name text; fields jsonb; consent_config jsonb; progressive bool; redirect jsonb; created_at
```

### `submission`
A form submission.

```
id UUID pk; form_id UUID; landing_page_id UUID null; contact_id UUID null; data jsonb; utm jsonb; consent_given bool; ip inet; created_at
```

### `preference`
Contact channel preferences.

```
id UUID pk; contact_id UUID; channels jsonb; unsubscribed_all bool; updated_at
```

## 5. API Contracts
| Method | Path | Purpose | Responses |
|---|---|---|---|
| `POST` | `/v1/pages` | Create/publish a landing page. | 201 |
| `POST` | `/v1/forms` | Create a form. | 201 |
| `POST` | `/v1/forms/{id}/submit` | Public submission endpoint. | 201 |
| `GET` | `/p/{slug}` | Public render of a landing page. | 200 html |
| `PUT` | `/v1/preferences/{contact}` | Update preference/unsub center. | 200 |

## 6. Core Workflows
1. Publish page/form -> visitor submits -> validate + spam check -> upsert contact (identity resolution) + capture consent + UTM -> optional journey enroll + gated asset unlock -> emit form.submitted
2. Preference center update -> propagate consent/suppression

## 7. State Machine — `landing_page`
**States:** draft, published, archived

**Transitions:** draft->published on publish; ->archived

## 8. Events
**Publishes:** `form.submitted`, `page.published`, `preference.updated`, `consent.captured`

**Subscribes:** `campaign.activated (link pages)`, `asset.published`

## 9. Business Rules
- **LP-001:** Every form capturing contactable data must capture explicit consent (PDPL) + store IP/timestamp.
- **LP-002:** Submission upserts via Identity Resolution — no blind duplicate contacts.
- **LP-003:** Unsubscribe center writes global suppression immediately.
- **LP-004:** Gated asset served only after valid submission; link is signed & expiring.
- **LP-005:** Canonical/OG URLs must be real published paths before indexing.

## 10. Permissions & RBAC
| Permission | Roles |
|---|---|
| `pages.manage` | Marketer, Admin |
| `forms.manage` | Marketer, Admin |
| `submissions.read` | Marketer, AE, Admin |

## 11. Validations
- slug unique
- required fields
- consent present when required
- valid redirect

## 12. Error Scenarios
- 409 slug taken
- 422 missing consent
- 429 submission rate-limit (bot)

## 13. Internal Integrations
Contact Engine (upsert), Journey (enroll), Asset Library (unlock), Marketing (suppression), Analytics (conversion)

## 14. Testing Requirements
- Submission dedups to existing contact
- Consent stored with proof
- Gated link expires
- Bot/spam rate limiting

## 15. Acceptance Criteria
- [ ] Publish a gated whitepaper page; submission creates contact, captures consent, unlocks asset, enrolls in journey
- [ ] Unsub center suppresses globally

## 16. Edge Cases
- Repeat submitter -> progressive profiling adds fields, no dup
- Missing UTM -> direct/organic attribution
- Asset link shared -> expiry blocks non-submitters

## 17. Implementation Checklist
- [ ] page/form builder + renderer
- [ ] submission pipeline + identity upsert
- [ ] consent + preference center
- [ ] gated asset signer
- [ ] spam protection
- [ ] SEO/OG/JSON-LD

## 18. Future Enhancements
- Deeper AI autonomy for this module as trust tier rises.
- Additional provider/channel adapters.
- Arabic-first UX refinements.
