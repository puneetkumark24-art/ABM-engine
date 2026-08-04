# Answers to your 15 questions — 2026-08-02

Every item below was checked in the code and, where it mattered, driven through
the running app. **Six were real bugs and are now fixed** (merged, `bafde8b`).
The rest are answers, and four are decisions I need from you rather than fixes.

One thing that explains a lot of this list: several of the things you describe
were fixed in the v4 merge, but **you were looking at the old running server**.
The campaign "choose audience" loop in particular no longer exists in the current
code. Restart with `Restart DRIP Platform.bat` before judging any of it.

---

## Fixed

### 2 & 7. "HOT LEADS — why is it here? What does it represent?"

It represents the contacts with the highest **engagement score** — computed from
email opens, clicks and replies (`PersonEngagement`). The idea is: of everyone
you have emailed, these are the people actually reacting, so they are the ones
worth a call this week.

**It was showing a truncated UUID instead of a name**, which is why it looked
like noise. `executive_dashboard()` only returned `{person_id, score}` and the
screen printed the first 8 characters of the id. Fixed: it now shows the
person's name and their bank, and clicking the row opens the contact.

How a contact becomes hot: they receive a campaign or sequence email, the
delivery events come back as opens/clicks/replies, and the score rises. With no
sends yet, the panel is legitimately empty.

### Campaign merge tags "not working"

They genuinely were not. The screen told you the tags were `{first_name}` and
`{bank}` — **neither of those existed**. The renderer supports `{name}`,
`{full_name}`, `{institution}`, `{role}`, `{city}`, `{sender}`, and an unknown
tag is replaced with an empty string rather than left visible, so following the
instruction on screen produced silently blank personalization with no error.

Fixed both ways: the label now lists the real tags, and `{first_name}` and
`{bank}` are registered as aliases so anything you have already written keeps
working. You can also give a fallback: `{name|there}` renders "there" when the
contact has no name.

### Campaign create button "keeps showing to choose audience"

Fixed — twice over. The v4 merge replaced that flow with a proper dropdown, and
I have now removed the remaining trap: the audience was only registered from the
**result** of the preview call, so if that call failed for any reason the button
refused forever while blaming your selection. The selection itself is now what
counts; the preview is just a count, and it reports its own failure honestly.

### 6. "All contacts should be visible"

You were seeing 50. `GET /persons` defaults to `limit=50`, the screen never
asked for more, then trimmed to 60 locally — with nothing on screen saying it
had truncated. Fixed: it now loads up to the server maximum (500) and tells you
"Showing N of M". For more than that, Export CSV gives you everything.

### 9 & 10. "Initiatives have a status — how do I change it? There is no option to act on it"

Correct, there wasn't. The backend endpoint has existed all along
(`POST /bd/signals/{id}/toggle`); the screen just never called it, so Status was
a label you could look at and nothing else. Added **mark read** and **mark
actioned** buttons on every row.

Meaning: *new* = nobody has looked at it, *read* = triaged, *actioned* = you
actually did something about it.

---

## Not bugs — here is what is happening

### 1. "What is the point of SAR 0 on the dashboard?"

It is your **total open pipeline value** — the sum of every open opportunity's
amount, with "weighted" underneath being the same figure multiplied by each
deal's stage probability.

It says SAR 0 because no opportunity has an amount recorded yet, not because the
tile is broken. Add a deal with a value under Pipeline and it will populate.
If you would rather it said "no deal values recorded yet" than "SAR 0", say so —
that is a one-line change.

### 3. "Export CSV should ask what to export — and it is not working"

**It works.** I ran both exports against a live app: organizations returns CSV,
contacts returns 121 rows for 120 contacts. What almost certainly happened is
that you were not signed in — the export goes through a raw `fetch()` and a 401
surfaces as "export failed: 401 — sign in first (Settings)". Sign in under
Settings and try again.

On "should ask what to export": the backend **already supports** scoped exports —
`/export/persons` takes `org_id`, `tier`, `indian`, `seniority` and a text query,
all combinable. The button just doesn't offer them. Worth adding a small
"Export…" dialog; tell me and I will.

### 4. "Import CSV should automatically match the contact with the organisation"

**It already does, and it needs no AI.** Include a `bank` or `org_name` column
and each row is matched to that organization by name (case-insensitive). If the
bank does not exist yet, it is created. Verified live: one row matched an
existing bank, another created a new one.

It also de-duplicates — by email, or by name-plus-bank when there is no email —
so re-importing the same file does not double your contacts.

What is missing is only that the screen never tells you any of this. The column
names it accepts should be documented on the upload button.

### 8. "How to make a contact a connector?"

