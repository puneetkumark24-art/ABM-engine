# Phase 11 — Native Tracking Stack + Deliverability + AI Decision Engine

Implements the capability layer from the "collections of capabilities, not
products" architecture: the full Mailchimp-style tracking stack owned natively,
the deliverability engine, the analytics rate card, the AI feedback loop —
and the capability neither HubSpot nor Mailchimp ships: an **AI Decision
Engine** that chooses every next touchpoint dynamically instead of static
"wait 3 days" workflows. This is the autonomous-ABM-operating-system layer.

## Test gate — green on BOTH databases

| Suite | SQLite | PostgreSQL 16.2 |
|---|---|---|
| test_sequence_engine.py | 30/30 | 30/30 |
| test_platform_services.py | 53/53 | 53/53 |
| test_engine_e2e.py | 30/30 | 30/30 |
| **test_tracking_decision.py (new)** | **29/29** | **29/29** |
| **Total** | **142/142** | **142/142** |

Migration chain now ends at `b8d5f3a2c6e9` (17 migrations, 71 tables on PG).

## 1 · Native tracking stack (`services/tracking.py` + `/t/*` endpoints)

Exactly the six mechanisms you specified:

1. **Pixel tracking** — `GET /t/o/{message_id}.gif` serves a real transparent
   1×1 GIF and records the open. **Deduped per message/day** so Apple
   Mail/Gmail image-prefetch doesn't stack fake opens; opens are flagged
   "approximate" in the rate card, clicks weighted higher everywhere.
2. **Link tracking** — `prepare_email()` rewrites every href to
   `/t/c/{token}` (HMAC-salted tokens). First request hits our server → click
   logged → **HTTP 302** to the real URL. Verified: original query string
   preserved, UTM appended.
3. **Landing tracking** — `GET /t/js` serves `tracking.js` (page views, 90%
   scroll, PDF/doc downloads, pricing-link clicks, `window.dripTrack()` custom
   events) beaconing to `POST /t/e`.
4. **Cookies** — `drip_vid` visitor cookie set on click redirect; anonymous
   web activity accumulates on the visitor and **backfills onto the Person**
   the moment a form identifies them (`/t/identify`). Verified.
5. **UTM** — utm_source/campaign/medium/content/persona stamped on rewritten
   links and captured on every web event.
6. **Event stream** — everything lands in `delivery_events` / `web_events`,
   flows into engagement rollup → account score → automation triggers.
   The full HubSpot chain (sent → opened → clicked → visited → downloaded →
   pricing viewed → score updated) passes as one test.

## 2 · Deliverability engine (`services/deliverability.py`)

Domain health (DKIM/SPF/DMARC gates — unauthenticated domains cannot send),
7-stage **warmup schedule** with enforced daily caps, rolling **reputation**
from 30-day bounce/complaint rates (thresholds 5% / 0.2%), `can_send()` volume
gate for real transports, and the full **rate card**: delivery, bounce, open,
CTR, **CTOR**, spam, unsubscribe, reply rates. Amazon SES is the encoded
recommendation for the first real transport adapter — one `register_transport()`
call when you're ready; the gate and warmup logic are already waiting for it.

## 3 · AI Decision Engine (`services/decision.py`) — the differentiator

`decide(person)` assembles live features — engagement score, click recency,
**pricing views / downloads (web intent)**, live high-urgency signals, tier,
buying-stage estimate, channel availability — and returns a logged, **fully
explained** decision: what to do, when, through which channel, with what
content hint, at what confidence.

v1 policy (deterministic, auditable; pluggable LLM/ML hook via
`register_policy()`):

| Situation | Decision (verified by test) |
|---|---|
| Replied | `notify_sales` — machine steps back |
| C-suite | `hold_human` — **hard stop, overrides any policy** |
| Viewed pricing | `suggest_meeting` in 2h — don't drip at high intent |
| Clicked <24h ago | `send_email` follow-up in 4h on the clicked topic |
| HOT account + live signal | signal-triggered email now |
| Zero engagement + has LinkedIn | **channel switch** to LinkedIn |
| Compliance-blocked | `wait` — gates pre-empt the policy entirely |

`apply_decision()` reschedules the person's sequence enrollment dynamically —
replacing the static cadence with behaviour-driven timing. Every decision is a
`decision_log` row with reasons and inputs: autonomy with an audit trail.

## 4 · AI feedback loop (`VariantPerformance`)

Campaign results fold into per-variant rolling scores (replies ×10, meetings
×20, clicks ×3, opens ×1); `choose_variant()` is **epsilon-greedy** (85%
exploit best, 15% explore) — verified that the better subject wins most picks
while exploration continues. Prompt → email → performance → better subject/CTA.

## Bugs the tests caught (fixed)

1. Pixel open didn't flip a `queued` message's status.
2. `VariantPerformance` counters were None before first flush.
3. (Postgres) older suites' metadata missing Phase-11 tables → FK drop errors.

## Apply on your machine

```bash
cd drip_platform
alembic upgrade head        # -> b8d5f3a2c6e9
python tests/test_tracking_decision.py    # 29/29 (plus the other three suites)
uvicorn main:app --reload
# then e.g.:
#   POST /decide/{person_id}         -> explained next-best-touch
#   GET  /deliverability/rates       -> full rate card
#   GET  /t/js                       -> drop into any landing page
```

**Deployment note:** the `/t/*` endpoints are what recipients' mail clients and
browsers hit — they are the concrete thing that needs your **public HTTPS
domain** decision (VPS vs ngrok). Until then everything works locally and in
tests; no real mail leaves regardless (dry-run transport only).
