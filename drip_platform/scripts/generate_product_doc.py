"""
generate_product_doc.py — builds the Complete Product Documentation PDF.

Half authored guide, half auto-generated ground truth (live schema, live route
table, migration chain, test catalog) so the document cannot drift from the
code. Run:  python scripts/generate_product_doc.py
"""
from __future__ import annotations
import glob
import os
import re
import sys
from datetime import date

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, PageBreak,
                                Table, TableStyle, KeepTogether)
from reportlab.platypus.tableofcontents import TableOfContents

GREEN = colors.HexColor("#1d5c3f")
GOLD = colors.HexColor("#b8860b")
DIM = colors.HexColor("#5a6e64")
LINE = colors.HexColor("#cddbd3")

styles = getSampleStyleSheet()
S_TITLE = ParagraphStyle("T", parent=styles["Title"], fontSize=30, textColor=GREEN, spaceAfter=6)
S_SUB = ParagraphStyle("Sub", parent=styles["Normal"], fontSize=13, textColor=DIM, spaceAfter=4)
S_H1 = ParagraphStyle("H1x", parent=styles["Heading1"], fontSize=19, textColor=GREEN,
                      spaceBefore=10, spaceAfter=8)
S_H2 = ParagraphStyle("H2x", parent=styles["Heading2"], fontSize=14, textColor=GREEN,
                      spaceBefore=8, spaceAfter=5)
S_H3 = ParagraphStyle("H3x", parent=styles["Heading3"], fontSize=11.5, textColor=GOLD,
                      spaceBefore=6, spaceAfter=3)
S_P = ParagraphStyle("Px", parent=styles["Normal"], fontSize=9.5, leading=13.5, spaceAfter=5)
S_SMALL = ParagraphStyle("Sm", parent=styles["Normal"], fontSize=8, leading=11,
                         textColor=DIM, spaceAfter=3)
S_CODE = ParagraphStyle("Cd", parent=styles["Code"], fontSize=8, leading=10.5,
                        backColor=colors.HexColor("#f2f6f4"), borderPadding=4, spaceAfter=5)

story = []
_headings = []


class Doc(SimpleDocTemplate):
    _seen_h1 = False

    def afterFlowable(self, fl):
        if isinstance(fl, Paragraph) and fl.style.name in ("H1x", "H2x"):
            text = fl.getPlainText()
            if text == "Table of Contents":
                return
            level = 0 if fl.style.name == "H1x" else 1
            if level == 0:
                Doc._seen_h1 = True
            if level == 1 and not Doc._seen_h1:
                level = 0  # outline can't start at depth 1
            key = f"h{len(_headings)}"
            _headings.append(text)
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(text, key, level=level, closed=level == 0)


