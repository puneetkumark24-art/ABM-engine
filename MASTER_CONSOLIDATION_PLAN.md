# Master Consolidation Plan — ABM / DRIP / HubSpot-replica / Mailchimp-replica

Prepared after reading: the ABM Business Logic Bible (`all sections/`, `final rules/`,
`build artifcat/`), `DRIP_Phase1_System_Discovery_Report.md`, `DRIP_Completion_Summary.md`,
`drip_platform/README.md`, `drip_platform/models.py`, `drip_platform/docs/Signal_Pipeline_Architecture.md`,
the live `decimal_abm` codebase (including the Phase 1 sequencing work done this session),
and the transcripts of the two other in-project chats ("DRIP platform architecture",
"Mailchimp replication analysis").

This is a plan, not code. Nothing described below has been built yet except what's already
flagged as done in the inventory in Section 1.

---

## 0. The naming collision that needs to be resolved first

"Drip" has been used for two different things in this project, and it matters which one
you mean:

1. **DRIP = Decimal Relationship Intelligence Platform** — the codebase at `drip_platform/`.
   This is an intelligence/CRM layer: organizations, persons, signals, scoring, opportunities,
   vendor intelligence, a dashboard. It does **not** currently send anything or run a cadence.
2. **"the drip" / "drip campaign"** — the automated outreach cadence (signal → AI draft →
   approval → scheduled send → sequence progression). This logic lives in **`decimal_abm/`**,
   and is what this session's earlier Phase 1 work (sequence engine, KSA send-window,
   compliance gates) was built into.

Your instruction this turn — "make it in such a way that the current ability of the drip
do not get corrupted but only improves" — almost certainly means **drip_platform**, since
that's the actively-growing system across multiple sessions (dashboard, scoring, signal
pipeline design). But decimal_abm's outreach automation is *also* a real, currently-running
capability that must not break. The plan below protects both, explicitly, because they are
not currently the same system.

---

## 1. Full current-state inventory (what actually exists, verified by reading it)

| # | System | Location | Stack | Maturity | What it does |
|---|---|---|---|---|---|
| 1 | **decimal_abm** | `decimal_abm/` | Flask + SQLite | Live, running daily | Signal scanning (RSS), AI draft generation (Gemini), approval dashboard, multi-channel send (Mailchimp/SendGrid/LinkedIn), HubSpot logging (one-way). **This session added:** a real sequencing engine (`abm_engine/workflow/`), a KSA send-window guard, and two compliance-gate fixes — see `PHASE_1_DRIP_ENGINE_CHANGES.md`. |
| 2 | **ABM Business Logic Bible** | `all sections/`, `final rules/`, `build artifcat/` | Spec only (target: FastAPI+Postgres+n8n+HubSpot+Metabase) | Fully specified, 1,065 rules, zero corresponding code | 33 entities across 5 tiers, the exact scoring formula, a 12-stage build order with acceptance tests. The most mature *design* asset, but not runnable. |
| 3 | **brip_dashboard** | `brip_dashboard/` | Flask + Postgres (schema never found) | Superseded | Predecessor prototype. `drip_platform` already absorbed its universal `organizations`/`persons` vocabulary and its dashboard template set (per the Phase 1 Discovery Report's own recommendation) — treat this folder as archived, not a fourth thing to reconcile. |
| 4 | **drip_platform** | `drip_platform/` | FastAPI + SQLAlchemy + Alembic + Postgres, plus a Flask `dashboard/` | Actively built, largest and most current | Reconciled entity model (`Organization`+`AccountIntelligence` extension, `Person`, `Signal` w/ SIG-TENDER+SIG-PARTNER fields, `Opportunity`, `VendorIntelligence`, `OutreachChannel`, `DocumentUpload`, `Draft`, `AuditLog`, `Unsubscribe`, `Template`). ETL pulls from live `decimal_abm/abm_engine.db`. REST API (organizations/persons/signals/opportunities). Scoring engine matches the Bible's formula exactly (T-SCORE-1 passes: 46.8). 17+ dashboard templates already built. A full **Capture → Filter → Intelligence signal pipeline is designed** (`docs/Signal_Pipeline_Architecture.md`) but not yet built (P1–P5 phased). |
| 5 | **HubSpot-replica research** | This chat, earlier this session | N/A (research) | Documented, not built | Full HubSpot feature/architecture breakdown + open-source component map (Mautic, Chatwoot, Cal.com, Listmonk, GrapesJS, PostHog, Metabase) — delivered as PDF+PPTX. |
| 6 | **Mailchimp-replica research** | Other in-project chat ("Mailchimp replication analysis") | N/A (research) | Documented, not built | Core finding: Mailchimp's real moat is the **event pipeline** (open pixel → click redirect → MTA-level bounce/complaint handling → engagement scoring), not the compose UI. Recommends routing sends through **Mandrill** (Bhagyam already has access) instead of building a mail server, catching Mandrill webhooks in a new Flask route, storing events in two new tables, and feeding a Mailchimp-style engagement score into `account_scores`. Concrete event types confirmed: `send, deferral, hard_bounce, soft_bounce, open, click, spam, unsub, reject, inbound`, authenticated via an `X-Mandrill-Signature` header. Flagged blocker: **Mandrill needs a public HTTPS webhook URL**, which the current single-laptop deployment doesn't have. |

**Data-quality findings already surfaced by drip_platform's ETL run** (worth fixing regardless
of what else happens): of 264 signal rows in `decimal_abm`, only 86 have a unique URL — 178
are duplicates the schema's `UNIQUE(url)` constraint should have blocked. And the 20 "real"
KSA contacts everyone has been referencing only existed as prose in project notes, not in any
file — they've now been transcribed into `drip_platform` with `email_confidence="Unknown"`
and are **not outreach-ready** until enriched.

