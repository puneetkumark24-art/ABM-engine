# ULTIMATE mailing-engine package — integration report

**Merged as `ae7fdb8` on `main`.** Live sending remains disabled; `dry_run` is
the only registered transport.

---

## Files merged (17 of 18 packaged; 1 doc-only)

**Taken as the stronger implementation:** `delivery.py`, `mandrill_events.py`
(new), `routers/platform_modules.py`, `models_ext.py`, `delivery_ext.py`,
`deliverability.py`, `journeys.py`, `routers/bd_parity.py`,
`tests/test_mailchimp_e2e.py` (new), and both migrations.

**Hand-merged:** `tracking.py`, `marketing.py`, `unified.py`, `email_events.py`.

**Rejected:** `routers/os_shell.py`, `tenant_middleware.py` (equivalent to
current), `webhook_security.py` (identical).

Line endings first: the package reports 18 changed files and *every* file
differs on a naive diff. That is CRLF. Ignoring it, 17 genuinely differ.

## Conflicts and decisions

This package forked before today's merges, so it would have reverted live work.
Four conflicts, each resolved in favour of the newer code:

| Conflict | Decision |
|---|---|
| `marketing.py` drops the `db.flush()` in the c-suite branch | **Kept ours.** Third package in a row to drop it. Without it a campaign is marked `sent` while an executive draft is still awaiting review — the exact inversion that branch exists to prevent. |
| `unified.py` drops `hot_leads` name/org enrichment | **Kept ours.** The dashboard would render a truncated UUID again. Took their `mode: "empty"` and unique-message unsubscribe rate. |
| `os_shell.py` reverts five UI fixes | **Rejected the file.** It would have undone the Email Analytics screen, initiatives read/actioned controls, the contacts "showing N of M" fix, `/persons?limit=500`, and the merge-tag label fix. Its only new content — campaign-detail KPIs — is already covered by the current screen. |
| `email_events.normalize()` returns `""` for a missing type | **Kept our `UNKNOWN` sentinel, took their `CANONICAL` set.** `unknown` is deliberately not in `CANONICAL`, so ingestion still fails closed — but the value is explicit rather than an empty string. |

One performance conflict: their `_soft_bounce_count` reads *every* delivery
event from the last 30 days into Python, once per bounced address. Kept the
indexed join.

## What this package genuinely improved on ours

- **Webhook tenant routing.** `ingest_webhook` now resolves through
  `provider_message_maps`, applies **transaction-local** PostgreSQL tenant
  context from the mapping (`set_config(..., true)`), and rejects a missing
  mapping, a message-id mismatch, an unknown message, or a non-canonical event.
  Materially safer than what was here.
- **Fail-closed Mandrill translation.** An event without our own
  `drip_message_id` is rejected, never guessed. Batch cap 1000. Provider event
  and message ids preserved.
- **Link rewriting** now handles single-quoted and mixed-case `href`, and
  reuses the existing token for a `(message, url)` pair.
- **`campaign_preflight()`** — a non-mutating launch checklist covering empty
  audiences, subject header-injection, unsafe link schemes, missing
  unsubscribe, non-HTTPS tracking URL and unrecorded consent.

## Two defects found by running it

**1. The pixel lost its idempotency guard in the merge.** The link side was
guarded, the pixel side was not, so a retry appended a second tracking pixel.
Caught by the lifecycle suite, not by inspection.

**2. Provider timestamps could silently hide events.**
`_provider_occurred_at` accepted any parseable value, so a millisecond-scale or
placeholder `ts` (epoch 1970) placed the event outside every analytics window —
present in the table, invisible in every report, with nothing to indicate a
problem. Implausible values now fall back to receipt time.

## Migrations and rollback rehearsal

Applied in order on a **clone of the pre-migration schema**, not on the working
database:

```
u8a0b2c4d6e7 (baseline)  →  u8c0e2f4a6b8  →  v9d1f3a5b7c9   UPGRADE   ok
v9d1f3a5b7c9  →  u8c0e2f4a6b8  →  u8a0b2c4d6e7             ROLLBACK  ok
  provider_message_maps dropped                     verified (0 rows in catalog)
  send_requests.provider_message_id dropped         verified
u8a0b2c4d6e7  →  v9d1f3a5b7c9                              RE-UPGRADE ok
```

