# Mailchimp-style email integration — report

**Merged as `31db3e1` on `main`.** Real sending remains disabled and hard-locked
to `dry_run`.

---

## First, the thing you should know about the source repo

`Documents\ABM\drip_repo` reports 12 changed files. Diffed against this
repository it shows **every file** as different — that is CRLF line endings, not
content. Ignoring line endings, **15 Python files genuinely differ**, and only 9
of them are the email work.

The other 6 are that repo reverting changes merged here earlier today, because
it forked before them. Most importantly it removes the `db.flush()` in
`marketing.send_campaign` — the fix that stops a campaign being marked **"sent"
while a C-suite approval draft is still pending**. Taking the file wholesale
would have silently reopened exactly the defect that branch exists to prevent.

Rejected in full: `llm_core.py` (−111 lines: the local-model provider),
`signal_v2_bridge.py` (−60: the runtime-account export fix), `routers/parity.py`
(−23: `/ai/status`), `marketing_ext.py` (−9: the `{first_name}`/`{bank}` merge
aliases), `test_crm_marketing_ext.py` and `test_unified.py` (−50 combined: the
approval-gate and collection-order assertions). Hand-merged: `marketing.py`,
`journeys.py`, `unified.py`, `os_shell.py`.

---

## Files changed (16)

**New:** `email_events.py`, `send_activation.py`, `provider_mandrill.py`,
`alembic/versions/u8a0b2c4d6e7_email_event_indexes.py`,
`tests/test_email_lifecycle_e2e.py`, `tests/_dbclean.py`

**Modified:** `tracking.py`, `delivery.py`, `delivery_ext.py`, `marketing.py`,
`journeys.py`, `unified.py`, `routers/platform_modules.py`, `tenant_middleware.py`,
`tests/conftest.py`, `tests/test_inbound.py`

## Migrations added

`u8a0b2c4d6e7` — indexes on `delivery_events(event_type, occurred_at)`,
`delivery_events(occurred_at)`, `email_messages(to_email)`,
`tracked_links(message_id)`. Idempotent, reversible, **round-tripped
up → down → up against real PostgreSQL**. `delivery_events` grows fastest of any
table here — one row per recipient per lifecycle stage, so a 30,000-recipient
campaign adds 150,000+ rows.

No table or column changes, so nothing to backfill.

---

## What I changed in the Codex work, and why

Four things would not have survived contact with production:

**1. `normalize(None)` returned `"delivered"`.** A malformed webhook, a truncated
payload, or the provider adding an event we don't know yet would each have been
counted as proof the mail arrived — inflating the single number the whole
deliverability picture rests on. Unknown is now `"unknown"`; it is recorded for
audit and acts on nothing.

**2. The 3-strike soft-bounce check was O(all events).** It loaded *every*
delivery event from the last 30 days into Python and filtered in a loop, once
per bounced address in the batch. At your stated 30,000-contact scale, one bad
campaign pulls hundreds of thousands of rows into memory to answer a question
about one address. Now an indexed `COUNT` joined to `email_messages` — which
also works for events whose payload omits the recipient.

**3. `prepare_email` was not idempotent.** With an absolute `PUBLIC_BASE_URL` the
rewritten href is itself an `http(s)` URL, so a retry, re-queue or re-render
matched its own output and wrapped the tracker in another tracker, duplicating
every `TrackedLink` row. Both the link rewrite and the pixel now no-op on an
already-instrumented body. This is your item 10, and it was live.

**4. `PUBLIC_BASE_URL` was used unvalidated,** defaulting to `""` in campaigns and
`http://localhost:8000` in journeys. A relative URL produces a pixel and links
that cannot resolve in a mail client — instrumentation that looks present and
silently does nothing. Tracking now disables itself unless the base URL is
absolute `http(s)`, and activation requires `https`.

---

## What I added

**`send_activation.py` — the fail-closed gate (items 7, 8, 9, 11).** Real
delivery requires *all* of: `EMAIL_LIVE_SENDING_ENABLED=true`; a **registered**
transport, not merely a configured one; that transport's credentials; an
`https` `PUBLIC_BASE_URL`; a webhook secret; verified SPF, DKIM and DMARC on the
sending domain; a return-path; an unsubscribe URL; and the KSA send window.
Every branch returns `dry_run` on failure, *including on an unexpected
exception* — there is no "assume yes" path. `GET /px/delivery/activation`
reports which condition is blocking.

**`provider_mandrill.py` (item 5).** Mandrill does not post JSON with a
JSON-body HMAC. It posts form-encoded `mandrill_events` and signs
`base64(HMAC-SHA1(key, url + concat(sorted(k+v))))` in `X-Mandrill-Signature`.
The URL it signs against is read from **configuration, never from the request** —
behind a reverse proxy the request's own host and scheme are whatever the proxy
rewrote them to, which breaks verification in production while passing every
local test. Native events map onto the canonical set; provider event id and
message id are preserved; our message id is recovered from Mandrill metadata
rather than falling back to Mandrill's own id, which would reference a message
this database has never seen.

**`tracking.is_safe_redirect` (item 13).** `/t/c/<token>` validates the
destination scheme at rewrite time **and again at redirect time** — the endpoint
is public and a poisoned row from any other code path would otherwise make it a
working open redirect under your own sending domain. `javascript:`, `data:` and
protocol-relative `//host` are refused.

