# Signal Pipeline P1 — Confidence/Decay Stamping (drip_platform)

Per `docs/Signal_Pipeline_Architecture.md` §6, P1: "the highest-leverage,
lowest-risk next build — everything you already have manually entered gets
a confidence_score, decay_category, and automatic re-classification,
without touching scraper fragility or ban risk at all." No `raw_captures`,
no `source_registry`, no scraping — those are P2+. This closes the first of
the three concrete gaps named in `Signal_Source_Bottleneck_Analysis.md`
§Part 4: "No decay/freshness model on `Signal`."

## What was built

**`models.py`** — 4 new nullable columns on `Signal` (additive, matches the
existing SIG-TENDER/SIG-PARTNER migration pattern):
`confidence_score` (float), `decay_category` (string), `decay_expires_at`
(datetime), `source_reliability` (float, left NULL — populated from
`source_registry` once P2 exists; nothing here fabricates it in the
meantime, per EPIS-RCM-05).

**`alembic/versions/b1e4a9c07d32_...py`** — additive migration, revises
`f3b8d1a92c47` (confirmed the sole current head before branching).

**`etl/signal_decay.py`** (new module):
- `SIGNAL_TYPE_TO_DECAY_CATEGORY` — the Bible's explicit mapping
  (rfp→tactical, partnership→strategic, hiring→operational,
  regulatory→strategic) extended to DRIP's other 6 signal_types, each with
  a documented one-line rationale. Unknown/blank types fall back to
  OPERATIONAL (shortest decay, so unclassified evidence doesn't linger
  overweighted — EDGE-EPIS-01 spirit).
- `DECAY_HALF_LIFE_DAYS` — the midpoint of each tier's day-range from
  `Signal_Source_Bottleneck_Analysis.md` §2.5: OPERATIONAL 18d (7-30),
  TACTICAL 60d (30-90), STRATEGIC 272d (6-12mo), STRUCTURAL 1460d (3-5y).
- `compute_confidence_score(sig)` — deterministic, rule-based (matching
  `signal_intel.py`'s existing "inspectable, not a black box" style, and
  the architecture doc's own OPEN-Q recommendation to start rule-based).
  Base 0.5, +0.15 for a URL present, +0.15 for a non-generic source,
  +0.15/+0.10 for populated type-specific structured fields (RFP
  deadline/scope, or a partnership's matched vendor), +0.05 for a
  substantive summary. Floored at 0.3, capped at 0.95 — never claims full
  certainty (EPIS-RCM-05).
- `stamp_signal_intelligence(sig)` — sets all three fields on a Signal ORM
  object in place; the one function both the live save path and the
  backfill script call, so they can't drift apart.
- `is_decayed(decay_expires_at, now=None)` — an unstamped signal
  (`decay_expires_at is None`) is treated as NOT decayed, never as stale.

**`dashboard/app.py`** — wired `stamp_signal_intelligence()` into both
`signal_new` (after `db.flush()`, so `decay_expires_at` is computed from the
real `created_at` default) and `signal_edit` (re-stamps every save, so
changing a signal's type updates its decay category immediately).
`signal_to_initiative()` now also returns `confidence_score`,
`decay_category`, `decay_expires_at`, and `is_decayed`.

**`etl/backfill_signal_decay.py`** (new script) — stamps every pre-existing
`Signal` row where `decay_category IS NULL`. Idempotent (a second run
touches 0 rows). Run once against the real Postgres `drip` database:
```
python etl/backfill_signal_decay.py
```

**Templates** — `bank_detail.html` and `initiatives.html` both render a
"Decayed" badge and mute (`opacity:0.55`) any signal past its decay window,
and show a `Confidence: NN%` line / column, per the architecture doc's
explicit P1 instruction to "surface decay-based visual de-emphasis."

## Verification performed

- `tests/test_signal_decay.py` (new, 42 checks, run standalone or via the
  same pattern as `test_signal_intel.py`) — the decay-category lookup table,
  the half-life math, `is_decayed` edge cases, all 5 confidence-score
  factors independently (each moves the score in the expected direction,
  bounded [0.3, 0.95]), live signal creation via `signal_new` auto-stamping
  all 3 fields, `signal_edit` re-stamping on a type change
  (hiring→partnership correctly flips OPERATIONAL→STRATEGIC), the backfill
  script stamping a raw pre-existing row and being a true no-op on rerun,
  both templates rendering the new UI without error, and a full regression
  sweep of every existing page. **42/42 pass.**
- `tests/test_signal_intel.py` (pre-existing, SIG-TENDER/SIG-PARTNER) —
  re-run unchanged against the new schema. **53/53 pass**, confirming this
  didn't regress the classification layer it extends.
- `tests/test_scoring.py` — re-run unchanged. **4/4 pass.**
- `python -m py_compile` clean on every changed/new `.py` file, and both
  edited Jinja templates parse cleanly via `jinja_env.get_template()`.
- Caught and fixed, mid-task, two instances of this sandbox's known
  mount-sync-lag bug (a file written via the Write/Edit tool appears
  truncated mid-content when read back via the shell) — in `dashboard/app.py`
  and both templates. Each was caught by the `py_compile`/Jinja-parse step
  immediately after writing, and fixed by reconstructing the exact missing
  tail directly, before any test ran against it.

## What this deliberately does NOT do (P2+, named explicitly per the architecture doc)

- No `raw_captures` table, no source adapters, no scraping of any kind —
  every signal is still 100% manually entered, exactly as before.
- No `source_registry` table — `source_reliability` stays NULL on every
  signal until that table exists; nothing here invents a reliability score.
- No `signal_hypotheses` table (SIG-HYP) — that's explicitly P2 per §4.3.
- Does not change `classify_partnership()` or any SIG-TENDER/SIG-PARTNER
  behavior — this sits alongside that layer, stamping every signal type,
  not just partnerships.
- Does not add a coverage-at-account-level signal (the bottleneck
  analysis's third named gap, "days since last signal / distinct
  signal_types logged") — out of scope for this pass, a natural P1.5/P2
  follow-on if wanted next.

## Next steps per the architecture doc's build order

P2 — `raw_captures` + `source_registry` tables, with the manual form
becoming the first "adapter" writing into `raw_captures` (status
auto-PROMOTED since a human already vetted it). This is the natural next
task once this is reviewed.
