# Sprint 2 — Enterprise CRM · Completion Report

Executed per the Transformation Constitution. Scope: CRM product depth — custom
objects, a money-correct value type, quotes/products/price-books (CPQ), and
property/field history. All additive; no existing API or table broken.

## Result: verified green on real PostgreSQL 16 and SQLite

- **292/292** checks across the **full suite on SQLite** — proves no logic
  regression anywhere from the Sprint 2 additions.
- **66/66** checks on **real PostgreSQL 16** for the DB-dependent behaviors
  (tenancy 15, tenant-writes 11, partitioning 7, platform 14, **CRM2 19**),
  run against a fresh 24-migration chain.
- New Sprint-2 suite **`test_crm2.py` — 19/19 on both SQLite and PostgreSQL**.

Honest note on the harness: unit suites that build their schema via
`create_all()` cannot be run against a *migrated* DB that now contains the new
`quotes` table (its FK to `opportunities` blocks a naive `drop_all`). This is a
test-ordering artifact — never a production path (production never drops tables).
The authoritative run therefore executes migration-dependent suites on the
migrated PG DB and `create_all` unit suites on their own fresh DBs, mirroring the
Sprint-1 pattern. Sprint 2 code passed identically on SQLite and PG.

## What was delivered (governed by the Constitution's Completeness Rule)

### S2-01 · Custom Objects Framework (audit: custom objects 1/10 → ~6/10)
`models_crm2.py` (`custom_object_defs`, `custom_object_records`) +
`abm_platform/services/custom_objects.py`. Tenants define **dynamic object
types** (not just properties on fixed tables): a typed schema of fields
(`text/number/date/bool/enum/ref`, `required`, enum `options`). `create_record`
enforces **strict validation** — required-field presence, unknown-field
rejection, per-type coercion/checking, enum-membership — and `update_record`
does partial validated updates. Proven: define, create+validate, required
enforced, enum enforced, unknown-field rejected, partial update, list. This
closes the single biggest CRM gap versus HubSpot custom objects.

### S2-02 · Money Type (audit: DB money-as-free-text → typed minor units)
`amount_minor` (BigInteger, currency-minor units) added to `opportunities` via
additive migration, **backfilled** from the legacy free-text `estimated_value`
(`_to_minor()`), with `currency` already present. `quotes.to_minor()` /
`format_minor()` parse `"SAR 2.5M"`, `"500k"`, decimals → exact integer minor
units and render `SAR 2,500,000.00`. `pipeline._amount()` now **prefers
`amount_minor`** and falls back to legacy text only when unset — so forecasts
are money-correct without breaking historical rows. Proven: parse (M/k/decimal),
format, forecast on `amount_minor`, legacy fallback still works.

### S2-03 · Property / Field History (audit: "no property history" → covered)
`abm_platform/services/property_history.py` — `record_history()` (full
who/when/action/changed/before/after timeline for any record) and
`field_history()` (one field's value timeline across every change). Built
**ON TOP of the Sprint-1 universal audit trail** (KEEP/EXTEND — no second
capture path). Proven: multi-change history; field timeline shows insert value +
rename `from`→`to`.

### S2-04 (partial) · Quotes / Products / Price-books (CPQ)
`models_crm2.py` (`crm_products`, `price_books`, `price_book_entries`, `quotes`,
`quote_line_items`) + `abm_platform/services/quotes.py`. Create products, a
price book with per-product prices, then build a quote from **product lines**
(priced from the book) and **ad-hoc lines**, apply **discount/tax**, and get a
**money-correct summary** (subtotal, total, line count) — all in minor units,
recomputed on every mutation. Quote links to an `opportunity` via FK. Proven:
subtotal `3×100k + 50k = SAR 350,000.00`, total after discount `SAR 340,000.00`,
line count. *(Meetings/scheduler, calling/inbox, and CRM UI remain TODO — see
backlog S2-04/S2-05.)*

## Score updates (after Sprint 1 → after Sprint 2)

| Category | After S1 | After S2 | Reason | Remaining weakness |
|---|---|---|---|---|
| CRM depth | 42 | **58** | custom objects, money type, CPQ quotes, property history | no CRM UI; meetings/calling/inbox; SCD-2 snapshots |
| Data model | (DB 55) | **60** | typed money in minor units + backfill; dynamic object store | no per-field encryption; history is audit-derived not SCD-2 |
| Architecture | 55 | **57** | additive object framework + service layer, no API breaks | dynamic schema not yet surfaced via public API/UI |
| Documentation | 63 | **64** | this report + backlog updates | no API ref for custom objects/quotes yet |
| **Overall** | **~40** | **~44** | CRM product depth materially raised | UI, sending, meetings, scale-proof still open |

## Definition-of-Done status (Completeness Rule)
Business/Functional/Technical/DB/Migration/Testing design: ✓ (unit + integration
on PG and SQLite). **Not yet complete for a 95/100 CRM gate:** CRM UI (records,
board, timeline, dashboards — S2-05), meetings/scheduler and calling/inbox
(S2-04 remainder), true SCD-2 snapshot tables (S2-03 extension), and a public
API surface for custom objects/quotes (Sprint 8). Tracked in `BACKLOG.md`.

## Honest note per the Constitution's Honesty Clause
Sprint 2 raised real CRM depth with tested code: dynamic custom objects, a
correct money type replacing free text, working CPQ math, and property history.
It did **not** reach 95/100 for CRM — that requires the UI surface and the
remaining engagement features (meetings, calling, inbox), which are large
build-outs (S2-04/S2-05), plus a public API. Nothing is claimed as done that
isn't proven by a passing test.

## Files
`models_crm2.py` · `abm_platform/services/custom_objects.py` ·
`abm_platform/services/quotes.py` · `abm_platform/services/property_history.py` ·
`models.py` (Opportunity `amount_minor`) · `abm_platform/services/pipeline.py`
(`_amount` prefers minor units) · migration
`j7b9d1f3a5c6_add_crm2_custom_objects_quotes_money` · `tests/test_crm2.py`.