**`decimal_abm/migrate_sqlite_to_pg.py` is stale** — it targets pre-V2 column names and would
fail or silently drop data if run today. Don't repair it; `drip_platform/etl/migrate_from_decimal_abm.py`
already does this job correctly against the current schema. Archive the old script rather than
fixing it.

---

## 2. The actual question: do we need a *new* folder at all?

**No — and creating one would repeat the exact mistake already documented and corrected once.**
The Phase 1 Discovery Report's own conclusion, after finding three non-integrated systems, was:
*"the risk is building a fourth, incompatible version instead of merging the three that exist."*
`drip_platform` is the result of following that advice — it already is the reconciliation
folder. Standing up a fifth folder now, to "subsume" drip_platform + decimal_abm + HubSpot +
Mailchimp, would be the same error one level up.

**Recommendation: `drip_platform/` is the single engine.** Everything below is framed as
"port into drip_platform," not "build a new folder." If you want a different name for it
going forward (e.g. renaming `drip_platform/` once it's the canonical system), that's a
cheap rename at the end, not a reason to fork now.

---

## 3. Non-corruption guarantees (how "the drip does not get corrupted")

Two systems currently work. Neither should regress while this consolidation happens:

- **decimal_abm keeps running exactly as-is.** It is not touched by this plan except to keep
  feeding `drip_platform`'s ETL (already a one-way, idempotent, non-destructive read).
  The Phase 1 sequencing/compliance/send-window work done this session stays in place and
  keeps protecting decimal_abm's live outreach until execution logic is actually ported to
  drip_platform and proven — not before.
- **drip_platform's existing dashboard, API, and scoring stay intact.** Every addition below
  is a new table (additive Alembic migration) or a new router/module — nothing in this plan
  proposes changing `Organization`, `Person`, `Signal`, or `AccountIntelligence`'s existing
  columns, only adding to them, exactly the pattern already used for SIG-TENDER/SIG-PARTNER.
- **Every phase below ends with a test gate before the next phase starts** — matching the
  Bible's own build-order philosophy ("a stage is 'done' only when its acceptance test
  passes") and this session's own precedent (`test_sequence_engine.py` against a disposable
  DB copy, never the live one).

---

## 4. Target architecture: what "subsumed" actually looks like

```
                         drip_platform/  (the single engine)
   ┌──────────────────────────────────────────────────────────────────────┐
   │  INTELLIGENCE (exists today)                                         │
   │  Organization · Person · Signal · Opportunity · VendorIntelligence   │
   │  AccountIntelligence · AccountScore · scoring.py (Bible formula)      │
   ├──────────────────────────────────────────────────────────────────────┤
   │  SIGNAL PIPELINE (designed, not built — docs/Signal_Pipeline_        │
   │  Architecture.md, P1→P5): raw_captures → filter/dedup/relevance →    │
   │  EPIS confidence stamp → Signal                                      │
   ├──────────────────────────────────────────────────────────────────────┤
   │  OUTREACH EXECUTION (NEW — ported from decimal_abm, generalized)     │
   │  Draft generation (Gemini) · sequence_engine (this session's Phase 1 │
   │  work, ported) · KSA send_window guard · compliance gates            │
   ├──────────────────────────────────────────────────────────────────────┤
   │  CHANNEL / DELIVERY (NEW — Mailchimp-replica plan)                   │
   │  Mandrill send abstraction · webhook event capture (open/click/      │
   │  bounce/spam/unsub) · engagement scoring → feeds AccountScore        │
   ├──────────────────────────────────────────────────────────────────────┤
   │  SATELLITES (NEW — HubSpot-replica plan, adopted not built)          │
   │  Chatwoot (service/chat) · Cal.com (scheduling) · Metabase (BI) ·     │
   │  GrapesJS (forms/landing pages) — each writes back into the same     │
   │  Postgres `drip` database, none owns its own contact database        │
   └──────────────────────────────────────────────────────────────────────┘
```