def esc(t: str) -> str:
    return (str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def H1(t): story.append(PageBreak()); story.append(Paragraph(esc(t), S_H1))
def H2(t): story.append(Paragraph(esc(t), S_H2))
def H3(t): story.append(Paragraph(esc(t), S_H3))
def P(t): story.append(Paragraph(t, S_P))
def CODE(t): story.append(Paragraph(esc(t).replace("\n", "<br/>"), S_CODE))


def TBL(rows, widths=None, font=7.5):
    data = [[Paragraph(esc(c), ParagraphStyle("c", fontSize=font, leading=font + 2.2)) for c in r]
            for r in rows]
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), GREEN),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, 0), font),
        ("GRID", (0, 0), (-1, -1), 0.4, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f8f6")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5)]))
    story.append(t)
    story.append(Spacer(1, 6))


def MD(path, max_table_cols=6):
    """Render a markdown file: headings, paragraphs, tables, bullets."""
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        return
    buf, tbl = [], []

    def flush_par():
        if buf:
            t = " ".join(buf)
            t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", esc(t))
            t = re.sub(r"`(.+?)`", r"<font face='Courier' size='8'>\1</font>", t)
            P(t)
            buf.clear()

    def flush_tbl():
        if tbl:
            rows = [[c.strip() for c in r.strip("|").split("|")][:max_table_cols] for r in tbl]
            rows = [r for r in rows if not all(re.fullmatch(r"[-: ]*", c) for c in r)]
            if rows:
                TBL(rows)
            tbl.clear()

    for line in text.splitlines():
        ls = line.strip()
        if ls.startswith("|"):
            flush_par(); tbl.append(ls); continue
        flush_tbl()
        if not ls:
            flush_par(); continue
        if ls.startswith("### "):
            flush_par(); H3(ls[4:])
        elif ls.startswith("## "):
            flush_par(); H2(ls[3:])
        elif ls.startswith("# "):
            flush_par(); H2(ls[2:])
        elif ls.startswith(("- ", "* ", "• ")):
            flush_par(); P("•&nbsp;" + re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", esc(ls[2:])))
        elif re.fullmatch(r"[─═#=~-]{4,}", ls):
            continue
        else:
            buf.append(ls)
    flush_par(); flush_tbl()


# ════════════════════ COVER + TOC ════════════════════
story.append(Spacer(1, 4 * cm))
story.append(Paragraph("DRIP OS", S_TITLE))
story.append(Paragraph("Enterprise AI-Native ABM Operating System for KSA Banking",
                       ParagraphStyle("st", parent=S_SUB, fontSize=15)))
story.append(Spacer(1, 0.6 * cm))
story.append(Paragraph("Complete Product Documentation — from scratch to the final platform",
                       S_SUB))
story.append(Paragraph(f"Decimal Technologies · generated {date.today().isoformat()} · "
                       "single source of truth: the repository itself", S_SMALL))
story.append(Spacer(1, 1.2 * cm))
P("<b>How to read this document.</b> Part I tells the story: what DRIP is, why it exists, "
  "and how it was built sprint by sprint. Part II explains the architecture and — critically — "
  "<b>where your data lives and how to change it</b>. Part III is the user guide: every screen "
  "of the DRIP OS. Part IV is the module reference for engineers. Part V is auto-generated "
  "ground truth: every database table, every API endpoint, every migration, every test — "
  "extracted from the running code at generation time, so it cannot be out of date. "
  "Part VI covers operations, and Part VII holds the honest assessments: audits, scores, "
  "gaps, and the roadmap.")
story.append(PageBreak())
story.append(Paragraph("Contents", S_H2))
for part, subs in [
    ("Part I — Vision, Story and Journey", "What DRIP is · Constitution · The journey 34→OS · Today in one paragraph"),
    ("Part II — Architecture & Your Data", "System architecture · WHERE data is stored · HOW to update it (4 ways) · Security model"),
    ("Part III — The DRIP OS, Screen by Screen", "All 26 screens: purpose, usage, and the APIs behind each"),
    ("Part IV — Module Reference", "13 engineering modules: code, logic, tables"),
    ("Part V — Ground Truth (auto-generated)", "Every database table · every API endpoint · migration chain · test suites · configuration"),
    ("Part VI — Operations Guide", "Running · backups · monitoring · troubleshooting · deployment paths"),
    ("Part VII — Honest State", "Live parity registry · audit conclusions · 90/180/365-day roadmap"),
    ("Appendix", "Full governance documents: Constitution, OS architecture, unification, parity mission, certification, CTO review, due diligence")]:
    story.append(Paragraph("<b>" + esc(part) + "</b>", S_P))
    story.append(Paragraph(esc(subs), S_SMALL))
story.append(Paragraph("Use the PDF sidebar bookmarks to jump to any section.", S_SMALL))

# ════════════════════ PART I — VISION & JOURNEY ════════════════════
H1("Part I — Vision, Story and Journey")
H2("1. What DRIP is")
P("DRIP (Decimal Relationship Intelligence Platform) is an account-based marketing operating "
  "system built for one job: helping Decimal Technologies sell banking technology to Saudi "
  "financial institutions. It is not a generic CRM with a Saudi skin — its data model is "
  "banking-native: banks with core-banking-stack fields, vendor and subsidiary ecosystems with "
  "confidence-weighted relationships, SAMA-aware signal classification, buying committees "
  "inferred from titles, and money handled in SAR minor units end to end.")
P("The operating loop it implements: <b>sense</b> (signal collectors + intelligence) → "
  "<b>understand</b> (accounts, committees, relationships, scoring) → <b>decide</b> (explainable "
  "decision engine with AI seams) → <b>act</b> (sequences, journeys, campaigns — send-safe) → "
  "<b>learn</b> (engagement rollups and variant performance feeding back into decisions).")
H2("2. Design principles (the Constitution)")
P("Everything was built under a written constitution: KEEP → HARDEN → EXTEND, never rewrite; "
  "additive-only database migrations; no breaking API changes; every claim proven by a test on "
  "real PostgreSQL; brutal honesty — anything requiring an external input is marked "
  "BLOCKED-EXTERNAL rather than faked; and send-safety — the email engine is dry-run by "
  "design until real credentials are provided, and C-suite contacts always require human "
  "review before any outreach.")
H2("3. The journey — from 34/100 to the DRIP OS")
P("The platform began as a working engine that an independent audit scored 34/100: strong "
  "foundations (multi-tenant row-level security, partitioned event tables, async workers, 275 "
  "tests) but missing enterprise essentials. Ten sprints, a unification phase, a parity "
  "mission, and the OS build followed. Each stage below was delivered as tested code — the "
  "check counts are from the automated suites.")
TBL([["Stage", "Delivered", "Proof"],
     ["Sprint 1 — Platform Foundation", "Route authorization, JSON logging + request IDs, health/metrics, universal audit trail, CI/CD, K8s + Terraform (me-south-1)", "289/289 on PostgreSQL"],
     ["Sprint 2 — Enterprise CRM", "Custom objects, money-correct amounts (minor units + backfill), CPQ quotes/products/price books, property history", "19/19 + Review-Board remediation 20/20"],
     ["Sprint 3 — Marketing", "Journey orchestration (send/wait/branch), multivariate testing, dynamic content", "17/17"],
     ["Sprint 4 — ABM Intelligence", "Buying-committee inference + coverage, signal dedup (content hash), account scoring", "19/19"],
     ["Sprint 5 — Sales Engagement", "Reply sentiment → auto pause/suppress/handoff, step-level A/B, hot leads", "14/14"],
     ["Sprint 6 — Workflow", "Durable execution: idempotency keys, bounded retry, dead-letter queue", "12/12"],
     ["Sprint 7 — Analytics", "Cohort retention, time series over partitioned events", "10/10"],
     ["Sprint 8 — Developer Platform", "API keys (hashed), signed outbound webhooks with retry + DLQ", "13/13"],
     ["Sprint 9 — Security & Compliance", "Fernet field encryption, RBAC/ABAC, PDPL export/erase, consent, retention", "22/22"],
     ["Sprint 10 — Production Readiness", "Perf harness, SLOs, Prometheus alerts, ops + DR runbooks", "6/6"],
     ["Unification", "Global search, executive dashboard, email analytics, capability registry + parity dashboard, GA4 seam", "31/31"],
     ["Parity Mission", "LLM core (prompt registry/versioning/cost), live KSA signal collectors, segments engine", "27/27"],
     ["Final Wave", "Meetings + ICS, public preference center, report builder, login rate-limit, dashboard auth, audit retention, RTL", "24/24"],
     ["DRIP OS", "ONE application: full-IA sidebar, Account 360, command palette, notifications, one login", "54/54"],
     ["Master Data", "Search + create/edit/soft-delete + CSV import/export for banks & people, vendors screen, BD outreach module", "29/29"]],
    widths=[4.4 * cm, 9.2 * cm, 3.4 * cm])
H2("4. What exists today, in one paragraph")
P("One FastAPI application serving one single-page OS at <b>http://127.0.0.1:8000/</b>: 33 "
  "routers, ~120 endpoints, 97+ database tables on your local PostgreSQL, 8,000+ real Saudi "
  "banking contacts, live RSS/regulatory signal collectors, an LLM core that is one API key "
  "away from live AI, and 600+ automated checks green. What still needs external inputs: real "
  "email sending (SES credentials), live AI (LLM key), SSO (identity provider), cloud "
  "deployment (account), certifications (auditors).")

# ════════════════════ PART II — ARCHITECTURE & DATA ════════════════════
H1("Part II — Architecture, and Where Your Data Lives")
H2("5. System architecture")
P("DRIP is a <b>modular monolith</b>: one Python process (FastAPI + SQLAlchemy 2.0) with clean "
  "internal boundaries — thin routers (HTTP layer) → services (business logic, 40+ modules "
  "under abm_platform/services/) → models (SQLAlchemy tables). Async work runs through a "
  "durable in-database job queue claimed with FOR UPDATE SKIP LOCKED by worker processes; a "
  "single scheduler process drives the beat loop (due sequence steps, campaign firing, outbox "
  "relay, signal collectors hourly, audit retention daily, partition provisioning monthly). "
  "An event bus + transactional outbox decouple modules internally.")
CODE("Browser (DRIP OS SPA at /)\n"
     "   ↓ fetch JSON (one origin, one login)\n"
     "FastAPI app — main.py (33 routers)\n"
     "   ↓ TenantMiddleware: JWT → scopes + tenant GUC\n"
     "Services (abm_platform/services/*.py)\n"
     "   ↓ SQLAlchemy ORM (audit listener on every flush)\n"
     "PostgreSQL 'drip' (RLS-enforced, partitioned)\n"
     "   ↑ Workers (jobs queue)  ↑ Scheduler (beat loop)")
H2("6. WHERE the data is stored")
P("<b>Everything lives in one PostgreSQL database named <font face='Courier'>drip</font> on "
  "your machine</b> (localhost:5432), as configured in the <font face='Courier'>.env</font> "
  "file at drip_platform/.env (DATABASE_URL). There is no second store: the OS screens, the "
  "legacy BD dashboard, the API, the workers and the collectors all read and write this one "
  "database. If DATABASE_URL is absent (tests, demos) the platform falls back to a local "
  "SQLite file — same schema, same code.")
P("Data protection layers on that database: <b>row-level security</b> enforced by PostgreSQL "
  "itself (every business table carries tenant_id; the app connects as a non-superuser role "
  "so policies cannot be bypassed); an <b>append-only audit trail</b> (every insert/update/"
  "delete on 28 business tables records who/when/before/after — this powers record history); "
  "<b>soft deletes</b> for master data (deleting a bank or person sets is_active=false — "
  "nothing is destroyed, everything is restorable); and monthly <b>partitioning</b> for the "
  "three high-volume event tables so analytics stay fast.")
H2("7. HOW to update the data (all four ways)")
P("<b>1 — In the OS (recommended).</b> Accounts and Contacts screens have search boxes, "
  "+ New buttons, per-row edit and delete, ⬆ Import CSV and ⬇ Export CSV. Every edit is "
  "audit-trailed automatically. BD Outreach updates connection/message status per contact. "
  "Deletes are soft — restore by editing the record's is_active back to true (or PATCH via API).")
P("<b>2 — CSV import.</b> Click ⬆ Import CSV on Accounts (columns: canonical_name, country, "
  "website, ...) or Contacts (full_name, email, org_name/bank, current_title, tier, ...). "
  "Duplicates are detected (banks by name; people by e-mail, then name+bank) and skipped, "
  "never overwritten. The response tells you created/skipped/errors counts.")
P("<b>3 — The API.</b> Every entity has REST endpoints (full catalog in Part V): "
  "POST to create, PATCH with {\"fields\": {...}} to update, DELETE for soft delete, "
  "GET /export/organizations|persons for CSV. Authenticate with your admin login via "
  "POST /auth/login, or an API key from the Developer screen.")
P("<b>4 — Schema changes.</b> When the CODE gains new tables/columns, run "
  "<font face='Courier'>python sync_db.py</font> (safe, additive, idempotent — it creates "
  "missing tables, adds missing columns, backfills, and stamps alembic). The desktop launcher "
  "runs it automatically at every start. Formal migrations live in alembic/versions/ "
  "(31 revisions, every one reversible).")
H2("8. Security model")
P("One login (POST /auth/login → 12-hour JWT; credentials in .env: ADMIN_EMAIL / "
  "ADMIN_PASSWORD), brute-force rate-limited (5 failures → 5-minute lockout). Authorization is "
  "scope-based per path prefix, enforced in middleware. The database enforces tenant isolation "
  "independently of the application (RLS with FORCE). PII can be encrypted at rest (Fernet). "
  "PDPL data-subject rights are implemented: export, consent management, and right-to-erasure "
  "(scrubs PII, suppresses the address, keeps the anonymized row for referential integrity). "
  "Email is dry-run; the suppression list is honored by every send path.")

# ════════════════════ PART III — THE DRIP OS USER GUIDE ════════════════
H1("Part III — The DRIP OS, Screen by Screen")
P("Open http://127.0.0.1:8000/ (your desktop button does this). Sign in under Settings. "
  "Press Ctrl+K anywhere for the command palette. Selecting a bank anywhere sets the working "
  "context — a bar appears under the top bar and every module follows that account until you "
  "clear it.")
_screens = [
    ("Dashboard", "The executive homepage: pipeline value and weighted forecast in SAR, account/contact counts, signals this week, email performance, hot leads, top accounts. Click any account to jump into its 360.", "/dashboard/executive"),
    ("Accounts", "The bank master. Search box filters live; + New bank creates; each row has edit (name, country, website, core-banking system) and del (soft delete, restorable). ⬆ Import CSV / ⬇ Export CSV for bulk work. Clicking a name opens the Account 360.", "/organizations · PATCH/DELETE /organizations/{id} · /import/organizations · /export/organizations"),
    ("Account 360", "Everything about one bank in tabs: Overview (tier, score, lifecycle), Contacts (its people), Committee (coverage ring, missing roles, single-threaded warning, one-click role inference), Signals (its news/regulatory feed), Deals (its pipeline in SAR), AI (generate an outreach angle through the guarded prompt registry), Tasks (create follow-ups tied to the bank).", "/organizations/{id}/... · /abm/committee/{id}/..."),
    ("Contacts", "The people master. Search across name/title/email; + New contact (bank auto-created if new); edit (name, title, email, tier, next step) and soft delete per row; CSV import/export; hot-leads panel ranked by engagement.", "/persons · PATCH/DELETE /persons/{id} · /import/persons · /export/persons"),
    ("Vendors", "The ecosystem view: every vendor/subsidiary/partner with its confidence-weighted edges to banks, plus vendor intelligence (products, capabilities, clients) where captured.", "/abm/vendors"),
    ("BD Outreach", "The daily BD cockpit: contacts (for the account in context, or globally) filtered by tier and text; click a contact then one-click record 'connection sent', 'accepted', 'messaged', or save a response note / next step. Replaces the old port-5050 dashboard's core flow.", "PATCH /crm/persons/{id}/outreach"),
    ("Signals", "The intelligence inbox plus the collector fleet. Seed KSA sources once (Argaam, Saudi Gazette, Arab News, SAMA), then Run now — or let the scheduler pull hourly. Items dedup automatically and match to banks by name.", "/signals · /abm/collectors[/seed|/run]"),
    ("Buying Committee", "Coverage for the account in context: the five canonical roles, % ring, engaged count, single-threaded flag, and inference from titles.", "/abm/committee/{org}/coverage|/infer"),
    ("Journeys", "Marketing orchestration: create the demo send→wait→branch journey, enroll people, and Run tick to advance everyone due. (The drag-drop canvas is a planned UI; the engine is fully live.)", "/mkt/journeys..."),
    ("Segments", "Dynamic segments from JSON conditions (any person field + engagement_score / has_replied) evaluated live, or static lists with explicit membership.", "/crm/segments..."),
    ("Email Analytics", "Mailchimp-grade metrics from your real send tables: delivery/open/click rates, CTOR, bounces, unsubscribes, per-campaign comparison, GA4 status.", "/analytics/email · /analytics/ga4/status"),
    ("Pipeline", "All open deals with SAR amounts, weighted forecast, and stage view.", "/opportunities · /dashboard/executive"),
    ("Meetings", "Schedule (conflict-detected per owner), see upcoming, download .ics into any calendar; meetings created with an account in context attach to it.", "/crm/meetings..."),
    ("Tasks", "My-day queue per assignee; tasks can be created from any Account 360.", "/crm/tasks..."),
    ("Sequences", "The automated cadence engine (send-safe): definitions, enrollment, due steps.", "/sequences..."),
    ("Quotes & Products", "SAR-correct CPQ: quick quote with lines, totals recomputed in minor units; products/price books via API.", "/crm/quotes..."),
    ("Custom Objects", "Define your own record types with validated schemas (e.g. regulatory_case).", "/crm/objects..."),
    ("Workflow", "Durable-execution health: the dead-letter queue and step ledger.", "/workflow/dead-letters"),
    ("AI Center", "The prompt registry (versions, active flags, rollback), the test console (see exactly what the model returns, at what cost), and analytics (calls, tokens, dollars, per prompt). Dry-run until a key is configured — then LIVE, with all guardrails intact.", "/ai/prompts · /ai/call · /ai/analytics"),
    ("Reports", "The custom report builder: entity + filters + group-by + count/sum, rendered as bars; save definitions for reuse.", "/reports/run · /reports"),
    ("Cohorts & Trends", "Time-series buckets and cohort-retention matrices over the event firehose.", "/analytics/timeseries|/cohort-retention"),
    ("Feature Parity", "The live competitor dashboard fed by the in-code capability registry — updates automatically as the registry changes.", "/platform/parity"),
    ("Developer", "API keys (shown once, stored hashed), outbound webhook subscriptions (HMAC-signed, retried), link to the full OpenAPI reference at /docs.", "/dev/api-keys · /dev/webhooks"),
    ("Compliance", "PDPL console: export a subject's data, set consent, or erase (scrub + suppress).", "/compliance/subjects/..."),
    ("Health", "Liveness/readiness probes and the Prometheus metrics endpoint.", "/health/ready · /metrics"),
    ("Settings", "Sign in/out, Arabic/RTL layout toggle, link to the legacy console.", "/auth/login"),
]
for name, purpose, apis in _screens:
    story.append(KeepTogether([Paragraph(esc(name), S_H2),
                               Paragraph(esc(purpose), S_P),
                               Paragraph("<b>APIs:</b> " + esc(apis), S_SMALL)]))

# ════════════════════ PART IV — MODULE REFERENCE ════════════════════
H1("Part IV — Module Reference (for engineers)")
_modules = [
    ("Identity & Tenancy", "auth.py, tenant_middleware.py, routers/auth_login.py, tenancy.py",
     "JWT issue/verify (HS256), scope wildcards, per-path SCOPE_POLICY, rate-limited login, transaction-local tenant GUC feeding Postgres RLS.",
     "tenants, app_users, app_roles"),
    ("Master Data", "routers/master_data.py, routers/organizations.py, routers/persons.py",
     "CRUD + soft delete + bulk import (dedup) + CSV export for banks and people; vendors ecosystem aggregation.",
     "organizations, persons, org_relationships, vendor_intelligence"),
    ("CRM Core", "abm_platform/services/{pipeline,crm_ext,merge,timeline}.py, quotes.py, custom_objects.py, property_history.py, meetings.py",
     "Pipelines/stages/forecast/health, saved views, tasks, dedup-merge, CPQ in minor units, dynamic objects with schema validation, audit-derived history, meetings with ICS.",
     "opportunities, pipelines, pipeline_stages, crm_tasks, quotes, quote_line_items, crm_products, price_books, custom_object_defs/records, meetings"),
    ("ABM Intelligence", "abm_intel.py, collectors.py, etl/signal_intel.py, etl/signal_decay.py",
     "Title→role committee inference + coverage, signal ingest with content-hash + URL dedup, RSS/Atom collectors with auto-disable, SAMA-aware classification, decay half-lives, blended account scoring.",
     "signals, signal_sources, buying_committee_members, account_scores, account_intelligence"),
    ("Marketing", "marketing.py, marketing_ext.py, journeys.py, segments.py, preferences.py, landing*.py",
     "Campaigns/audiences/templates, A/B with z-test winner, journey graph runner, dynamic segments + static lists, signed public preference center, landing pages + forms + UTM.",
     "email_campaigns, email_messages, audiences, templates, journey_defs, journey_enrollments, segment_defs, list_memberships, preference_profiles, landing pages/forms tables"),
    ("Sales Engagement", "sequences/engine.py, sales_engagement.py, engagement.py",
     "Cadence engine with contactability gates, reply-sentiment classification → pause/suppress/handoff, epsilon-greedy step A/B, engagement rollups, hot leads.",
     "sequence_definitions/steps/enrollments, person_engagement, variant_performance, suppressions"),
    ("Email Delivery", "delivery.py, delivery_ext.py, deliverability.py, webhook_security.py",
     "Dry-run transport (send-safe), queue/retry, bounce/complaint→suppression, warmup ramp + domain reputation model, inbound webhook signature verification.",
     "send_requests, delivery_events, domain_health"),
    ("Workflow", "rules.py, workflow.py, workflow_durable.py",
     "Trigger/condition/action rules with dry-run, graph workflows with approvals, durable step ledger (idempotency, backoff, DLQ, re-drive).",
     "rules, rule_firings, workflow_defs, workflow_runs, workflow_step_executions"),
    ("AI Core", "llm_core.py, ai_gen.py, decision.py, copilot.py",
     "Versioned prompt registry with rollback, Anthropic/OpenAI/Gemini adapters (honest dry-run without keys), cost/token ledger, eval harness; PII anonymization + QC + c-suite human gates wrap every model call; explainable decision log.",
     "llm_calls, decision_logs, generated drafts tables"),
    ("Analytics", "analytics.py, analytics_fast.py, cohorts.py, attribution.py, reporting.py, unified.py",
     "Event ingest + funnels, cohort retention, time series, 3-model attribution, generic report builder, executive aggregation, email analytics, GA4 measurement-protocol seam.",
     "metric_events (partitioned), web_events (partitioned), report_defs, touches"),
    ("Developer Platform", "developer_platform.py",
     "Hashed API keys with scopes, webhook subscriptions, HMAC-signed deliveries with exponential retry and dead-letter.",
     "api_keys, webhook_subscriptions, webhook_deliveries"),
    ("Compliance", "security_compliance.py, audit_trail.py, models_audit.py",
     "Fernet field encryption, RBAC/ABAC checks, PDPL export/consent/erase, retention purge, universal before/after audit listener.",
     "audit_events (+ retention job in scheduler)"),
    ("Platform Ops", "observability.py, config.py, jobs.py, orchestrator_async.py, deploy/*",
     "JSON logs with request IDs, /health probes, Prometheus metrics, vault-ready secrets seam, durable job queue, scheduler beat, Docker/K8s/Terraform, CI.",
     "jobs, outbox"),
]
for name, files, logic, tables in _modules:
    story.append(KeepTogether([
        Paragraph(esc(name), S_H2),
        Paragraph("<b>Code:</b> <font face='Courier' size='8'>" + esc(files) + "</font>", S_SMALL),
        Paragraph(esc(logic), S_P),
        Paragraph("<b>Tables:</b> " + esc(tables), S_SMALL)]))

# ════════════════════ PART V — GROUND TRUTH CATALOGS ════════════════════
H1("Part V — Ground Truth (auto-generated from the code)")
P("Everything in this part was extracted programmatically at generation time — from "
  "SQLAlchemy metadata, the live FastAPI route table, the migration directory and the test "
  "directory. If the code changes, regenerating this document regenerates these catalogs.")

# database catalog
from database import Base  # noqa: E402
import models, models_ext, models_tenant, models_jobs  # noqa: E402,F401
import models_p10, models_p11, models_p12, models_audit  # noqa: E402,F401
import models_crm2, models_s3, models_s6, models_s8  # noqa: E402,F401
import models_llm, models_collectors, models_segments, models_final  # noqa: E402,F401

H2(f"Database catalog — {len(Base.metadata.tables)} tables")
for tname in sorted(Base.metadata.tables):
    t = Base.metadata.tables[tname]
    cols = ", ".join(c.name for c in t.columns)
    fks = ", ".join(sorted({fk.column.table.name for c in t.columns for fk in c.foreign_keys}))
    body = [Paragraph("<b>" + esc(tname) + "</b>  <font color='#5a6e64' size='7.5'>("
                      + str(len(t.columns)) + " columns" + (", refs: " + esc(fks) if fks else "")
                      + ")</font>", S_P),
            Paragraph("<font face='Courier' size='6.8'>" + esc(cols) + "</font>", S_SMALL)]
    story.append(KeepTogether(body))

# API catalog
os.environ["AUTH_ENFORCED"] = "false"
from main import app  # noqa: E402
H2("API catalog")
rows = [["Method", "Path", "Handler"]]
seen = set()
for r in app.routes:
    methods = sorted(m for m in getattr(r, "methods", []) or [] if m not in ("HEAD", "OPTIONS"))
    path = getattr(r, "path", "")
    name = getattr(r, "name", "")
    for m in methods:
        if (m, path) not in seen:
            seen.add((m, path))
            rows.append([m, path, name])
rows = [rows[0]] + sorted(rows[1:], key=lambda x: (x[1], x[0]))
H3(f"{len(rows)-1} endpoints")
TBL(rows, widths=[1.6 * cm, 9.4 * cm, 6 * cm], font=6.8)

# migrations
H2("Migration chain")
migs = sorted(glob.glob(os.path.join(_ROOT, "alembic", "versions", "*.py")))
rows = [["#", "Revision file", "Purpose (from docstring)"]]
for i, m in enumerate(migs, 1):
    first = ""
    try:
        with open(m, encoding="utf-8") as f:
            for line in f:
                ls = line.strip().strip('"').strip()
                if ls and not ls.startswith(("#", "import", "from")):
                    first = ls
                    break
    except OSError:
        pass
    rows.append([str(i), os.path.basename(m)[:44], first[:95]])
TBL(rows, widths=[0.9 * cm, 6.6 * cm, 9.5 * cm], font=6.8)

# tests
H2("Test suites")
tests = sorted(glob.glob(os.path.join(_ROOT, "tests", "test_*.py")))
rows = [["Suite", "What it proves (from docstring)"]]
for t in tests:
    first = ""
    try:
        src = open(t, encoding="utf-8").read()
        m = re.search(r'"""(.*?)"""', src, re.S)
        if m:
            first = " ".join(m.group(1).split())[:160]
    except OSError:
        pass
    rows.append([os.path.basename(t), first])
TBL(rows, widths=[5.2 * cm, 11.8 * cm], font=6.8)

# env vars
H2("Configuration reference (.env)")
TBL([["Variable", "Purpose"],
     ["DATABASE_URL", "PostgreSQL connection (your data). SQLite fallback if unset."],
     ["AUTH_ENFORCED", "true = every API call needs a token (production posture)"],
     ["JWT_SECRET", "Signing key for login tokens (rotate by changing + restart)"],
     ["ADMIN_EMAIL / ADMIN_PASSWORD", "Your platform login (Settings screen)"],
     ["CORS_ORIGINS", "Browser origins allowed to call the API"],
     ["ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY", "Any ONE turns the AI Center live"],
     ["GA4_MEASUREMENT_ID / GA4_API_SECRET", "Turns Google Analytics events live"],
     ["FIELD_ENCRYPTION_KEY", "Key for PII field encryption"],
     ["AUDIT_RETENTION_DAYS", "Audit-trail retention window (default 365)"],
     ["DASH_PASSWORD", "Legacy BD dashboard password (defaults to ADMIN_PASSWORD)"]],
    widths=[6.4 * cm, 10.6 * cm])

# ════════════════════ PART VI — OPERATIONS ════════════════════
H1("Part VI — Operations Guide")
H2("Running the platform")
CODE("One-time:  pip install -r requirements.txt\n"
     "           python sync_db.py\n"
     "Daily:     double-click 'Start DRIP Platform.bat' (desktop button)\n"
     "           -> syncs DB, starts API+OS (:8000) and legacy dashboard (:5050),\n"
     "              opens http://127.0.0.1:8000/\n"
     "Tests:     run_all_tests.bat  (each suite in its own process)\n"
     "Team LAN:  server binds 0.0.0.0 — colleagues use http://<your-ip>:8000/")
H2("Backups")
P("Your data = the local PostgreSQL 'drip' database. Back it up with "
  "<font face='Courier'>pg_dump -h localhost -U postgres -d drip -F c -f drip_backup.dump</font> "
  "and restore with pg_restore. Do this before major imports. Cloud deployment (Path B) brings "
  "managed automatic backups with point-in-time recovery — see DEPLOYMENT.md and "
  "docs/runbooks/dr_backup.md.")
H2("Monitoring & troubleshooting")
P("Health: /health/ready (API+DB), /metrics (Prometheus). Alert rules ship in "
  "deploy/observability/alerts.yml; the on-call runbook is docs/runbooks/operations.md. "
  "Common issues: 'connection refused' → server window not running (use the desktop button); "
  "column-does-not-exist after an update → run python sync_db.py; 429 on login → wait 5 "
  "minutes (brute-force guard); collectors show errors → source auto-disables after 5 "
  "failures, re-enable by PATCHing enabled=true after the feed recovers.")
H2("Deployment paths")
P("Everything runs locally today by choice. DEPLOYMENT.md documents Path A (Railway/Render — "
  "public URL in ~30 minutes) and Path B (AWS me-south-1 via the included Terraform — PDPL "
  "residency, managed Postgres multi-AZ, EKS). The pre-deploy checklist covers secrets, "
  "migration, data move (pg_dump/restore) and CORS.")

# ════════════════════ PART VII — HONEST STATE, GAPS, ROADMAP ═══════════
H1("Part VII — Honest State: Audits, Gaps, Roadmap")
P("Four independent audit cycles were run against this repository (their full reports are in "
  "the transformation/ folder and are summarized here). The platform's own Feature Parity "
  "screen renders the live registry — the numbers below were current at generation.")
try:
    import capability_registry as _reg
    s = _reg.summary()
    pd_ = _reg.parity_dashboard()
    H2(f"Capability registry — {s['total_capabilities']} capabilities, "
       f"{s['completion_pct']}% complete")
    rows = [["Competitor", "Avg functional parity %"]]
    for k, v in pd_["competitor_parity"].items():
        rows.append([k, str(v)])
    TBL(rows, widths=[8 * cm, 6 * cm])
    H2("Open gaps (planned / blocked-external)")
    rows = [["Module", "Feature", "Status", "Unblocks with"]]
    for g in pd_["top_gaps"]:
        rows.append([g["module"], g["feature"], g["status"], g.get("notes", "")[:70]])
    TBL(rows, widths=[2.6 * cm, 6.4 * cm, 3 * cm, 5 * cm], font=6.8)
except Exception as e:  # noqa: BLE001
    P("registry unavailable: " + esc(e))
H2("What the audits concluded")
P("Method compliance (KEEP/HARDEN/EXTEND, additive migrations, honesty markers, send-safety): "
  "followed with evidence. The 95/100 sprint acceptance gate: violated every sprint — work "
  "shipped as 'delivered', never as 'accepted'. AI-native claim: refused until an LLM key is "
  "configured (the harness is built; the intelligence is deterministic). Tier-1 bank "
  "deployment: not yet — needs SSO, pen test, certifications, HA. The one genuine moat: the "
  "KSA banking intelligence layer (vendor/subsidiary graph, SAMA-aware signals, committee "
  "model, curated dataset) which no compared competitor has.")
H2("Roadmap (90 / 180 / 365 days)")
P("<b>90 days:</b> LLM key → live AI; more collectors (careers, tenders); full-text search "
  "indexes; JWT rotation. <b>180 days:</b> cloud deployment + SSO; SES → real sending with "
  "deliverability validation; one polished customer-grade UI pass (EN/AR); enrichment "
  "provider (Apollo/Clay). <b>365 days:</b> agent orchestration over the LLM core; embeddings "
  "+ semantic search; warehouse/BI for the 100M-signal tier; pen test + SOC2/PDPL "
  "certification; load proof at 100k contacts.")
H2("Closing")
P("DRIP began this journey as a 34/100 collection of scripts and dashboards. It is now one "
  "operating system — one login, one navigation, one database, one search, one audit trail — "
  "purpose-built for selling banking technology in Saudi Arabia, with its remaining distance "
  "to world-class documented honestly in this book and tracked live inside the product "
  "itself. Every claim in this document is backed by a green test in tests/ or a row in the "
  "capability registry.")

# ── appendices: the complete source record, rendered in full ──
H1("Appendix A — Governance (Constitution, Program, Backlog)")
for doc_name in ["CONSTITUTION.md", "SPRINTS.md", "BACKLOG.md", "OS_ARCHITECTURE.md"]:
    p = os.path.join(_ROOT, "transformation", doc_name)
    if os.path.exists(p):
        H2("Document: " + doc_name)
        MD(p)

H1("Appendix B — Sprint & Mission Completion Reports")
for doc_name in ["SPRINT_01_COMPLETION.md", "SPRINT_02_COMPLETION.md",
                 "SPRINTS_03_10_COMPLETION.md", "UNIFICATION.md", "PARITY_MISSION.md"]:
    p = os.path.join(_ROOT, "transformation", doc_name)
    if os.path.exists(p):
        H2("Document: " + doc_name)
        MD(p)

H1("Appendix C — Independent Audit Reports (full text)")
for p in [os.path.join(_ROOT, "INDEPENDENT_AUDIT_REPORT.md"),
          os.path.join(_ROOT, "PRODUCTION_READINESS_REVIEW.md"),
          os.path.join(_ROOT, "transformation", "DUE_DILIGENCE_V2.md"),
          os.path.join(_ROOT, "transformation", "CTO_REVIEW.md"),
          os.path.join(_ROOT, "transformation", "CERTIFICATION.md")]:
    if os.path.exists(p):
        H2("Document: " + os.path.basename(p))
        MD(p)

H1("Appendix D — Engineering Phase Logs (pre-sprint history)")
for p in sorted(glob.glob(os.path.join(_ROOT, "PHASE_*.md"))):
    H2("Document: " + os.path.basename(p))
    MD(p)

H1("Appendix E — Operations & Deployment Documents")
for p in [os.path.join(_ROOT, "DEPLOYMENT.md"),
          os.path.join(_ROOT, "docs", "SLO.md"),
          os.path.join(_ROOT, "docs", "runbooks", "operations.md"),
          os.path.join(_ROOT, "docs", "runbooks", "dr_backup.md"),
          os.path.join(_ROOT, "docs", "api", "crm2.md"),
          os.path.join(_ROOT, "README.md")]:
    if os.path.exists(p):
        H2("Document: " + os.path.basename(p))
        MD(p)

out = os.path.join(_ROOT, "docs", "DRIP_Platform_Complete_Documentation.pdf")
doc = Doc(out, pagesize=A4, leftMargin=1.9 * cm, rightMargin=1.9 * cm,
          topMargin=1.7 * cm, bottomMargin=1.7 * cm,
          title="DRIP OS — Complete Product Documentation",
          author="Decimal Technologies")


def _footer(canv, _doc):
    canv.saveState()
    canv.setFont("Helvetica", 7.5)
    canv.setFillColor(DIM)
    canv.drawString(1.9 * cm, 1 * cm, "DRIP OS — Complete Product Documentation")
    canv.drawRightString(A4[0] - 1.9 * cm, 1 * cm, f"Page {_doc.page}")
    canv.restoreState()


doc.build(story, onLaterPages=_footer, onFirstPage=_footer)
import pypdf  # noqa: E402
n = len(pypdf.PdfReader(out).pages)
print(f"OK: {out} — {n} pages")
