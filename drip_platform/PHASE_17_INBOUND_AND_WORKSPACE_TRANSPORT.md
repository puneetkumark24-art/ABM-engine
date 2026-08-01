# Phase 17 — Inbound Capture + Workspace Transport (and one corrected recommendation)

Closes the last structural gap in the Phase 11 tracking stack: **email replies
never reached ACC-001**, and **no real transport could legally be enabled**.

## Test gate

| Suite | SQLite | Notes |
|---|---|---|
| test_sequence_engine.py | 30/30 | unchanged |
| test_platform_services.py | 53/53 | unchanged |
| test_engine_e2e.py | 30/30 | unchanged |
| test_tracking_decision.py | 29/29 | unchanged |
| **test_inbound.py (new)** | **18/18** | bounce, reply, cascade, idempotency, MIME |
| **Total** | **160/160** | |

No migration. Phase 17 adds no tables — it writes into `delivery_events`,
`suppressions` and `persons.replied`, all of which already exist.

---

## 1 · The bug this phase exists to fix

`seq_engine.pause_on_reply()` implements ACC-001: a reply pauses the replier
**and every other active enrollment at that bank**. It was reachable from three
places — `linkedin.register_reply()`, `sales_engagement` (manual logging), and
`POST /sequences/pause-on-reply`.

None of them is email.

So on the primary outreach channel, the Decision Engine's flagship rule —
*"Replied → notify_sales, machine steps back"* — only fired if a human
remembered to log the reply by hand. In practice that means the platform would
have kept auto-touching a bank that had already written back. For account-based
outreach to ~25 KSA banks, that is the single most damaging thing it could do.

`services/inbound.py` closes it: a detected email reply flips the message to
`replied`, fires the same ACC-001 cascade LinkedIn already enjoyed, and
publishes `email.reply.received`. Nothing downstream changed — engagement
rollup, decision engine and rate card all consume it as-is.

## 2 · Bounce and reply capture without a public HTTPS endpoint

Phase 11's deployment note flagged the public-host decision (VPS vs ngrok) as
the open blocker. `ingest_webhook()` needs somewhere to be POSTed to.

Workspace and M365 don't send webhooks at all: bounces arrive as DSN mail and
replies arrive as replies. So `poll_once()` reads the mailbox **outbound**, on
the scheduler. No inbound port, no tunnel, no always-on host — it runs from the
laptop, and if the machine sleeps for two days the mail is still waiting.

That removes the blocker for **bounce and reply** events. The `/t/*` pixel and
click endpoints still need a public host; this does not change that.

- RFC 3464 DSN parsing, **plus a heuristic fallback** — many real MTAs emit
  non-conforming bounces, and a structured-only parser silently misses them and
  keeps mailing dead addresses. Covered by `test_unstructured_bounce_*`.
- Hard bounce → immediate suppression (DEL-003). Soft bounce → counted;
  suppressed only after 3 in 30 days. One full mailbox is not a dead address.
- Auto-replies classified and **excluded from engagement**. An out-of-office is
  not interest; scoring it would corrupt both the engagement rollup and
  `reply_rate` on the rate card.
- Idempotent via `provider_event_id = inbound:{uid}` — the same guarantee
  `ingest_webhook` gives for replayed webhooks.

**A bug the tests caught:** Python's `email` parser accepts arbitrary bytes and
returns a Message, so corrupt mail fell through to the `reply` branch — a false
reply that would halt outreach to an entire bank. Messages with no parseable
sender are now classified `unknown` and skipped. A false reply costs far more
than a missed one.

## 3 · Transport: corrected recommendation

`deliverability.py` recommended **Amazon SES** as the first real adapter, and
`delivery_ext.py` ships SES and Mandrill adapters. For transactional mail that
is right. For the cold 1:1 B2B outreach this platform runs it is an AUP problem:

> SES, Mandrill, SendGrid, Mailgun, Postmark and Resend all prohibit
> unsolicited/cold outreach. They share IP pools, so one tenant's complaint
> rate degrades every other tenant — which is why they police it hard.

SendGrid was already flagged as an AUP violation earlier in this project.
Enabling SES for cold KSA bank outreach invites termination mid-campaign,
taking the domain's reputation with it.

`services/delivery_gmail.py` adds **Google Workspace** and **Microsoft 365**
adapters behind the identical `register_transport()` seam. Same `can_send()`
gate, same warmup ladder, same suppression checks — the deliverability engine
does not care which adapter is registered. Both fail closed: without
`ENABLE_GMAIL_TRANSPORT=true` (or the M365 equivalent) plus credentials,
neither registers and the platform stays dry-run.

The docstring in `deliverability.py` has been amended in place rather than
deleted, so the reasoning is visible to whoever reads it next.

**One caveat carried forward:** `WARMUP_CAPS` tops out at 100,000/day. Correct
for SES, far too high for a Workspace mailbox doing cold outreach — practical
ceiling is ~40–50/day/mailbox against a technical limit of ~2,000. Cap
`warmup_stage` accordingly and let reputation govern, not the ladder.

## 4 · Endpoints

```
POST /inbound/poll        one polling pass against a real mailbox
POST /inbound/simulate    feed raw RFC-822 messages — no credentials needed
GET  /inbound/transports  what can actually send right now, and why not
```

All three sit behind `TenantMiddleware` like every other business route — they
mutate data and suppress contacts, so they are deliberately **not** in
`PUBLIC_PREFIXES` alongside `/t/*`.

`/inbound/simulate` is the useful one before the domain exists: it runs the
identical code path as `/poll`, so you can replay a real bounce you were sent
and watch it suppress.

## Apply on your machine

```bash
cd drip_platform
python tests/test_inbound.py          # 18/18, no credentials, no network
uvicorn main:app --reload

curl localhost:8000/inbound/transports
# -> {"registered":["dry_run"],"can_send_real_mail":false, ...}
```

## Still blocked on people, not code

| | Blocked on |
|---|---|
| Sending domain registered (NOT decimaltechnologies.com) | Puneet + IT |
| Workspace tenant, SPF/DKIM/DMARC/PTR | IT |
| Domain-wide delegation consented | Workspace Super Admin |
| Gmail/M365 adapters exercised against a live tenant | the three above |
| 3–4 week domain warmup | calendar time |
| PDPL review before any real send | Legal |

The Gmail and M365 adapters are written, import cleanly, and fail closed — but
**have never run against a live tenant**. Domain-wide delegation in particular
is fiddly to authorise; treat it as real work, not a formality.

Do not send cold outreach from `decimaltechnologies.com`. One flagged campaign
damages every email the company sends, contracts and invoices included.