`u8c0e2f4a6b8` as packaged revised `t7f9a1b3c5d6` directly, which would have
produced **two Alembic heads** alongside the index migration merged earlier
today and made `upgrade head` ambiguous. Rebased onto `u8a0b2c4d6e7`.

**`provider_message_maps` verified PII-free** — columns are exactly `id`,
`provider`, `provider_message_id`, `message_id`, `tenant_id`, `created_at`. No
recipient address, name or body.

## Test results

Legacy modules run in **separate processes with distinct disposable
databases**, as instructed.

```
test_email_lifecycle_e2e     51/51 checks   PASSED   (PostgreSQL)
test_mailchimp_e2e (theirs)                 PASSED
test_inbound                 18             PASSED
test_tracking_decision                      PASSED
test_unified                                PASSED
test_crm_marketing_ext                      PASSED
test_platform_services                      PASSED
test_journeys                               PASSED
full source compilation                     PASSED
```

Acceptance run against a live app on PostgreSQL — **13/13**:

- app starts, `/`, `/health`, `/dashboard/executive`, `/analytics/email` all 200
- **empty analytics reports `mode: "empty"`**, not provider delivery
- `/px/delivery/activation` reports live sending **off**
- **auto-pause fires independently** on hard bounce, total bounce, complaint and
  unsubscribe thresholds
- only `dry_run` is registered

Also pinned by the lifecycle suite: campaign *and* journey emails both receive
idempotent tracking; `accepted` / `delivered` / `simulated_delivered` stay
distinct; hard bounce, repeated soft bounce, complaint and unsubscribe update
suppression and consent; replays deduplicate; `/t/c/<token>` refuses
`javascript:`, `data:` and protocol-relative destinations.

## Outstanding risks

1. **No live provider has ever been exercised.** Every Mandrill assertion is
   against payloads built from its documented scheme. The signature maths is
   verified; the real handshake is not.
2. **The webhook secret is global.** Tenant resolution never trusts the payload,
   but with one shared secret a single ESP account covers all tenants. If
   tenants bring their own accounts, this needs a per-tenant secret.
3. **`bind_provider_message` is only reachable from live transports.** In
   dry-run no mapping rows are created, so the mapping path is exercised by
   construction in tests rather than by real traffic.
4. **Tracking pixels and redirects behind your production proxy are unverified** —
   that needs a real deployment.
5. `.in_(msg_ids)` in analytics binds every message id; fine now, needs a join
   before a six-figure campaign.

## Required production configuration

`EMAIL_LIVE_SENDING_ENABLED`, `EMAIL_TRANSPORT`, `MANDRILL_API_KEY`,
`MANDRILL_WEBHOOK_KEY`, `MANDRILL_WEBHOOK_URL` (the exact URL Mandrill calls —
it is part of the signature), `EMAIL_WEBHOOK_SECRET`, `PUBLIC_BASE_URL`
(absolute **https**), `EMAIL_SENDING_DOMAIN` with SPF/DKIM/DMARC verified,
`EMAIL_RETURN_PATH`, `EMAIL_UNSUBSCRIBE_URL`.

## Rollback

```
git revert -m 1 ae7fdb8
python -m alembic downgrade u8a0b2c4d6e7
```

## Live sending

**Disabled.** `delivery._TRANSPORTS` contains only `dry_run`; no Mandrill, SES,
Gmail, Microsoft 365 or SendGrid transport is registered; SendGrid was not
touched. `resolve_transport()` returns `dry_run` and continues to do so even
with `EMAIL_LIVE_SENDING_ENABLED=true`, because the remaining activation
conditions are unmet — asserted in the suite.

**Not production-live.** That requires separate human approval plus verified
SPF, DKIM, DMARC, return path, HTTPS tracking domain, native webhook
configuration, PostgreSQL RLS behaviour, KSA send windows, mailbox warm-up,
complaint thresholds and a controlled seed-list delivery.
