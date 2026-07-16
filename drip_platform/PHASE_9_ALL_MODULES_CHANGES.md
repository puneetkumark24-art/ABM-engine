# Phase 9 — All 16 Remaining Modules Implemented

Every SCAFFOLD module from Phase 8 is now real, working, tested code inside
`drip_platform/`. Registry after this phase: **20 LIVE · 6 PARTIAL · 0 SCAFFOLD**
(the 6 PARTIALs — Intelligence, Contact, Account, CRM, Pipeline, Gateway — were
already partly real and keep deepening on their own tracks).

**Safety invariants preserved:** additive-only (36 new tables, zero existing
columns touched), decimal_abm untouched, and **nothing can send for real** —
the delivery engine's only registered transport is `dry_run` (the API even
hard-locks it), the LinkedIn executor is a stub behind a circuit breaker, and
the AI generator defaults to an offline template with PII anonymization.

## Test gate: 53/53 platform checks + 30/30 sequence regression — all green (SQLite).

## What each module now does

| # | Module | Real behaviour (verified by test) |
|---|---|---|
| 03 | Enrichment | Pluggable provider waterfall (stops at first satisfying provider), offline email verification (invalid ⇒ do_not_contact), duplicate detection via hard keys + name-similarity. |
| 07 | Marketing | Audiences (static lists + dynamic JSON-filter segments), global suppression, campaigns with A/B variants, send-time gate (consent + do_not_contact + suppression), campaign report with per-variant split. |
| 09 | Campaign (ABM plays) | Groups sequences/email-campaigns/landing-pages/assets under one play; unified rollup (sends, opens, enrollments, submissions). |
| 10 | AI Personalization | Anonymized context (no real names to any model), offline generator default + pluggable LLM adapter, rule-based QC (placeholder leaks, teaser-discipline facts, length), c-suite ⇒ human approval always. |
| 11 | Email Delivery | Idempotent send queue (by message_id), normalized event pipeline, webhook ingest with replay dedup (incl. within-batch), bounce/complaint ⇒ auto-suppression. Only transport: dry_run. |
| 12 | LinkedIn | Seats with daily caps, queue → stub executor, circuit breaker hard gate (nothing runs when tripped), reply ⇒ account-centric pause via the sequence engine. |
| 13 | Landing/Forms | Form defs + required-field validation, consent-required enforcement (PDPL), submission upserts Person with consent proof, unsubscribe ⇒ suppress + consent denied. |
| 14 | Asset Library | Name-versioning, HMAC-signed expiring links for gated assets (tamper + expiry rejected), usage/download tracking. |
| 15 | Rules Engine | No-code IF/THEN: deterministic condition ops, 5 actions (opportunity, task, notify, enroll, event) executed in order, priority, simulate/dry-run, and **rules cannot bypass compliance** (enroll goes through the sequence gate — proven: suppressed person not enrolled). |
| 16 | Workflow Engine | Durable node runs (start/condition/delay/email/notify/approval/end), suspends at approvals & delays, resumes from persisted cursor, branch edges, validation rejects malformed DAGs. |
| 17 | Analytics | Event-sourced metric store, optional bus auto-ingest, grouped queries, funnel with conversion %. |
| 20 | Reporting | Saved reports over analytics + one-click exec brief (committee, live signals only — decayed excluded, open opps, suggested next steps). |
| 21 | Notification | In-app inbox, per-user quiet hours (held then flushed), urgent bypass. |
| 22 | Attribution | first/last/linear/time-decay/W-shaped credit models (fractions sum to 1.0), campaign-level rollup. |
| 25 | Admin | RBAC deny-by-default with wildcard grants, quotas that block at the limit, audit hook. |
| 26 | Copilot | Grounded intent router: "who should I call today" (due steps + HOT fallback), "how do I approach <bank>" (committee + live signals + citations), "status" (registry + data counts). Free-form ⇒ pluggable LLM adapter, not required. |

## Files added / changed

- **`models_ext.py`** — 36 new tables (separate file; models.py untouched except Phase-7's append).
- **`abm_platform/services/`** — 16 service modules (+ `__init__.py`).
- **`alembic/versions/d4e8b1c5a7f9_…`** — additive migration (`c7d1f0a2b9e4 → d4e8b1c5a7f9`), creates all 36 tables from model metadata (checkfirst).
- **`routers/platform_modules.py`** — `/px/*` API for all 16 modules; `main.py` includes it.
- **`abm_platform/registry.py` + 16 `mNN_*/service.py`** — statuses flipped to LIVE, wired to the real services.
- **`tests/test_platform_services.py`** — 53 checks.
- **`sequences/engine.py`** — one Phase-9 strengthening: enrollment now also blocks globally-suppressed emails (JRN-001), guarded so it degrades gracefully if models_ext isn't deployed.

## Bugs found by the tests and fixed during the build

1. Webhook batch dedup missed duplicates inside a single batch (uncommitted rows) → batch-local seen-set.
2. Linear/time-decay attribution rounded per-touch shares so credit summed to 0.999999 → full precision kept.
3. Sequence enrollment ignored the marketing suppression list → gate added.

## Apply on your machine

```bash
cd drip_platform
alembic upgrade head          # c7d1f0a2b9e4 -> d4e8b1c5a7f9 (36 tables)
python tests/test_platform_services.py   # expect 53/53
python tests/test_sequence_engine.py     # expect 30/30
uvicorn main:app --reload     # /px/* + /platform/* + /sequences/* in /docs
```

## Still deliberately NOT live

Real email transport (Mandrill/SMTP adapter registration + public HTTPS webhook — your VPS/ngrok decision), a real LinkedIn client (breaker-gated, roadmap-last), an external LLM adapter for generation/copilot, and the deepening of the 6 PARTIAL modules. Every one of these now has its exact insertion point marked in code.
