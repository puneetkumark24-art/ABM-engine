# Signal Pipeline Architecture: Capture → Filter → Intelligence

### A spec for automating DRIP's signal layer, grounded in ABM Business Logic Bible §4 (Integrations/EPIS) and §6 (Information Economics)

---

## 0. What changes

Today, every `Signal` row in DRIP is created by a human typing into `signal_new`/`signal_edit`. There is one interpretation layer on top of that (`etl/signal_intel.py`'s `classify_partnership()`), and it only runs when a human manually saves a partnership-type signal. Nothing captures signal on its own, nothing filters noise before it reaches the dashboard, and nothing separates "we know this is true" from "we saw this once, unverified."

This document specifies three layers that sit in front of the existing `Signal` table — Capture, Filter, Intelligence — so that automated sourcing can feed the same table the manual form feeds today, without either path bypassing the other's guarantees. It does not specify code; it specifies the data model, the responsibilities of each layer, the automated/human-reviewed boundary, and the build order. Each design decision below is traced to a specific Bible rule so the reasoning is checkable, not just asserted.

---

## 1. The pipeline, end to end

```
 SOURCE ADAPTERS          RAW CAPTURE           FILTER              INTELLIGENCE            SIGNAL (existing)
 ───────────────         ─────────────        ──────────          ──────────────           ─────────────────
 SIG-NEWS scraper    →                    →                   →                        →
 SIG-REG scraper     →    RawCapture      →    Dedup check    →   EPIS RCM stamp      →    Signal row
 SIG-EXEC scraper    →    (append-only,   →    Relevance      →   Classification      →    (bank_detail.html
 SIG-VENDOR scraper  →     source-of-     →    score          →   (SIG-PARTNER,       →     initiatives.html,
 manual form entry   →     truth for      →    Blocking vs.   →    future SIG-VSAT,   →     scoring.py inputs)
                           what arrived)        non-blocking       SIG-HYP, etc.)
                                                                    Decay tag
                                                                    Urgency default
```

Every source — automated scraper or human typing into the existing form — writes to the same entry point (`RawCapture`, §2 below). The manual form doesn't disappear; it becomes one more adapter feeding the same pipe, which is why nothing in `signal_new`/`signal_edit`/`signal_intel.py` needs to be thrown away. This mirrors the Bible's own framing (§4.9 API-10): every producer goes through the same contract, nothing writes into a later stage's table directly.

---

## 2. Layer 1 — Capture

**Responsibility:** get raw material into the system, with full provenance, without deciding yet whether it matters.

### 2.1 New table: `raw_captures`

An append-only log, separate from `signals`. This is the single most important structural decision in this document, and it's directly required by two Bible rules: EPIS-RCM-05 ("the engine never fabricates confidence; absence of evidence is recorded, not filled with an inferred value") and INT-ORC-02 (idempotent steps — a re-run of a scraper must not double-create signals). If capture writes straight into `signals`, there's no way to re-run the filter/intelligence layers against the same raw material later without either duplicating rows or destroying the original capture.

```
raw_captures
  id                   uuid, pk
  source_stream        string   -- SIG-NEWS / SIG-REG / SIG-EXEC / SIG-VENDOR / MANUAL / ...
  source_name          string   -- "SAMA circulars page", "Riyad Bank press room", "Puneet (manual)"
  source_url           string, nullable
  raw_title            text
  raw_body             text
  raw_hash             string, indexed   -- sha256(source_url or normalized title+body) for dedup
  captured_at          datetime
  org_id_guess         string, fk->organizations, nullable  -- adapter's best guess, unconfirmed
  status                string   -- PENDING / FILTERED_OUT / PROMOTED / ERROR
  filter_result        JSON, nullable    -- populated by Layer 2
  promoted_signal_id    string, fk->signals, nullable
```

`raw_hash` is what makes the pipeline idempotent (INT-ORC-02): a scraper that runs hourly and re-fetches the same press release doesn't create a new row, it's a no-op keyed on the hash — matching `INT-CRM-01`'s idempotency pattern already established for CRM sync in the Bible, applied here to capture instead of sync.

### 2.2 Source adapters

Each of the 8 INT-SIG sub-streams gets its own adapter, sharing one interface: `fetch() -> list[RawCaptureCandidate]`. Per the bottleneck analysis already delivered, these are not equally easy to build — ranked by what's actually tractable first:

| Adapter | Mechanism | Practical risk | Build tier |
|---|---|---|---|
| SIG-REG | Poll SAMA/CMA circular pages (structured, low change-rate) | Low — mostly static HTML/PDF listings | P1 |
| SIG-NEWS | RSS/scrape bank press rooms + a news aggregator | Medium — layout changes break selectors (§1.2 of bottleneck doc) | P1 |
| SIG-EXEC | LinkedIn profile changes, press mentions | High — LinkedIn scraping without Heyreach-style ban-risk controls is fragile | P2 |
| SIG-EVENT | Conference/event listing sites | Medium — inconsistent formats across sites | P2 |
| SIG-VENDOR | Vendor case-study pages, press | Medium — same fragility as SIG-NEWS, lower cadence | P2 |
| SIG-SUBS | Manual/periodic — subsidiaries change rarely | Low | P2 (mostly manual) |
| SIG-FIN | Annual report / investor relations pages | Low, quarterly cadence | P2 |
| SIG-PATH | Requires LinkedIn automation (INT-LIN) | Highest — ban-risk circuit breaker required (§1.1 of bottleneck doc) | P3, do not start until INT-LIN-02 equivalent exists |

SIG-PATH is called out specifically: nothing here should touch LinkedIn automation before the ban-risk circuit breaker (§4.3 INT-LIN-02) is actually implemented, because an early automation mistake there doesn't just lose data, it burns a Decimal employee's warm network permanently.

### 2.3 What Capture does NOT do

It doesn't classify, doesn't score, doesn't decide relevance, doesn't write to `signals`. A raw capture with `status=PENDING` is inert until Layer 2 processes it. This separation is what lets you re-run an improved filter or classifier against everything already captured without re-scraping — directly reusing the Bible's Layer 8 Knowledge Portfolio principle (§6 v3 ENR-PORT) that acquired intelligence should be reusable, not single-use.

---

## 3. Layer 2 — Filter

**Responsibility:** decide whether a raw capture is worth turning into a `Signal`, and catch duplicates before they double-count.

### 3.1 Dedup

Two checks, cheapest first:
1. **Exact dedup** — `raw_hash` collision against existing `raw_captures` (same URL or near-identical text already seen). Reject immediately, no further processing.
2. **Fuzzy dedup against existing `Signal` rows** — the same event reported by two different sources (a bank's own press release and a news aggregator both covering the same partnership announcement) won't hash-match but should still merge, not create two signals. A simple fuzzy match (normalized title similarity + same `org_id_guess` + captured within a 72-hour window) is enough for v1; this is explicitly flagged as needing calibration over time, matching the Bible's own honesty about which layers are P1-good-enough vs. needing iteration (§6 v3's exhaustion table treats several layers as "~90%, calibration ongoing" rather than claiming completeness).

### 3.2 Relevance scoring (SIG-RELEVANCE, RELEVANCE-01/02/03)

Every raw capture that survives dedup gets scored against the Bible's four axes before promotion:
- Relevance to Decimal's solutions (does this touch lending, collections, onboarding, etc.)
- Relevance to the account's current initiatives (if any tracked)
- Relevance to the current narrative (does this fit or contradict what's already known about the account)
- Relevance to the current opportunity (if one is open)

v1 implementation: a keyword/rule-based scorer (same spirit as `signal_intel.py`'s vendor matching — deterministic, inspectable, not an LLM black box) producing a 0–1 score per axis and a combined score. Below a configurable threshold, `status=FILTERED_OUT` and the item never becomes a `Signal` — but per RELEVANCE-02, it's *retained* in `raw_captures` (Market Memory equivalent), not deleted, so a future recalibration can recover it.

### 3.3 Blocking vs. non-blocking (ENR-BLOCK-01/02)

Not every relevant item deserves equal handling speed. An RFP deadline or a competitive-closure partnership is blocking (it changes what a BD rep should do this week); a routine hiring announcement is usually non-blocking (informational, doesn't require action). The filter tags each promoted signal with a `blocking: bool` derived from `signal_type` + urgency defaults already built (RFP and COMPETITIVE_CLOSURE partnerships are blocking by construction, matching the CRITICAL urgency default already shipped). Blocking signals should be the ones that actually interrupt a rep's day (notification-worthy); non-blocking ones populate the dashboard without alerting anyone.

### 3.4 What Filter does NOT do

It doesn't decide what the signal *means* (that's Intelligence) — it decides whether the signal is real enough and relevant enough to bother interpreting. A filtered-in item is still just a fact at this point ("Bank X mentioned Backbase"), not yet a classified interpretation ("this looks like competitive closure").

---

## 4. Layer 3 — Intelligence

**Responsibility:** turn a filtered fact into an interpreted, confidence-stamped belief, and write the resulting `Signal` row.

### 4.1 The EPIS RCM stamp (EPIS-RCM-01)

Every `Signal` produced by this pipeline (automated or manual) should carry a confidence record, not just a bare fact. This is the single biggest gap identified in the earlier bottleneck analysis (§2.2, §2.5 of that doc) — today a signal from 11 months ago and one from yesterday look identical, and there's no source-reliability memory at all.

Proposed extension to `Signal` (new nullable columns, additive migration, exactly like the SIG-TENDER/SIG-PARTNER additions already shipped):

```
confidence_score       float, nullable      -- 0-1, EPIS-RCM-01
decay_category         string, nullable     -- OPERATIONAL / TACTICAL / STRATEGIC / STRUCTURAL (EPIS-HALF-01)
decay_expires_at       datetime, nullable   -- computed from decay_category + created_at
source_reliability     float, nullable      -- pulled from source_registry at capture time (EPIS-SRC-01)
```

`decay_category` is set automatically from `signal_type` at creation (rfp/tender → tactical, partnership → strategic, hiring → operational, regulatory → strategic, per the half-life table in the bottleneck analysis §2.5) — no new human input required, just a lookup table.

### 4.2 New table: `source_registry`

Implements EPIS-SRC-01 (reliability and incentive-bias as two independent scores) and EPIS-TRUST-01 (per-subsystem trust, not global):

```
source_registry
  source_name           string, pk    -- matches raw_captures.source_name
  reliability_score     float          -- accuracy track record, updated over time
  incentive_bias        string         -- self-reporting / third-party-news / regulatory / social — informs framing discount
  total_captures         int
  corroborated_count     int
  retracted_count         int          -- feeds back from Filter/Intelligence disagreements (EDGE-FP-03 pattern)
  last_updated           datetime
```

A bank's own press release and an independent news aggregator covering the same event should not carry the same weight — the press release is EPIS-SRC-01's "high reliability, high incentive-bias" case (§2.1 of the bottleneck analysis). `source_registry` is what makes that distinction persistent instead of re-litigated every time.

### 4.3 Classification (extends `signal_intel.py`, doesn't replace it)

`classify_partnership()` becomes one of several classifiers that Layer 3 runs automatically on every promoted capture of the matching type, instead of only on manual saves:
- `classify_partnership()` — already built, runs automatically now instead of only in `apply_signal_intel_fields`
- **New, P2:** a lightweight `classify_vendor_satisfaction()` stub (SIG-VSAT direction) — starts as a keyword scan for complaint/delay/dissatisfaction language near a known incumbent-vendor mention, explicitly marked low-confidence until it has real calibration data
- **New, P2:** `classify_hypotheses()` (SIG-HYP direction) — for now, this can be as simple as attaching a template hypothesis set per `signal_type` (a leadership_change signal gets pre-populated with "transformation / succession / regulatory" as competing explanations with a placeholder confidence split), which is honest about being a stub, not a full reasoning engine, but it establishes the *data shape* (competing hypotheses, not one guess) that SIG-HYP-01 requires.

The architectural point: don't try to build the full 8-stream reasoning engine at once. Build the data shape (a `SignalHypothesis` table capable of holding competing, confidence-stamped explanations) now, populate it with simple rules today, and let it get smarter later without a schema migration.

```
signal_hypotheses
  id              uuid, pk
  signal_id       fk -> signals
  explanation     text
  confidence      float          -- SIG-HYP-01, calibrated and revisable
  evidence_for    text, nullable
  evidence_against text, nullable  -- ENR-HUMAN-01's disconfirmation field, made structural instead of a form prompt
```

### 4.4 What Intelligence does NOT do

It doesn't auto-send anything, doesn't auto-notify a rep, doesn't skip human review for high-stakes classifications. See §5.

---

## 5. Automated vs. human-reviewed — the governance boundary

This is the part most likely to get skipped under time pressure, and it's the part the Bible is most insistent about (§8 v2 QC-PHIL, §18 v2 EDGE-UNK-02). Concretely, for this pipeline:

**Fully automated, no human gate:** Capture (Layer 1) and Filter (Layer 2) run unattended. A filtered-out item never bothers anyone; that's the point of the filter.

**Automated with a visible confidence flag, but not blocked:** Classification (SIG-PARTNER, SIG-VSAT stub) auto-populates and auto-saves the `Signal` row — exactly like today's manual flow, just triggered by an adapter instead of a form submit. The classification badge already shows the matched vendor for a human to sanity-check (this pattern already exists in `signal_edit.html`); nothing changes here except who triggers the save.

**Requires human confirmation before it's "real":** Anything that would trigger a notification, an automated outreach action, or a change to `AccountIntelligence.priority`/scoring inputs. This directly implements EDGE-UNK-02's default posture ("an unclassified or novel scenario routes to human review, not a guess") and QC-RISK-03's guardrail (false-negative tolerance never applies to the handful of genuinely high-stakes gates). Concretely: a COMPETITIVE_CLOSURE partnership signal can auto-populate today exactly as it does now, but if a future phase adds Slack notification on CRITICAL signals (mirroring INT-SLK), that notification step is the one place this pipeline should NOT auto-fire without a human-visible review step first — a false-positive edge case here (§2.4 of the bottleneck analysis) has a real cost if it fires wrong at scale.

**Unclassified anomaly handling (EDGE-UNK-01):** any raw capture that doesn't cleanly map to an existing `signal_type` shouldn't be silently forced into "other" — it should be flagged `status=NEEDS_REVIEW` with the raw text visible, so a human names it, and a recurring pattern of "doesn't fit anything" becomes a signal that the taxonomy itself needs a new `signal_type`, per EDGE-EPIS-01's catalogue-coverage principle already discussed in the bottleneck analysis.

---

## 6. Build order (phased, tied to the bottleneck analysis)

**P1 — Filter + Intelligence layer on existing manual data (no new scraping yet).**
This is the highest-leverage, lowest-risk next build: everything you already have manually entered gets a `confidence_score`, `decay_category`, and automatic re-classification, without touching scraper fragility or ban risk at all. Concretely: add the four new `Signal` columns (§4.1), backfill `decay_category` for existing rows via the `signal_type` lookup table, wire automatic classification to run on every save (not just partnership saves), and surface decay-based visual de-emphasis on `bank_detail.html`/`initiatives.html` (a signal past its decay window renders muted). This closes two of the three "what this means for DRIP right now" gaps flagged in the bottleneck doc without any capture automation.

**P2 — `raw_captures` + `source_registry` tables, manual form becomes an adapter.**
Restructure the manual form to write into `raw_captures` first (status auto-set to PROMOTED since a human already vetted it), so the schema is proven end-to-end before any scraper touches it. Add the dedup/relevance filter logic, even though the only "source" feeding it initially is still humans.

**P3 — SIG-REG and SIG-NEWS adapters** (lowest practical risk per the bottleneck analysis — no ban risk, no paid enrichment, mostly structured/semi-structured public pages). This is the first point where signals start arriving without anyone typing them in.

**P4 — SIG-EXEC, SIG-EVENT, SIG-VENDOR, SIG-FIN adapters**, each individually gated on having a working relevance filter (P1/P2) already in place, so adding more capture volume doesn't just add more noise to a dashboard that can't yet triage it.

**P5 — SIG-PATH / INT-LIN**, explicitly gated on building the ban-risk circuit breaker first (§4.3 INT-LIN-02), not on convenience or demand. This is deliberately last.

The ordering principle, stated once: *never automate a new capture stream before the filter/intelligence layers can handle the volume it produces* — matching the bottleneck analysis's core finding that a practical capture failure becomes dangerous specifically when nothing downstream notices it degrading.

---

## 7. Open questions (Bible-style — named, not hidden)

**OPEN-Q — Relevance scorer: rules or model?** v1 above proposes a deterministic keyword/rule scorer for relevance, matching `signal_intel.py`'s existing style. A model-based scorer (embedding similarity against Decimal's product descriptions) would generalize better but loses the inspectability that's made `signal_intel.py` easy to debug and trust. Recommend starting rule-based (P1/P2) and only reaching for a model if the rule-based version's false-negative rate (relevant items filtered out) proves too high in practice.

**OPEN-Q — Where does `raw_captures` review happen?** A `NEEDS_REVIEW` queue needs a UI surface — either a new page or a filtered view on the existing Uploads-style pattern already in DRIP. Not designed here; flagged as a P2 UI decision once `raw_captures` exists.

**OPEN-Q — Scraping infrastructure.** This document deliberately doesn't specify the scraping stack (requests/BeautifulSoup vs. a managed scraping service vs. RSS-only where available) — that's an implementation choice for P3, not an architecture decision, and should be made per-source based on what each site actually allows.
