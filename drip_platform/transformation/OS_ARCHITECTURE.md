# DRIP OS — Single-Application Architecture (design deliverable)

## Information architecture & navigation map (implemented in the shell)

One SPA, one sidebar, hash-routed. Groups → routes:

- **Home**: Dashboard `#/dashboard`
- **Intelligence**: Accounts `#/accounts` · Account 360 `#/accounts/{id}` (tabs:
  Overview, Contacts, Buying Committee, Signals, Deals, AI, Tasks) · Contacts
  `#/contacts` · Signals & Collectors `#/signals`
- **Marketing**: Journeys `#/journeys` · Segments `#/segments` · Email
  Analytics `#/email` · Preferences tooling (inside Contacts/Account 360)
- **Sales**: Pipeline `#/pipeline` · Meetings `#/meetings` · Tasks `#/tasks` ·
  Sequences `#/sequences`
- **CRM**: Quotes & Products `#/quotes` · Custom Objects `#/objects`
- **Automation**: Workflow `#/workflow`
- **AI Center**: Prompts & Calls `#/ai` (registry, versioning, rollback, test
  console, cost analytics) · Agents (honest "planned" state — never fake)
- **Analytics**: Reports `#/reports` · Cohorts & Trends `#/analytics`
- **Admin**: Developer `#/developer` (API keys, webhooks) · Compliance
  `#/compliance` · Health `#/health` · Settings `#/settings`

Top bar: global search (⌘K command palette, `/search`), notifications (recent
signals + workflow dead-letters), profile/login, breadcrumbs via context bar.

## Shared state model

`S = { token, rtl, account: {id, name} | null }` persisted in localStorage.
Selecting an account ANYWHERE (search, accounts table, dashboard) sets
`S.account`; a persistent context bar renders it; every account-aware screen
(360 tabs, committee, signals, deals, tasks, AI) reads it. Clearing context
returns screens to global scope. Auth: one token, attached to every fetch;
401 anywhere surfaces the login affordance. One design-token set (the existing
deep-green/gold dark system) styles every screen.

## Routing plan

Hash router (`#/screen[/id]`), zero build tooling, served by the same FastAPI
process at `/` — no second origin, no CORS, no separate deploy. `/app`
redirects to `/`. The previous launcher and operator console are retired;
the console remains at `/legacy` during transition. External surfaces removed
from navigation (Lovable demo). The Flask BD dashboard remains a separate
process for now — its core data (contacts by bank, tiers) is already served
inside the OS via `/organizations/{id}/persons`; full ETL/flow-map absorption
is the one remaining migration, tracked in the registry.

## Module dependency & integration model

All modules call the ONE API (31 routers) on the ONE database. Integration is
by shared account context + cross-navigation (e.g. signal row → its account's
360; committee gap → contacts tab; AI test → prompt registry), not iframes or
links to other apps. End-to-end journey supported without leaving the SPA:
select bank → profile → committee → signals → AI research → segment → journey →
email analytics → tasks → deal → pipeline → report.

## Honesty constraints

Screens for capabilities that do not exist in the backend (Invoices, Knowledge
Graph visual, autonomous Agents, News/Career/Vendor dedicated feeds) appear in
the IA as explicit "planned" states with what unblocks them — the shell never
fakes a capability the platform lacks.
