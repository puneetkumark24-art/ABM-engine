# Signal Source Bottleneck Analysis
### Practical and theoretical limits on sourcing, deciphering, and filtering signal — DRIP / ABM Business Logic Bible

---

## Framing

The Sourcing summary covered *what* the 12 signal streams are and where the 7 coverage gaps sit. This document covers *why sourcing signal is hard even when a source exists* — the two different kinds of limits the Bible's own architecture (Sections 4, 6, 8, 15, 18) treats as first-class problems, not implementation detail.

Practical bottlenecks are execution-level: a scraper breaks, LinkedIn bans an account, an API costs money, Arabic text doesn't parse. These are the failures you'd expect from building the thing.

Theoretical bottlenecks are epistemic-level: even when every source works perfectly, the engine still doesn't *know* things with certainty, sources lie about their motives even while reporting facts correctly, confidence decays at different rates for different fact types, and the engine can be wrong about scenarios it has never seen before. These are failures baked into the nature of intelligence-gathering itself, not into any particular tool.

The Bible treats the second category as more dangerous than the first, because practical failures are visible (a scraper throws an error) while theoretical failures are silent (the engine confidently acts on a stale, biased, or unverified belief and nobody notices until it's wrong).

---

## Part 1 — Practical Bottlenecks

### 1.1 Platform ban risk (SIG-PATH, INT-LIN)

LinkedIn is both the richest source for SIG-PATH (connection-to-Decimal resolution) and the most fragile. Automation that breaches LinkedIn's platform policy gets banned, and a ban destroys an *irreplaceable* warm channel — every P1 edge (Decimal-employee-to-target 1st-degree connection) anchored on that account breaks simultaneously, not gracefully.

The Bible's answer is not a rate limit alone but a ban-risk circuit breaker: caps are set below LinkedIn's human-plausible thresholds, and early-warning signals (captcha challenges, view restrictions, accept-rate collapse, withdrawal spikes) trip an automatic pause *before* the irreversible ban, because by the time a static rate limit would catch the problem it's often already too late. New accounts also warm up gradually rather than sending at full volume immediately.

The practical cost: this means SIG-PATH throughput is deliberately capped below what's technically possible, and a banned account isn't just lost capacity — it's a permanent loss of whatever warm relationships were routed through it. There is no scraping "harder" through this bottleneck; it's a hard ceiling by design.

### 1.2 Scraper fragility (SIG-NEWS, SIG-EXEC, SIG-VENDOR, SIG-EVENT)

Career-portal redesigns, news-site layout changes, and anti-bot measures on bank/regulator sites break scrapers silently unless something is watching for it. A scraper that returns zero results because a site redesign broke a CSS selector looks identical, from the outside, to a genuinely quiet week for that bank — which is exactly the kind of failure the Bible's FAIL-CASC-01/02 (cascading failure theory) and FAIL-LAT-01 (detection latency) rules are built to catch: a broken scraper is a *dependency failure* that cascades into "no signals surfaced," and if detection latency (MTTD) is long, the account looks falsely cold for weeks.

This is compounded for SIG-VENDOR and SIG-EXEC specifically because they depend on unstructured pages (press pages, bios, LinkedIn profiles) rather than structured feeds — there's no API contract to break cleanly against; the failure mode is a silently degraded extraction, not a clean error.

### 1.3 Arabic NLP and bilingual source material

A meaningful share of KSA bank signal — SAMA circulars, Arabic-language press releases, local news coverage — is Arabic-first, sometimes Arabic-only. Generic English-tuned NLP (entity extraction, sentiment, relevance scoring) degrades on Arabic text: named-entity recognition misses transliterated names, sentiment models miscalibrate on Arabic phrasing conventions, and keyword-based classifiers (like the SIG-PARTNER vendor-matching just built) need an Arabic vendor-name registry alongside the English one or they simply won't fire on Arabic-language partnership announcements.

This is a real gap in what was just built: `signal_intel.py`'s `classify_partnership()` only matches English vendor names. An Arabic-language MOU announcement naming Backbase in Arabic script would not classify today.

### 1.4 Rate limits and enrichment cost (INT-ENR, API)

Apollo → Clearbit → Clay is a fallback chain specifically because no single provider has complete KSA banking coverage, but every fallback hop costs money and rate-limit budget. The Bible's Information Economics layer (Section 6 v3) treats this explicitly as an economic constraint, not a technical one: every enrichment call is an investment decision, and Layer 6 (ENR-ECON) ties spend to the *expected value* of the account, not a flat per-tier budget — a $5M flagship account justifies deeper enrichment spend than a $50K commercial account even at the same HOT tier.

Practically, this means enrichment throughput is gated by a real budget ceiling, and unbounded enrichment ("just enrich everything") is explicitly called out as economically irrational (ENR-COMP-02: stop when Expected Information Gain < Acquisition Cost).

### 1.5 Deliverability as a scarce, reputation-managed resource (INT-EML)

Email is not a free channel once you count reputation. SPF/DKIM/DMARC misconfiguration routes outreach to spam regardless of content quality; domain warmup means new sending domains can't send at volume immediately; and bounce/complaint telemetry must gate further sending or reputation degrades silently and compounds. This is a slow-moving bottleneck — the damage from over-sending doesn't show up immediately, it shows up as declining inbox placement weeks later, which is part of why the Bible treats deliverability as "a strategic layer, not a technical afterthought."

### 1.6 Orchestration and retry-storm risk (INT-ORC, FAIL)

Every workflow step must be idempotent because n8n retries and re-runs steps on failure — a non-idempotent step risks double-sending outreach or double-writing CRM records on retry, which is arguably worse than the original failure (it corrupts the system of record, the one failure category the Bible calls out as uniquely trust-destroying). Transient failures (timeouts, 5xx) get exponential backoff specifically to avoid worsening an already-struggling dependency with a retry storm.

### 1.7 What's actually built vs. what the Bible specifies

Worth naming directly: the DRIP dashboard as it exists today (manual signal entry, SIG-TENDER/SIG-PARTNER just added) implements almost none of the automated sourcing infrastructure described above — there's no scraper, no LinkedIn automation, no enrichment chain, no email execution layer. Every signal currently enters the system through a human typing it into a form. This isn't a flaw in what was built — manual entry was the deliberately chosen zero-infra starting point — but it means the practical bottlenecks above are not yet DRIP's problem; they become DRIP's problem the moment any of SIG-NEWS/SIG-EXEC/SIG-HIRE/INT-LIN/INT-ENR get automated. Worth keeping in mind when prioritizing what to automate next: automating SIG-PATH (LinkedIn) inherits ban risk on day one; automating SIG-NEWS inherits scraper fragility and Arabic NLP on day one.

---

## Part 2 — Theoretical Bottlenecks

These are the harder problems, because they don't go away when the practical infrastructure gets built — they get *more* dangerous, because a fully-automated pipeline can act on a bad belief faster and with less human friction than a manual one.

### 2.1 Source trust vs. source motive are not the same axis (EPIS-SRC-01/02)

A source can be highly *reliable* (its facts check out) while being highly *biased* (why it publishes distorts how it frames what it reports). A bank press release is usually accurate about the fact of an event — a partnership was signed, an executive was hired — while being incentivized to frame that event favorably. Collapsing reliability and incentive-bias into one "trust score" makes the engine treat a biased framing as neutral truth. The Bible keeps these as two independent scores for exactly this reason: a press release can score high-reliability, high-bias simultaneously, and only the framing (not the underlying fact) should be discounted.

This matters directly for SIG-PARTNER: a bank's own press release about "signing Backbase" is a reliable fact (the partnership likely happened) but a biased framing (it will describe the deal in the most flattering terms available, never as "we're replacing our old vendor because it failed us") — the COMPETITIVE_CLOSURE interpretation the classifier now applies is Decimal's own analytical layer on top of the source's self-serving framing, not something the source itself would ever say.

### 2.2 Coverage caps confidence — most of what matters is invisible (EPIS-COV-01/02)

The events that actually drive enterprise purchasing decisions — budget meetings, internal procurement rejections, board disagreements, a CTO's private frustration with an incumbent vendor — are almost never publicly observable. An engine that scores confidence only on what it *can* see is confidently wrong exactly when the decisive action is happening somewhere it can't reach. The Bible's answer is to make this explicit: every account carries an Intelligence Coverage Score (observable share of the buying system), and that score mechanically *caps* how confident any recommendation about that account can be — the engine is architecturally prevented from being more certain than its coverage allows.

Applied to Sourcing: a bank with heavy LinkedIn/press coverage but zero internal-network signal (no P1/P2 path, no vendor-satisfaction chatter) should never be treated with the same confidence as a bank where Decimal has a warm internal contact reporting directly. Today, nothing in DRIP tracks or surfaces this distinction — a signal entered manually carries the same implicit weight regardless of how it was actually sourced.

### 2.3 Noise-to-signal and the relevance gate (SIG-RELEVANCE)

Thousands of facts arrive; most are noise. The Bible treats relevance as a *distinct* judgment from scoring — not "is this account generally active" but "does this specific item touch Decimal's solutions, this account's current initiatives, the current narrative, or the current opportunity" — and requires that judgment to run *before* an item is allowed to feed hypotheses or scoring, specifically so irrelevant volume can't inflate an account's apparent activity level. A bank sponsoring a football tournament and a bank issuing an RFP are both "signals" in the loosest sense; without an explicit relevance gate they get weighted as if comparable.

This is the theoretical version of a very practical problem: as more sourcing streams get automated, the volume of raw material rises far faster than the volume of decision-relevant material, and without a relevance gate the system either drowns a BD rep in noise or — worse — silently dilutes the signal that actually matters into a sea of things that technically happened but change nothing.

### 2.4 Verification lag and the false-positive edge (EDGE-FP)

A source reports "bank under regulatory investigation." The system reacts — pauses outreach, escalates for review. Weeks later the report turns out to be a misidentified entity or an unconfirmed rumor. The Bible's Edge Case Epistemics section (18 v2) treats this as a named failure mode, not a rare accident: every low-confidence trigger gets a mandatory verification window (48–72 hours depending on severity) during which the response stays in effect while the claim is actively checked against corroborating sources, and if it fails to corroborate, the scenario is marked *retracted* — not silently closed — and the retraction feeds back into that source's own reliability score.

The asymmetry worth naming: acting on an unverified signal costs a real opportunity (paused outreach, spent reviewer attention, interrupted relationship momentum) even when the signal turns out to be false, and that cost is real whether or not anyone tracks it. The Bible insists on tracking it explicitly (EDGE-FP-05) specifically because a catalogue that fires confidently and wrongly at scale has a real, measurable price that's invisible unless someone counts it.

### 2.5 Semantic half-life — not all signal decays at the same rate (EPIS-HALF, ENR-DECAY)

A generic "signals older than 30 days are stale" rule mis-ages everything equally. A job posting is meaningfully stale in 30 days; a vendor contract signal is still load-bearing a year later; an organization's core identity facts barely decay across 5 years. The Bible defines four explicit decay tiers — Operational (7–30d, contact-level facts), Tactical (30–90d, activity-level), Strategic (6–12mo, priority-level), Structural (3–5y, identity-level) — and requires every fact to be tagged with its category at the moment it's acquired, not aged on a single global clock.

Applied directly to what was just built: an RFP deadline is Tactical-to-Strategic (it matters until the deadline passes, then becomes historical); a partnership classification is Strategic (a competitive-closure signal from 8 months ago is still meaningfully "the vendor evaluation may be closing" unless something has since changed it). Neither `Signal` field in DRIP currently carries a decay category — a signal from 11 months ago renders in `bank_detail.html` identically to one from yesterday, with no visual or scoring distinction.

### 2.6 Diminishing returns and the temptation of the complete dossier (ENR-COMP, ENR-STOP)

The instinct with any intelligence system is to keep researching until the dossier is "complete." The Bible calls this economically irrational: the first confirmed contact at an account is worth a lot, the eighth confirmed contact for the same buying committee is worth very little, and continuing to enrich past the point of diminishing returns is spending scarce budget on information that won't change any decision. The explicit stopping rule (ENR-STOP-01) is deliberately narrow — buying-committee coverage ≥80%, ≥2 reachable contacts, ≥1 resolved outreach path — and *more* research past that point requires a named justification, not just "more would be nice."

This is a useful discipline to apply to Sourcing prioritization directly: the question for any new stream shouldn't be "would this add more signal" (almost anything would) but "does the account currently lack decision-relevant signal that this stream would supply" — which is closer to the actual logic that picked SIG-TENDER and SIG-PARTNER as the first two builds (both fill a *blocking* gap — deal-stage-relevant information the account currently has zero mechanism to capture — rather than adding volume to a stream that already has coverage).

### 2.7 Researcher bias — the same traps apply to humans typing signals into a form (ENR-HUMAN)

Availability bias (research what's easy to find, not what matters), confirmation bias (favor evidence supporting the existing hypothesis), completion bias (fill in fields rather than resolve real uncertainty), and freshness bias (overweight whatever was learned most recently) are named explicitly as failure modes of *human* researchers, not just AI agents. The countermeasure the Bible specifies — requiring every research output to explicitly answer "what would disprove the current working hypothesis" — is a discipline, not a tool; it applies exactly as much to a BD rep manually typing a signal into DRIP's `signal_new` form as it would to an automated agent.

Concretely: today's signal-entry form has no field that asks "what would make this classification wrong" — a rep entering a partnership signal sees the auto-classified COMPETITIVE_CLOSURE badge and, by default, will tend to confirm rather than actively look for the disconfirming case (evidence the bank is evaluating Backbase alongside three others and hasn't decided anything). Nothing currently in the DRIP form structurally invites that check.

### 2.8 Irreversibility — not all mistakes are equally recoverable (QC-PHIL, QC-RISK)

A rare but catastrophic failure deserves more protection than a frequent but trivial one, because severity should be measured as probability × magnitude × *reversibility*, not raw frequency. A message sent to the wrong contact is recoverable in the sense that you can apologize and move on; a message that reveals confidential per-account vendor intelligence across accounts, or a signal that triggers a wrongful competitive-closure escalation to a bank that was never actually evaluating a competitor, does lasting damage to trust that isn't undone by a correction.

Applied to what was just built: SIG-PARTNER's auto-classification is a *low-stakes* irreversibility case today precisely because it's advisory (a human confirms it on the form, per the design notes in `signal_intel.py`) — but if this classifier ever gets wired into an automated escalation (e.g., auto-notifying a sales lead the moment COMPETITIVE_CLOSURE fires), the irreversibility profile changes completely, and the false-positive-edge discipline (2.4 above) would become mandatory, not optional.

### 2.9 Repeat failure and the difference between an incident and a pattern (FAIL-REPEAT, FAIL-ANTI)

A scraper break, a misclassified signal, a LinkedIn ban-risk trip that recovers and then trips again a week later on the same pattern are not independent incidents — recurrence is itself evidence that whatever was learned the first time didn't actually prevent the second. The Bible's deepest claim in this area is that the highest form of recovery converts a breakdown into a new capability (a new detection rule, an automated pre-check, a predictive signal) rather than simply closing the incident — a system that resolves many individual failures but generates no capability improvements is, by the Bible's own success metric, underperforming even with a clean-looking dashboard.

### 2.10 The catalogue doesn't know what it doesn't know (EDGE-EPIS)

The deepest point in the entire Edge Epistemics section, worth stating plainly because it applies to the Signal Source Registry itself: a list of 12 known signal streams and 7 known coverage gaps presents itself with the same confident tone regardless of how much of reality it actually covers. The Bible's answer is to track an aggregate coverage metric for the catalogue itself — the rate of genuinely unclassified events relative to total signal-triggering events — because a rising rate of "something happened that doesn't fit any of our 12 streams" means the taxonomy's own coverage is declining, even though none of the 12 existing streams changed. Nothing currently measures this for DRIP's signal taxonomy; it would require deliberately logging signals that don't fit any current `signal_type` rather than forcing them into the nearest available bucket (which is what an "other" catch-all silently does today).

---

## Part 3 — Where Practical and Theoretical Bottlenecks Compound

The two categories aren't independent — the dangerous cases are where a practical failure produces a theoretical one silently.

A scraper that breaks (practical, §1.2) doesn't just lose data — it silently degrades that account's Intelligence Coverage Score (theoretical, §2.2), which should mechanically lower confidence in any recommendation about that account, but only if something is actually computing and applying that coverage score. If nothing tracks coverage explicitly, the practical failure just looks like "the account went quiet," and the engine (or a human reading the dashboard) draws the wrong conclusion — not "we lost visibility" but "nothing is happening here" — which is the exact confidently-wrong failure mode Section 4's EPIS layer exists to prevent.

Similarly, a LinkedIn ban (practical, §1.1) doesn't just cost the automation account — it silently invalidates every SIG-PATH P1 edge that account anchored, and unless a path-break event fires (INT-LIN-07), the system keeps recommending outreach through a channel that no longer exists.

This is the strongest argument for why Sourcing, Deciphering, and Filtering can't really be sequenced as cleanly separate stages the way the earlier framing suggested — a sourcing-layer failure that goes undetected corrupts the deciphering layer's confidence calculations invisibly, and no amount of good filtering logic downstream can recover information that was silently lost or degraded upstream.

---

## Part 4 — What This Means for DRIP Right Now

Three concrete gaps, ranked by how directly they connect to what was just built:

**No decay/freshness model on `Signal`.** Every signal — a tender deadline from yesterday and a partnership classification from 11 months ago — renders with equal visual weight. A cheap first step: tag `signal_type` with an implied decay tier (rfp/tender → tactical, partnership → strategic, hiring → operational) and visually de-emphasize signals past their expected half-life on `bank_detail.html` and `initiatives.html`.

**No source-reliability tracking.** `Signal.source` is a free-text field today ("Contact call," "News article") with no memory of whether that source has been reliable before. Even a simple manual field — did this source's last claim corroborate — would start building the EPIS-SRC-01 discipline without needing full automation.

**No coverage signal at the account level.** There's currently no way to see, at a glance, whether a bank's signal profile is thin because nothing is happening or thin because DRIP simply hasn't looked — the two look identical on `bank_detail.html` today. A simple proxy (days since last signal of any type, count of distinct signal_types ever logged for this account) would start to make that distinction visible.

None of these require new infrastructure — they're refinements to what already exists, in the spirit of the Bible's insistence that the epistemic layer matters as much as the acquisition layer.

---

*Sources: ABM Business Logic Bible Section 4 (Integrations, APIs, Failure Modes & Engine Epistemology — EPIS, INT-SIG, INT-ENR, INT-LIN, INT-EML, INT-CRM, INT-ORC, API, FAIL, OBS), Section 6 v3 (Information Economics), Section 8 v2 (Trust Preservation & Irreversibility Management), Section 15 v2 (Reliability, Resilience & Antifragility), Section 18 v2 (Edge Case Epistemics), and the ABM Signal Source Registry / Coverage Gaps documents read in the prior Sourcing pass.*