The organizing principle carried over from the HubSpot blueprint applies directly here: one
shared Postgres object graph, everything else — including decimal_abm's execution logic and
the eventual HubSpot-style satellites — writes into it rather than keeping its own copy of
contacts/signals. `drip_platform` already *is* that shared graph; this plan's job is to make
sure execution and delivery join it instead of staying siloed in decimal_abm forever.

---

## 5. Phased build order

Numbering follows the Bible's own 12-stage order where it applies, with the new work slotted
in using the Discovery Report and Signal Pipeline doc's own phase labels so nothing here
invents a competing numbering scheme.

**Phase 2 (done).** Reconciled schema — `models.py`, initial Alembic migration. ✅
**Phase 3 (done).** ETL from decimal_abm + documented-contacts recovery. ✅
**Phase 4 (done).** REST API (organizations/persons/signals/opportunities). ✅
**Phase 6, partial (done).** Scoring engine, Bible formula verbatim. ✅
**Phase 5 (done, ongoing).** Dashboard — 17+ templates already built.

**Phase 2e (next, low-risk, do first): data hygiene.**
Fix the 178 duplicate signals, retire the 7 orphaned V8 tables in decimal_abm (archive per
the Golden Rule, don't drop), confirm whether contacts loaded into drip_platform via
"documented_contacts_seed" have since been enriched with real emails. None of this requires
a design decision — it's cleanup already flagged as needed.

**Signal Pipeline P1 (next): confidence + decay on existing data, no new scraping.**
Add `confidence_score`, `decay_category`, `decay_expires_at`, `source_reliability` to
`Signal` (additive migration, same pattern as SIG-TENDER/SIG-PARTNER). Wire automatic
classification to run on every signal save, not just partnership saves. Surface decay-based
visual de-emphasis on `bank_detail.html`/`initiatives.html`. This is the highest-leverage,
lowest-risk next build per the pipeline doc's own recommendation — do this before anything
else in this list.

**Outreach Execution port (new phase, the core of "subsuming the drip"):**
1. Add `Draft`-adjacent tables to drip_platform mirroring decimal_abm's proven design:
   `workflow_definitions` / `workflow_steps` / `workflow_enrollments` (this session's Phase 1
   design, generalized — drip_platform's richer `Person`/`OrgTypeTag` model actually makes
   per-relationship-type cadences *easier* than in decimal_abm, since the sequence-selection
   logic already built (`sequence_for_relationship_type`) maps directly onto
   `OrgTypeTag`/`PersonRelationship`).
2. Port `send_window.py` (KSA business-hours + weekend guard) unchanged — it has no
   dependency on decimal_abm's schema, it's a pure function of the clock.
3. Port the compliance gates (`do_not_contact`, `consent_status`, `replied` checks) onto
   `Person` + the new enrollment tables.
4. Port `agents/writer.py`'s Gemini drafting logic to write into drip_platform's `Draft`
   table via the FastAPI layer instead of decimal_abm's SQLite `db.py`.
5. **Test gate:** run the equivalent of `test_sequence_engine.py` against a disposable copy
   of the `drip` Postgres database before this touches anything real. Do not flip decimal_abm's
   live scheduler over to drip_platform until this passes and a manual side-by-side comparison
   (same contact, same day, same decision) matches.

**Mailchimp-replica build (can run in parallel with the above, ~5-7 days per the existing plan):**
1. Add `email_events` table to drip_platform (send/open/click/bounce/spam/unsub/reject,
   keyed to `Person` + the new outreach-enrollment record).
2. Route sends through Mandrill's API instead of (or alongside) the current
   Mailchimp/SendGrid split in decimal_abm.
3. New FastAPI route to catch Mandrill webhooks, verified via `X-Mandrill-Signature`.
4. Feed a computed engagement score into `AccountScore`'s reachability weight — this is the
   loop the original bug history flagged as never actually closed.
5. **Open decision, not yet resolved:** Mandrill requires a public HTTPS endpoint. Either
   stand up a small always-on relay (a cheap VPS, matching the HubSpot blueprint's "Docker
   Compose on one small VPS" recommendation) or keep using ngrok as decimal_abm's
   SendGrid Inbound Parse already does. This decision gates the webhook step, not the send-routing step.

**HubSpot-replica satellites (later, lowest urgency, highest breadth):**
Once drip_platform owns execution + delivery, the satellites from the HubSpot blueprint
(Chatwoot for two-way WhatsApp/email inbox, Cal.com for meeting scheduling, Metabase for BI,
GrapesJS for landing pages/forms) each get wired to the same Postgres `drip` database. No
new design needed here beyond what's already in `Drip_to_HubSpot_Class_Platform_Blueprint.pdf`
— just sequence it after execution/delivery are solid, not before.

**Signal Pipeline P2-P5:** proceeds per `docs/Signal_Pipeline_Architecture.md` on its own
track, independent of the outreach/delivery work above — `raw_captures` + `source_registry`
(P2), then SIG-REG/SIG-NEWS adapters (P3), then SIG-EXEC/EVENT/VENDOR/FIN (P4), then SIG-PATH
gated on a LinkedIn ban-risk circuit breaker (P5, deliberately last).

**Retirement of decimal_abm's execution role:** only after the Outreach Execution port above
has run side-by-side with decimal_abm for a proven period with matching output. Decimal_abm
itself is not deleted — its signal-scanning and Gemini-drafting *logic* is what gets reused;
the SQLite database is archived, not the code's ideas.

---

## 6. Open decisions that need your (or the team's) input — named, not glossed over

1. **Does the drip_platform Postgres database (`drip`) actually exist and hold real data on
   your machine right now?** Both README-level docs flag this as unverified from any sandbox —
   only checkable by running `setup_drip.bat` yourself. Everything above assumes it does; if
   it doesn't yet, that's the literal first step, before any of Section 5 starts.
2. **Who owns the "Account vs Organization" and "HubSpot-as-CRM-of-record" questions** — the
   Bible's stack assumes HubSpot is the deal system of record with n8n for routing; drip_platform
   as built doesn't currently sync to HubSpot at all (decimal_abm does, one-way). Decide whether
   HubSpot stays the sales system of record once drip_platform's API can do everything HubSpot's
   free CRM does, or whether decimal_abm's existing one-way HubSpot logging is sufficient
   indefinitely.
3. **Mandrill's public webhook endpoint** — VPS vs. ngrok, as above.
4. **Is Lalit (HubSpot) and Bhagyam (Mailchimp/Mandrill) in the loop on this consolidation?**
   Both have access this plan depends on (HubSpot API, Mandrill API) — worth confirming before
   Phase 5+ work starts touching either integration.

---

## 7. Immediate next 3 actions (in order)

1. Run `setup_drip.bat` (or the manual equivalent) yourself and confirm the `drip` Postgres
   database is real and populated — this de-risks everything else in this plan.
2. Fix the 178 duplicate signals + retire the 7 orphaned decimal_abm tables (Phase 2e above) —
   small, safe, immediately useful regardless of which later phase happens next.
3. Build Signal Pipeline P1 (confidence/decay columns + automatic classification on every
   save) — the pipeline doc's own top recommendation, and the natural next unit of work in
   drip_platform specifically.

---

## 8. On version control (separate from the above, but requested together)

Git could not be initialized directly against this mounted folder from this session — the
Cowork bridge blocks file *deletion* here by design (`allow_cowork_file_delete` requires your
approval per file, and you'd need to approve constantly since git creates/deletes lock files
on almost every operation). This is not a limitation of your actual machine — run it there
directly:

```
cd "C:\Users\Puneet\Desktop\ABM business logic\decimal_abm"
del .git\config.lock          REM harmless leftover from the attempted init this session
git init
git add -A
git commit -m "Baseline: decimal_abm + Phase 1 drip engine hardening"
```

Repeat the same `git init` / `add` / `commit` pattern in `drip_platform/` separately — it's
a distinct codebase and deserves its own history, not a subfolder of decimal_abm's repo.

For daily automatic commits, the reliable option is a scheduled task **on your machine**
(Windows Task Scheduler running a small script), not through this session, for the same
delete/lock-file reason above. Say the word and I'll write that script — a two-line batch
file (`git add -A && git commit -m "auto: %date%"`) plus the one-time Task Scheduler setup
instructions.

If you want off-machine backup too (protects against disk failure, not just "undo"), that
needs a GitHub.com remote — create an empty repo there and tell me the URL; pushing itself
doesn't require local delete permissions, so that part *can* run from a session with proper
git access on your machine.
