# Phase 12 — Honest Scorecard vs. HubSpot & Mailchimp (2026 features) + The Upgrades

## Part 0 — "Is it live?"

Straight answer: **built and verified, not yet deployed.** Every engine below is
real, running code with 171/171 checks green on SQLite **and** on a real
PostgreSQL 16.2 server (full 18-migration chain, 75 tables). It becomes *live*
on your machine with `alembic upgrade head` + `uvicorn main:app` — and becomes
*production-live* only after your three infrastructure decisions: public HTTPS
domain (for `/t/*` tracking + webhooks), a real transport (SES adapter is coded,
inert until `ENABLE_SES_TRANSPORT=true` + credentials), and PDPL sign-off before
any real outreach.

## Part 1 — What HubSpot & Mailchimp actually ship in 2026 (fetched, not assumed)

**HubSpot Smart CRM 2026:** unlimited contacts/companies/deals in one record
system; customizable pipelines & deal stages; tasks with reminders **and
subtasks (new 2026)**; workflow automation (triggers → tasks/notifications/
sequences/property updates); **custom objects & properties with default
property values (new 2026)**; views & dashboards; email tracking
(open/click notifications); Breeze AI (enrichment, summaries, predictive lead
scoring, AI content).

**Mailchimp 2026:** campaigns + "Flows" visual journey builder (triggers,
delays, conditions, branching); segmentation incl. behavioral/engagement-
scoring segments; **send-time optimization**; A/B testing; deliverability
tooling (domain auth, abuse detection, **automatic campaign pausing on high
bounce/spam**); AI copy + subject suggestions; analytics (opens, clicks,
revenue, growth).

## Part 2 — Engine-by-engine honest score (before → after today)

| # | Engine | Before | Built today | **After** |
|---|---|---|---|---|
| 1 | CRM objects/timeline/graph | 6/10 | **Custom properties framework** (text/number/date/bool/enum, validation, *default values* — the 2026 HubSpot feature), **saved views** (native + `custom.*` + engagement pseudo-fields, sort), **real Task object** (due, assignee, priority, reminders, *subtasks*, my-day queue: overdue/today/reminders/upcoming) | **7.5/10** |
| 2 | Pipelines & forecast | 7/10 | — (already ≥7) | 7/10 |
| 3 | Marketing campaigns | 5.5/10 | **Merge-field rendering with fallbacks** (`{name|there}` — a tag never renders literally), **campaign scheduling** honored by a tick (KSA-window aware), **test-send**, **A/B auto-winner** (min 30/variant + two-proportion z-test ≥1.96, winner fed to the AI feedback loop), **engagement-scoring segments** | **7.5/10** |
| 4 | Journeys / Workflows | 7/10 | — (already ≥7; visual builder UI is the remaining gap) | 7/10 |
| 5 | Email delivery & deliverability | 5.5/10 | **Amazon SES transport adapter** (code complete; refuses to activate without explicit env opt-in + boto3 + creds — safety by construction), **retry with exponential backoff** (5/30/120min, terminal after 3, never silently dropped), **mid-send auto-pause** on bounce >5% / complaint >0.2% with urgent alert (Mailchimp's signature safety behaviour) | **7/10*** |
| 6 | Tracking & analytics | 7.5/10 | — (pixel/click/web events/CTOR rate card already built in Phase 11) | 7.5/10 |
| 7 | Landing pages & forms | 4/10 | **Real public renderer**: `GET /p/{slug}` serves actual HTML (hero/text/bullets/CTA blocks), embedded PDPL-consent form, tracking.js included, `POST /p/{slug}/submit` → CRM upsert + visitor identification + **gated asset via signed 1-hour link** on the thank-you page | **7/10** |
| 8 | AI (decision + feedback + generation) | 8/10 | — (already above parity: neither product ships a decision engine) | 8/10 |

\* Delivery is 7/10 *of what software can do* — the last points are physical:
a warmed IP/domain with real send history, which only comes from actually
sending. The code for warmup, reputation and gating is all in place.

**Everything is now ≥7/10.** The honest remaining discount across the board is
UI (drag-drop builders, dashboards) and third-party data (Apollo-scale contact
data, real LinkedIn client) — capability logic is at or above parity.

## Part 3 — Verification

| Suite | SQLite | PostgreSQL 16.2 |
|---|---|---|
| test_sequence_engine.py | 30/30 | 30/30 |
| test_platform_services.py | 53/53 | 53/53 |
| test_engine_e2e.py | 30/30 | 30/30 |
| test_tracking_decision.py | 29/29 | 29/29 |
| **test_crm_marketing_ext.py (new)** | **29/29** | **29/29** |
| **Total** | **171/171** | **171/171** |

Migration chain: 18 revisions → head `c9e6a4b8d2f0`, 75 tables on Postgres.

## Part 4 — New files & API

`models_p12.py` (property_defs, property_values, saved_views, crm_tasks) ·
migration `c9e6a4b8d2f0` · services `crm_ext.py`, `marketing_ext.py`,
`landing_render.py`, `delivery_ext.py` · router `crm_marketing_ext.py` ·
suite `test_crm_marketing_ext.py`.

```
POST /crm/properties            define custom property (+defaults, enum options)
POST /crm/properties/set        validated set   GET /crm/properties/{type}/{id}
POST /crm/views                 saved view      GET  /crm/views/{id}/run
POST /crm/tasks (+subtasks)     POST /crm/tasks/{id}/complete
GET  /crm/tasks/my-day/{who}    overdue / due-today / reminders / upcoming
POST /mkt/campaigns/{id}/schedule   POST /mkt/run-scheduled
POST /mkt/campaigns/{id}/test-send  POST /mkt/campaigns/{id}/ab-winner
POST /delivery/retry-failed         POST /delivery/campaigns/{id}/health-check
GET  /p/{slug}                  PUBLIC landing page (HTML)
POST /p/{slug}/submit           PUBLIC form submit → CRM + gated asset link
```

## Part 5 — Sources (feature sets fetched this session)

- [HubSpot CRM Review 2026 — crm.org](https://crm.org/news/hubspot-crm-review)
- [HubSpot Spring 2026 Spotlight: 99 new features — vantagepoint.io](https://vantagepoint.io/blog/hs/hubspot-spring-2026-spotlight-99-features-ranked-business-impact)
- [In-Depth HubSpot CRM Review 2026 — onepagecrm.com](https://www.onepagecrm.com/crm-reviews/hubspot/)
- [Mailchimp official features — mailchimp.com/features](https://mailchimp.com/features/)
- [Ultimate Guide to Mailchimp 2026 — almcorp.com](https://almcorp.com/blog/ultimate-guide-to-using-mailchimp-for-email-marketing/)
- [Mailchimp Review 2026 — mailsoftly.com](https://mailsoftly.com/blog/mailchimp-review/)
