# Claude Handoff — DRIP 360 Signal Engine

## Objective

Continue building the signal-capture portion of DRIP until it provides honest,
account-specific 360-degree observation and can be transplanted into the
original DRIP application. Signal capture is the highest-priority component.

## Non-negotiable safety boundaries

- Work only in this isolated package unless Puneet separately authorizes migration.
- Do not modify the original DRIP project or its PostgreSQL database.
- PostgreSQL access, if used, must be explicitly read-only.
- Do not modify GitHub.
- Do not access, configure, or send through SendGrid without explicit authorization.
- Never initiate outreach. All signals remain shadow-only.
- Do not scrape LinkedIn. Use an authorized LinkedIn API, licensed provider, or explicit export.
- HeyReach is not available and must not be treated as a capture source.
- HubSpot is the active CRM.
- Never print secrets or commit credentials.

## What is implemented

### Processing core

- Immutable observations and evidence links.
- RSS/Atom and official-page ingestion.
- English/Arabic account attribution using aliases, domains and tickers.
- URL normalization and exact/syndication/event deduplication.
- Deterministic product relevance, review routing and market-intelligence routing.
- Event-time confidence, decay, expiry, corroboration and coverage caps.
- Human review approval/rejection.
- Promoted signals remain separate from evidence.
- No action execution.

### 360 capture framework

Fourteen channels are registered per account:

1. public_news
2. regulator
3. exchange
4. official_site
5. careers
6. procurement
7. linkedin_company
8. linkedin_people
9. linkedin_jobs
10. crm
11. email_engagement
12. website_intent
13. app_releases (optional)
14. social_other (optional)

Implemented capabilities:

- Per-account/channel capture targets and freshness requirements.
- Capture events with idempotent external IDs.
- Persistent account/channel gap alerts.
- Stable visible-text page hashing that ignores scripts, styles and templates.
- Empty/script-only pages are rejected as invalid baselines.
- Page changes create passive capture events.
- Bounded-parallel page fetching with isolated source failures.
- Bulk page-watch CSV import.
- Authorized LinkedIn CSV/provider boundary; no scraper.
- Generic JSON/JSONL CRM, email and website-intent ingestion.
- HubSpot webhook/export normalization.
- HubSpot v1 signature-validated integration endpoint.
- Structured claim extraction with field-level completeness and materiality.
- Same-source-family corroboration does not inflate confidence.
- Cancellation, retraction and correction evidence contests the prior signal,
  disables scoring/action eligibility and enters human review.
- Reviewer confirmation preserves the contested state without creating a new
  positive signal; rejection restores the prior signal.
- Quality feedback matrix and legacy quality backfill.
- Replay-resistant HMAC/timestamp-authenticated first-party webhook endpoint.
- Scheduler hook for page checks.
- HTML daily/status report.

## DRIP and PostgreSQL findings

The uploaded DRIP project was inspected read-only.

- PostgreSQL connectivity was verified in read-only mode.
- Public schema contains accounts, contacts, signals, engagement_events,
  news_items, opportunities, score_breakdowns, products and related tables.
- Current counts observed: 25 accounts, 235 historical signals, 1 contact,
  0 engagement events, 0 news items and 0 opportunities.
- DRIP contains HubSpot code and a configured HubSpot key.
- HeyReach environment fields exist but HeyReach is not configured or available.
- DRIP contains SendGrid outbound/webhook code, but SendGrid was not accessed.
- The existing SendGrid webhook requires hardening before production use.
- DRIP scoring uses a 100-point model and P1/P2/P3 signal weighting; the isolated
  engine adds stricter evidence, decay, attribution and coverage controls.

## Verified public page configuration

See `config/verified_watch_targets.csv`. It includes verified targets for:

- Al Rajhi careers, jobs and vendors.
- Riyad Bank careers, jobs and suppliers.
- Alinma newsroom, careers and vendor relations.
- STC Bank careers.

Observed limitations:

- Alinma's careers signup page returned no stable visible text and is rejected.
- Bank AlJazira official domain has a certificate-name mismatch.
- D360 official site returned HTTP 522.
- Riyad official homepage sometimes resets/times out; its careers pages work.
- SNB official homepage failed TLS negotiation from the standard fetcher.
- Do not bypass TLS verification; use safe alternate official endpoints or feeds.

## Latest honest status