Open the contact (click their name in Contacts), and there is a **Connector**
checkbox in the edit form alongside Decision maker and Indian origin. It saves
correctly — `is_connector` is in the allowed field list.

So it exists; it is just invisible until you open a contact. The Connectors
screen even says "mark contacts as Connector when editing them", which only
helps if you already knew where that was.

### 5. "Priority against each bank should be editable"

This one is a real gap, not a hidden feature. Contact priority **is** editable
(the `priority_tier` field on the contact edit form). **Account** priority is
not — it is computed by the scoring engine from signals, engagement,
reachability and regulatory fit, and there is no manual override.

That is a deliberate design, but your objection is fair: if you know an account
matters, you should be able to say so. Adding a manual override means a schema
change (a `priority_override` column plus a "manually set by X on date" marker so
it is clear the score was overridden rather than computed). **Want me to build
it?**

---

## Screens you questioned — what they are, and my read

You asked me to explain these rather than change them, so here is what each one
actually is. My recommendation is at the end of each; nothing has been removed.

### 11. BD Outreach — "why is it here, what does it do?"

It is the LinkedIn-style manual outreach tracker: pick a contact, then log
**Connection sent → Accepted → Messaged**, with a free-text note for the response
and next step. It predates the automated sequence engine and covers the part
sequences cannot — the manual, relationship-led touches.

*My read:* it overlaps heavily with Sequences and the contact's own outreach
fields. Its distinct value is LinkedIn-channel tracking, which nothing else does.
Reasonable options: keep it as a LinkedIn-specific log, or fold those three
buttons into the contact page and drop the screen.

### 12. Signals vs Initiatives vs BD Outreach — how do they differ?

- **Signals** and **Initiatives** read the *same table*. Initiatives is the
  cross-bank list of everything, newest first. Signals is the per-account and
  triage-oriented view, with the collectors that create them.
- **BD Outreach** is not related — it is your manual contact activity, not
  external events.

*My read:* Signals and Initiatives being two screens over one table is genuinely
confusing and I would merge them, with a "this account / all accounts" toggle.

**Collectors: "Seed KSA sources" and "Run now" — do they work?**
Yes. *Seed KSA sources* creates a starter set of Saudi sources (SAMA, bank
newsrooms, tender portals) as collector records. *Run now* fetches one and turns
what it finds into signals. They are the input side of the same table Initiatives
displays — which is why they live on the Signals screen.

### 13. Journeys — "I don't understand what it is or if it works"

A journey is a multi-step nurture flow: **send → wait → branch on whether they
opened → send a different follow-up**. Mailchimp-style automation, but running on
your CRM contacts, consent rules and account scoring.

Two things you should know. First, **you have not seen the current version** —
v4 replaced the developer screen (which asked for a "Person id" and had a
"demo-person" placeholder) with one that uses real contacts and real journey
definitions. Restart and look again. Second, before v4 the branch conditions were
hard-coded to always answer "no", so every branch was structurally dead; that is
now wired to real open/click events.

*My read:* keep it, but it overlaps with Sequences. Worth deciding which is the
primary automation tool rather than maintaining both.

### 14. Segments — "why is it here, is it working?"

It works, but it is still a **developer screen**: it asks you to type raw JSON
conditions like `[{"field":"tier","op":"eq","value":"1"}]`. Not something anyone
should be asked to do in a product.

Underneath, a segment is a saved dynamic list — "all Tier-1 contacts who have
replied" — that refreshes as data changes, and it does feed the campaign audience
dropdown, so it is genuinely wired in.

*My read:* the concept is worth keeping and the screen needs replacing with a
visual condition builder. It was missed by the v4 dashboard work — it is the only
screen still in its raw developer state.

---

## What I need from you

1. **Account priority override** — build it? (schema change)
2. **Export dialog** — add scope options to the export button? (backend already
   supports them)
3. **Signals + Initiatives** — merge into one screen?
4. **BD Outreach** — keep as a LinkedIn log, or fold into the contact page?
5. **Segments** — build a visual condition builder?
6. **Journeys vs Sequences** — which is the primary automation tool?

---

## Also worth knowing

The dashboard file contains **dead duplicate definitions** of three screens
(dashboard, journeys, signal review) — an old version and the v4 version, where
the later one silently wins. It works, but it is a trap for whoever edits it
next, and it is why Segments looks untouched while Journeys looks rebuilt. Worth
cleaning up; not urgent.

**Verification:** 24/24 checks against a live app on a disposable PostgreSQL,
covering every fix above plus export CSV and CSV import bank-matching. The
regression suites (`os_shell`, `crm_marketing_ext`, `unified`, `master_data`,
`parity_mission`, `engine_e2e`, `platform_services`) all pass. No schema change.
Delivery is still dry-run only.
