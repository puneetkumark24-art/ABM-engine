# Match Report — Built Code vs. Blueprint: HubSpot Replica & Mailchimp Replica

**What this compares:** the enterprise blueprint's Module 06 (CRM Engine — HubSpot
replica) and Modules 07 + 11 (Marketing Automation + Email Delivery — Mailchimp
replica) against what is **actually implemented in `drip_platform/` today**
(after Phases 7–9). Verified by reading the code, not the plans: 24 core tables
in `models.py`, 36 extension tables in `models_ext.py`, 18 dashboard templates,
53/53 + 30/30 tests green.

Status legend: ✅ built & tested · 🟡 partial (real code, incomplete vs. spec) ·
❌ not built (spec only).

---

## 1 · HubSpot Replica (Blueprint Module 06 — CRM Engine)

### Core object model — the part that's genuinely there

| HubSpot capability | Blueprint spec | Built in drip_platform | Status |
|---|---|---|---|
| Companies / Accounts | `account` + hierarchy | `organizations` (+ parent_org_id, aliases, Arabic names, tech-stack columns) + `account_intelligence` extension + `org_type_tags` multi-classification | ✅ richer than HubSpot's default |
| Contacts | `contact` + persona/authority | `persons` — 40+ fields: persona, seniority, decision_weight, consent, outreach state, BD-flow placement, career history JSON | ✅ |
| Deals / Opportunities | `deal` w/ pipeline+stage refs | `opportunities` (stage, probability, value, champion) | 🟡 deals exist; **no configurable pipelines/stages** (stage is free text, no entry/exit criteria, no weighted forecast) |
| Activities (universal) | `activity` polymorphic | `activity_log` — email/linkedin/phone/whatsapp/meeting/demo/rfp/poc, outcome, next_action | ✅ |
| Tasks | dedicated task object | via `activity_log` type=task (rule action creates them) | 🟡 no due-date/assignee object |
| Meetings / Calls / Notes | typed activities | covered by `activity_log` + notes/Text fields | 🟡 |
| Buying Committee | `committee_member` roles ×product | `buying_committee_members` (role, engagement, per-product) | ✅ table + data; auto-mapping logic ❌ |
| Relationship Graph | typed, scored edges | `org_relationships` + `person_relationships` (type, strength, confidence, source, dates) | ✅ |
| Custom Objects | polymorphic `crm_object` registry | — | ❌ |
| Properties framework (custom fields) | `property` defs + validation | — (columns are fixed) | ❌ |
| Lead Status / Lifecycle | lifecycle enum + transitions | `account_intelligence.lifecycle_status`, `persons.tier/warmness` | 🟡 fields exist; no transition rules |
| Owners / Teams / Permissions | RBAC + row-level | `app_users`/`app_roles` RBAC deny-by-default + wildcards + quotas (Phase 9, tested) | 🟡 role-level yes; row-level/teams ❌ |
| Views / Lists / Segments | saved views, static+dynamic | `audiences` (static lists + dynamic JSON-filter segments, tested) | 🟡 exists in Marketing; not yet a generic CRM "saved view" |
| Duplicate detection | hard keys + similarity | `merge_candidates` + `detect_duplicates()` (linkedin/email/name-similarity, tested) | ✅ detection |
| Merge engine | re-point associations, keep history | — | ❌ (candidates surfaced, merge is manual) |
| Audit log | every mutation, before/after | `audit_log` + Phase-9 `admin.audit()` hook | 🟡 exists; not yet automatic on every mutation |
| AI Timeline | unified system-authored timeline | raw material exists (`activity_log`, sequence events, delivery events) | ❌ assembler not built |
| Engagement score (contact) | rollup from events | delivery events captured; rollup to Person ❌ | ❌ (the feed exists, the aggregation doesn't) |
| Next-Best-Action surfacing | from Intelligence Engine | — (Intelligence is PARTIAL) | ❌ |
| Forecasting | weighted pipeline forecast | — | ❌ |
| Cross-object search | FTS | API filters per router only | ❌ |
| Dashboards / UI | 11 role dashboards | 18 Flask templates: bank detail, connection map, flow, initiatives, persons, scoring, uploads, vendors | ✅ substantial (different shape than spec) |

**HubSpot-replica verdict:** the **data spine is real and in places richer than
HubSpot** (relationship graph, committee-per-product, Arabic fields, BD-flow
placement) — roughly **~60% of the core CRM object model** is live. What's
missing is HubSpot's *configurability layer* (custom objects, properties,
pipeline/stage editor, saved views, merge, forecasting) — the parts that make it
a product rather than a schema. Biggest single gap: **Pipeline Engine (19)** —
`pipelines`/`stages` tables with transition rules + weighted forecast.

---

## 2 · Mailchimp Replica (Blueprint Modules 07 Marketing + 11 Delivery)

### The moat — the event pipeline (this was the whole point)