- 36 signal-engine tests and 1 bridge integration test pass.
- Processing core is functional in shadow mode.
- Current required 360 coverage: 35.61%.
- Required account/channel cells: 132.
- Open gaps: 85.
- Channel coverage:
  - public_news: 11/11
  - regulator: 11/11
  - exchange: 11/11
  - official_site: 7/11
  - careers: 4/11
  - procurement: 3/11
  - LinkedIn company/people/jobs: 0/11
  - CRM: 0/11 live (adapter ready)
  - email engagement: 0/11 live
  - website intent: 0/11 live
- The 360 readiness threshold is 90%; do not lower it to manufacture readiness.
- 607 legacy observations have quality assessments. Average completeness is
  53.92% and average materiality is 44.94%. The quality calibration gate remains
  false because reviewed feedback has not yet been collected.
- Only one independent source family is represented in the current legacy data,
  so repeated aggregator stories must not be interpreted as independent proof.

## Important accuracy rules

- An adapter existing does not count as coverage.
- A configured channel does not count as coverage without a fresh successful
  account-specific check/event.
- News/regulator/exchange can be global collectors; careers, procurement,
  official sites, LinkedIn, CRM, email and website intent are account-specific.
- One account event must never cover another account.
- A careers landing page is not itself a hiring signal; only meaningful content
  change or a specific job event should create a signal.
- Anonymous website activity must not be attributed to a company without reliable evidence.
- Ambiguous attribution must enter review.
- Signal collection must never automatically trigger outreach.

## Primary files

- `signal_engine/capture.py` — 360 registry, events, page watches, HubSpot normalization and audit.
- `signal_engine/pipeline.py` — observation processing, attribution, relevance, promotion and review.
- `signal_engine/catalog.py` — initial 11-bank catalog and source definitions.
- `signal_engine/db.py` — SQLite shadow schema.
- `signal_engine/cli.py` — operations and reports.
- `drip_integration/` — additive transplant overlay; do not install yet.
- `config/verified_watch_targets.csv` — verified page configuration.
- `tests/` — automated behavior tests.
- `reports/signal_360_capture_status.html` — latest report.

## Run and verify

From the package root:

```powershell
python -m signal_engine.cli init
python -m unittest discover -s tests -v
python -m unittest discover -s drip_integration\tests -v
python -m signal_engine.cli capture-init
python -m signal_engine.cli watch-seed-official
python -m signal_engine.cli watch-import --file config\verified_watch_targets.csv
python -m signal_engine.cli watch-check-all
python -m signal_engine.cli capture-audit
python -m signal_engine.cli quality-backfill
python -m signal_engine.cli quality-audit
python -m signal_engine.cli daily-report --output reports\signal_360_capture_status.html
```

`watch-check-all` performs public read-only network requests. Everything else
can be exercised locally with fixtures/imports.

## Next work, in priority order

1. Add a read-only DRIP/PostgreSQL account synchronization adapter and map the
   25 PostgreSQL accounts to stable signal-engine IDs. Do not write to PostgreSQL.
2. Decide the operational account universe: the initial engine has 11 banks,
   while PostgreSQL has 25 accounts including fintechs and Decimal itself.
   Exclude Decimal itself from prospect monitoring.
3. Finish verified careers, jobs, supplier/procurement, newsroom and investor-
   relations URLs for every in-scope account. Store evidence and do not invent URLs.
4. Build HubSpot read-only backfill for companies, contacts, deals, meetings,
   forms and conversations. Resolve HubSpot object IDs to account IDs before
   counting coverage.
5. Add HubSpot webhook subscription deployment as a separate, explicit activation
   step because configuring subscriptions changes an external system.
6. Add website intent from HubSpot tracking/forms while preventing false company attribution.
7. Add app-store release monitoring for relevant bank apps.
8. Resolve difficult official sites via alternate official endpoints or browser-
   rendered adapters; never disable TLS verification.
9. Keep LinkedIn blocked until official API access, a licensed provider or an
   authorized export is available.
10. Add retry/backoff, a dead-letter queue, distributed scheduler locking and
    end-to-end shadow acceptance tests. Payload redaction/bounding, SQLite WAL,
    local scheduler overlap prevention and immutable correction audit are present.
11. Migrate only after coverage is at least 90%, all tests pass, and Puneet gives
    explicit permission to modify the original DRIP project.

## Known integration caution

Raw HubSpot webhook events generally contain object IDs and changed properties,
not a trustworthy DRIP account ID. The receiver is ready, but production coverage
must not be credited until the event is enriched through HubSpot associations or
a verified mapping table.