**Per-signal auto-pause (item 12).** Four independent thresholds instead of one
blended rate: hard bounce 3%, total bounce 5%, complaint 0.2%, unsubscribe 0.5%.
The pause names which one tripped.

**Email Analytics screen (item 16).** Now separates attempted / accepted /
delivered / **simulated**, shows the bounce, complaint and unsubscribe split,
lists most-clicked links, and has real loading, empty, error and sign-in states.
Every key it reads was verified against an actual API response. Simulated
activity is labelled explicitly so a dry run cannot be mistaken for a campaign.

## Test isolation (item 4)

`tests/_dbclean.purge_all()` empties tables in **reverse dependency order taken
from SQLAlchemy's own graph**. `test_inbound`'s teardown did `DELETE FROM
persons`, which fails on PostgreSQL if any suite left a referencing row — it was
drafts, then touches, and the next table to gain a `person_id` would have broken
it again. Hand-listing children is whack-a-mole; deriving the order from the
schema is not. The two suites now pass **in either order in one process**, with
no separate databases.

---

## Tests executed

All against real disposable PostgreSQL 16, migrated with `alembic upgrade head`.

```
tests/test_email_lifecycle_e2e.py         50/50 checks   PASSED   (new)
tests/test_inbound.py                     18            PASSED
  lifecycle + inbound together, one process, the order that used to fail: 19 PASSED
tests/test_crm_marketing_ext.py                         PASSED
tests/test_unified.py                                   PASSED
tests/test_journeys.py                                  PASSED
tests/test_tracking_decision.py                         PASSED
tests/test_os_shell.py                                  PASSED
tests/test_engine_e2e.py                                PASSED
tests/test_platform_services.py                         PASSED
tests/test_sales_engagement.py                          PASSED
tests/test_tenancy_rls.py / test_tenant_writes.py       PASSED
tests/test_signal_pipeline_e2e.py                       PASSED
tests/test_alembic_roundtrip.py                         PASSED (fresh DB)
migration u8a0b2c4d6e7 up → down → up                   PASSED
```

The acceptance flow (item 17) runs inside `test_email_lifecycle_e2e`: audience →
campaign → personalization → link and pixel instrumentation → enqueue → signed
provider events → reporting → suppression and consent → account engagement →
dashboard payload, plus replay dedupe, retry non-duplication, unsigned-webhook
rejection and the Mandrill signature path.

**Honest limit:** a single whole-suite `pytest tests/` still exceeds this
sandbox's 45-second per-command cap, so it was not run end to end in one
invocation. Everything above was run per-file or in small in-process groups.

---

## Unresolved risks

1. **Tenant resolution is correct but single-secret.** Nothing reads a tenant
   from the payload — it resolves through *our* message id to the person and
   org, and an event for an unknown message suppresses nobody (verified). But
   webhook paths are unauthenticated by necessity, so `app.current_tenant` is
   unset and RLS does not scope the session. With one ESP account that is fine.
   **If tenants ever bring their own ESP accounts, you need a per-tenant webhook
   secret**, or tenant A's provider could submit an event for tenant B's message.
2. **`.in_(msg_ids)` in analytics** passes every message id as a bind parameter.
   Fine at current volumes; it will need a join or temp table before a
   six-figure campaign.
3. **No live provider has ever been exercised.** Every Mandrill assertion is
   against a payload I constructed from its documented scheme. The signature
   maths is verified; the real handshake is not.
4. **Item 14 is unverified.** Pixels and redirects behind your production proxy
   and public domain cannot be tested from here — it needs a real deployment.
5. Soft-bounce counting relies on `email_messages.to_email`. Events for messages
   sent before this change are matchable; events with no message row are not.

## Configuration still required before live sending

| Variable | Purpose |
|---|---|
| `EMAIL_LIVE_SENDING_ENABLED=true` | the deliberate human activation |
| `EMAIL_TRANSPORT=mandrill` | and its adapter must call `register_transport()` |
| `MANDRILL_API_KEY` | sending credential |
| `MANDRILL_WEBHOOK_KEY` | Mandrill's webhook signing key |
| `MANDRILL_WEBHOOK_URL` | the exact URL Mandrill is configured to call |
| `EMAIL_WEBHOOK_SECRET` | generic signed webhook |
| `PUBLIC_BASE_URL` | absolute **https** — tracking is off without it |
| `EMAIL_SENDING_DOMAIN` | with SPF, DKIM, DMARC verified in DNS |
| `EMAIL_RETURN_PATH`, `EMAIL_UNSUBSCRIBE_URL` | bounce attribution, legal requirement |

## Rollback

```
git revert -m 1 31db3e1
python -m alembic downgrade -1     # drops only the four indexes
```

---

## Live sending status

**Disabled.** `delivery._TRANSPORTS` contains only `dry_run`; every send request
in every test used `dry_run`; `resolve_transport()` returns `dry_run` and does so
even with `EMAIL_LIVE_SENDING_ENABLED=true` set, because the remaining
conditions are unmet — asserted directly in the test suite.

**This is not production-ready**, and passing dry-run tests is not evidence that
it is. It becomes production-ready after: a real Mandrill webhook validated
against the live endpoint, the migration applied to your actual PostgreSQL, DNS
authentication verified, the per-tenant secret question answered, a controlled
seed-list send, and your explicit activation.