| Mailchimp capability | Blueprint spec | Built in drip_platform | Status |
|---|---|---|---|
| Audiences / Lists | static lists | `audiences` kind=list + `audience_members` | ✅ tested |
| Dynamic segments | JSON-filter re-evaluated on read | `audiences` kind=segment + operator engine (eq/ne/gt/contains/…) | ✅ tested |
| Suppression list | global, auto-fed | `suppressions` — enforced at **send AND sequence enrollment** (Phase-9 gate) | ✅ tested |
| Campaigns | audience+template+schedule | `email_campaigns` + `email_messages` per recipient | ✅ |
| A/B testing | variants + auto-winner | variant split round-robin + per-variant report | 🟡 split ✅; significance/auto-winner ❌ |
| Merge tags / personalization | {name} etc. + fallbacks | `templates` placeholders + QC catches unresolved tags | 🟡 basic |
| Open/click/bounce tracking | pixel + redirect + webhooks | **normalized `delivery_events` + webhook ingest with replay dedup (incl. within-batch — bug found & fixed)** | 🟡 event pipeline ✅; live pixel/redirect endpoints ❌ (no real sending yet) |
| Bounce/complaint handling | auto-suppress + reputation | bounce/complaint/unsub ⇒ **auto-suppression** (tested) | ✅ the logic; reputation/IP mgmt ❌ |
| Automation / drip | triggers + multi-step | **Sequence Engine (Phase 7: 5-touch, pause-on-reply, account-centric)** + Rules Engine + Workflow Engine | ✅ arguably beyond Mailchimp |
| Transactional email | event-triggered single sends | `delivery.enqueue()` (idempotent by message_id) | ✅ (dry-run) |
| Template builder / drag-drop editor | GrapesJS-class UI | `templates` table + AI generator (offline, QC'd) | ❌ UI; 🟡 content |
| AI email + subject generator | governed generation | `ai_generations` — anonymized, QC'd, c-suite human gate | ✅ tested |
| Spam checker | preflight | QC covers placeholders/leaks/length only | 🟡 |
| Landing pages / Forms | hosted + submissions→CRM | `form_defs`/`form_submissions`/`landing_pages` — consent-enforced upsert into `persons` (tested) | 🟡 records+pipeline ✅; public hosting/renderer ❌ |
| Preference / unsubscribe center | one-click, global | `unsubscribe()` ⇒ suppress + consent=denied + do_not_contact (tested); Phase-1 HMAC tokens exist in decimal_abm | ✅ logic |
| Scheduling / timezone | timezone + STO | **KSA send-window (Sun–Thu, Ramadan blackout)** enforced in sequences + delivery | ✅ KSA; per-recipient STO ❌ |
| Deliverability: SMTP/MTA | Mandrill adapter + failover | transport interface with **only `dry_run` registered — API hard-locks it** | ❌ real transport (deliberate: your VPS/ngrok webhook decision gates it) |
| IP warming / domain auth (DKIM/SPF) | warmup curves, auth checks | — | ❌ |
| Reports / analytics | opens/clicks/heatmaps | `campaign_report()` per-variant + `metric_events` + funnels | 🟡 heatmaps ❌ |
| Engagement score → account scoring | feeds Reachability 20% | events captured; **rollup into `account_scores` not wired** | ❌ the last mile |

**Mailchimp-replica verdict:** the analysis said Mailchimp's real moat is the
**event pipeline, not the compose UI** — and that pipeline (send queue →
normalized events → webhook ingest → auto-suppression → per-variant reporting)
is **built and tested, ~70% of the moat**. What's deliberately absent is the
real MTA (Mandrill adapter + public HTTPS webhook — blocked on your
infrastructure decision) and the builder UI. The single highest-value missing
wire: **engagement rollup → `account_scores.reachability`** — the loop the
original bug history flagged as never closed. It's now a small job because both
ends exist.

---

## 3 · Where the built system EXCEEDS both replicas

- **Compliance spine** neither product has natively: consent enforced at
  enrollment *and* send, account-centric pause (one reply silences a whole
  bank), c-suite human-review gate, KSA calendar, PII anonymization before LLM.
- **Intelligence layer**: signals with confidence/decay (EPIS), scoring formula
  (Bible-exact, T-SCORE-1 verified), exec briefs that exclude decayed intel.
- **Relationship graph + BD-flow placement** — HubSpot models this poorly.
- **Rules + Workflow + Sequences as three coordinated engines** with a shared
  event bus — the n8n/Customer.io layer inside the same database.

## 4 · Priority gaps to close (ranked by leverage)

1. **Engagement rollup → account_scores.reachability** (closes the Mailchimp loop; both ends exist).
2. **Pipeline Engine**: `pipelines`/`stages` config + weighted forecast (biggest HubSpot gap).
3. **Merge engine** on top of the existing duplicate detection.
4. **Contact AI timeline assembler** (activity_log + sequence events + delivery events already hold the data).
5. **Mandrill transport + public webhook** — unblocks real tracking pixels/redirects (needs your VPS/ngrok call).
6. Custom properties framework, saved CRM views, A/B auto-winner, STO — the productization tier.

**Bottom line:** HubSpot replica ≈ **60% of the core object model** live (schema
often richer, configurability layer missing). Mailchimp replica ≈ **70% of the
moat** live (event pipeline + automation done; real MTA + UI deliberately
gated). Everything above is verified against code, with the two replicas'
behaviour covered by the 53-check Phase-9 suite.
