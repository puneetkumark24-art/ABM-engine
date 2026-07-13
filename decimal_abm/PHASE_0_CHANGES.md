# Phase 0 — Code Built This Session

Goal: make the Claude-based ABM engine (scoring/orchestrator/writer/scheduler) the actual
live system, instead of the simpler Gemini/SMTP `engine_scheduler.py` script that had been
running. Nothing here adds new Bible features — it's entirely "make what's already built
actually run."

## Bugs found and fixed

1. **`signals` table schema mismatch** — an earlier migration (`migrate_to_v2.py`) changed
   the live `signals` table to a different column set than `database/db.py` expects.
   `scoring/engine.py`'s `score_signal_strength()` crashed on every run with
   `OperationalError: no such column: institution`. Fixed with additive `ALTER TABLE`
   statements (see `db.py` below) — the historical 235 rows are untouched.
2. **Dashboard was talking to a different database than the engine.** `abm_engine/dashboard/app.py`
   connected to PostgreSQL; the engine writes to SQLite (`abm_engine.db`). Approving a draft
   in the dashboard could never cause it to be sent. Fully rewired to SQLite.
3. **`.env` was silently never loading** when running `python -m abm_engine <command>` —
   plain `load_dotenv()` only searches the current directory and its ancestors, and `.env`
   lives in a subdirectory relative to where `-m` must be invoked from. Every CLI command was
   running with zero API keys. Fixed with an explicit resolved path.
4. **Windows console crash on emoji output** — `sys.stdout` defaults to cp1252 on this
   machine, which can't encode the ✅/❌/🔍 characters the CLI prints, crashing any command
   that hit those lines. Fixed by forcing UTF-8 stdout/stderr.
5. **`research_contact` was `async def` with no actual async I/O inside**, called
   synchronously by every caller (`orchestrator.py`, `__main__.py`). This meant draft
   generation has never worked in this codebase — it always returned an unawaited coroutine
   instead of a result. Fixed by removing `async`.
6. **Stale duplicate `CONTACTS_EXCEL_PATH`** in `.env`, pointing at a path from before the
   project was moved into the `ABM business logic` folder. Removed the stale line; corrected
   the remaining one to be relative to where `-m abm_engine` is actually invoked from.

## Verification performed

- `python -m abm_engine setup` — loads contacts, runs initial scoring. ✅ works.
- `python -m abm_engine status` — pipeline status view. ✅ works.
- Full pipeline dry run (signals → scoring → research → writer → draft save), with the LLM
  call mocked since the Anthropic account is currently out of API credits — confirmed no
  crashes anywhere in the chain. Draft correctly appeared in the dashboard's pending queue.
  All dry-run/mock artifacts were deleted afterward — no fake data was left in the database.
- Dashboard: every page (`/`, `/accounts`, `/contacts`, `/drafts` all filters, `/intelligence`,
  `/templates`, `/audit`, account/contact detail) and every API action (approve, reject, edit,
  redraft, consent update, template CRUD, backup) tested via Flask's test client against real
  data — all return 200 / `{"ok": true}`.
- **Not yet verified live**: a real (non-mocked) AI-generated draft, and the real approve→send
  email path — blocked by the Anthropic account having zero credits. Everything upstream of
  the actual API call is confirmed correct.

---

## File: `abm_engine/database/db.py`

Added: schema-reconciliation migration for `signals`/`unsubscribes`, plus ~15 new helper
functions the dashboard needs (accounts, consent, templates, audit log, unsubscribes, backup).

```python
"""
abm_engine/database/db.py
─────────────────────────
Full database layer — all tables for the complete platform.
"""
from __future__ import annotations
import sqlite3
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from loguru import logger

DB_PATH = Path("abm_engine.db")

def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db() -> None:
    conn = get_conn()
    with conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS accounts (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                name                TEXT NOT NULL UNIQUE,
                account_type        TEXT NOT NULL DEFAULT 'BANK',
                segment             TEXT NOT NULL DEFAULT 'COMMERCIAL',
                country             TEXT DEFAULT 'Saudi Arabia',
                website             TEXT,
                description         TEXT,
                has_warm_contact    INTEGER DEFAULT 0,
                sama_pressure       INTEGER DEFAULT 0,
                is_greenfield       INTEGER DEFAULT 0,
                composite_score     INTEGER DEFAULT 0,
                tier                TEXT DEFAULT 'COLD',
                score_updated_at    TEXT,
                is_active           INTEGER DEFAULT 1,
                hubspot_company_id  TEXT,
                created_at          TEXT DEFAULT (datetime('now')),
                updated_at          TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS contacts (
                id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id              INTEGER REFERENCES accounts(id),
                full_name               TEXT NOT NULL,
                role                    TEXT NOT NULL,
                persona                 TEXT DEFAULT 'OTHER',
                seniority               TEXT DEFAULT 'VP',
                is_ksa_national         INTEGER DEFAULT 0,
                relationship_type       TEXT DEFAULT 'TARGET',
                institution             TEXT NOT NULL,
                country                 TEXT DEFAULT 'Saudi Arabia',
                institution_type        TEXT DEFAULT 'Bank',
                segment                 TEXT DEFAULT 'COMMERCIAL',
                email                   TEXT,
                email_confidence        TEXT,
                linkedin_url            TEXT,
                whatsapp                TEXT,
                phone                   TEXT,
                phone_status            TEXT,
                key_signal              TEXT,
                outreach_angle          TEXT,
                product_fit             TEXT,
                warmness                TEXT DEFAULT 'Cold',
                has_warm_relationship   INTEGER DEFAULT 0,
                background_notes        TEXT,
                pitch_notes             TEXT,
                connection_paths        TEXT,
                priority_score          INTEGER DEFAULT 0,
                tier                    TEXT DEFAULT 'COLD',
                hubspot_contact_id      TEXT,
                current_touch           INTEGER DEFAULT 0,
                is_active               INTEGER DEFAULT 1,
                replied                 INTEGER DEFAULT 0,
                reply_handled           INTEGER DEFAULT 0,
                created_at              TEXT DEFAULT (datetime('now')),
                updated_at              TEXT DEFAULT (datetime('now')),
                last_touch_at           TEXT
            );

            CREATE TABLE IF NOT EXISTS draft_messages (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                contact_id          INTEGER NOT NULL REFERENCES contacts(id),
                touch_number        INTEGER NOT NULL,
                touch_type          TEXT NOT NULL,
                language            TEXT DEFAULT 'EN',
                subject             TEXT,
                body_en             TEXT NOT NULL DEFAULT '',
                body_ar             TEXT,
                hook_used           TEXT DEFAULT '',
                status              TEXT DEFAULT 'DRAFT',
                rejection_reason    TEXT,
                mailchimp_id        TEXT,
                sendgrid_id         TEXT,
                heyreach_id         TEXT,
                hubspot_id          TEXT,
                generated_at        TEXT DEFAULT (datetime('now')),
                reviewed_at         TEXT,
                sent_at             TEXT
            );

            CREATE TABLE IF NOT EXISTS touch_records (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                contact_id      INTEGER NOT NULL REFERENCES contacts(id),
                draft_id        INTEGER REFERENCES draft_messages(id),
                touch_number    INTEGER NOT NULL,
                touch_type      TEXT NOT NULL,
                language        TEXT DEFAULT 'EN',
                status          TEXT DEFAULT 'DRAFT',
                subject         TEXT,
                body            TEXT NOT NULL DEFAULT '',
                body_ar         TEXT,
                signal_used     TEXT,
                sendgrid_id     TEXT,
                mailchimp_id    TEXT,
                heyreach_id     TEXT,
                hubspot_id      TEXT,
                scheduled_at    TEXT,
                sent_at         TEXT,
                opened_at       TEXT,
                replied_at      TEXT,
                error           TEXT
            );

            CREATE TABLE IF NOT EXISTS signals (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                institution     TEXT NOT NULL,
                signal_type     TEXT NOT NULL,
                priority        TEXT NOT NULL,
                headline        TEXT NOT NULL,
                detail          TEXT NOT NULL,
                source_url      TEXT,
                source_name     TEXT DEFAULT '',
                score_impact    INTEGER DEFAULT 0,
                detected_at     TEXT DEFAULT (datetime('now')),
                used_in_touch   INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS news_items (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                category        TEXT NOT NULL,
                institution     TEXT DEFAULT '',
                contact_name    TEXT,
                headline        TEXT NOT NULL,
                summary         TEXT NOT NULL,
                source_url      TEXT,
                source_name     TEXT DEFAULT '',
                relevance_score INTEGER DEFAULT 0,
                detected_at     TEXT DEFAULT (datetime('now')),
                is_read         INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS score_breakdowns (
                id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                contact_id              INTEGER NOT NULL REFERENCES contacts(id),
                institution             TEXT NOT NULL,
                signal_strength         INTEGER DEFAULT 0,
                regulatory_pressure     INTEGER DEFAULT 0,
                persona_reachability    INTEGER DEFAULT 0,
                existing_relationship   INTEGER DEFAULT 0,
                composite_score         INTEGER DEFAULT 0,
                tier                    TEXT DEFAULT 'COLD',
                scored_at               TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS engagement_events (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                contact_id    INTEGER NOT NULL REFERENCES contacts(id),
                touch_id      INTEGER REFERENCES touch_records(id),
                event_type    TEXT NOT NULL,
                raw_content   TEXT,
                received_at   TEXT DEFAULT (datetime('now')),
                notified      INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS kpi_snapshots (
                id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                week_start              TEXT NOT NULL UNIQUE,
                touches_sent            INTEGER DEFAULT 0,
                emails_sent             INTEGER DEFAULT 0,
                linkedin_sent           INTEGER DEFAULT 0,
                emails_opened           INTEGER DEFAULT 0,
                replies_received        INTEGER DEFAULT 0,
                linkedin_accepts        INTEGER DEFAULT 0,
                meetings_booked         INTEGER DEFAULT 0,
                pipeline_value_usd      INTEGER DEFAULT 0,
                open_rate_pct           REAL DEFAULT 0,
                reply_rate_pct          REAL DEFAULT 0,
                engagement_rate_pct     REAL DEFAULT 0,
                hot_replies             INTEGER DEFAULT 0,
                warm_replies            INTEGER DEFAULT 0,
                cold_replies            INTEGER DEFAULT 0,
                computed_at             TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS research_cache (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                contact_id       INTEGER NOT NULL REFERENCES contacts(id),
                fresh_signals    TEXT,
                recommended_hook TEXT,
                context_summary  TEXT,
                researched_at    TEXT DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_contacts_tier        ON contacts(tier);
            CREATE INDEX IF NOT EXISTS idx_contacts_active      ON contacts(is_active);
            CREATE INDEX IF NOT EXISTS idx_contacts_rel         ON contacts(relationship_type);
            CREATE INDEX IF NOT EXISTS idx_drafts_status        ON draft_messages(status);
            CREATE INDEX IF NOT EXISTS idx_drafts_contact       ON draft_messages(contact_id);
            CREATE INDEX IF NOT EXISTS idx_news_category        ON news_items(category);
            CREATE INDEX IF NOT EXISTS idx_news_read            ON news_items(is_read);
            CREATE INDEX IF NOT EXISTS idx_touches_contact      ON touch_records(contact_id);
            CREATE INDEX IF NOT EXISTS idx_events_contact       ON engagement_events(contact_id);
        """)
    _ensure_signals_columns(conn)
    _ensure_unsubscribes_columns(conn)
    logger.info("Database initialised at {}", DB_PATH)


# ─── Schema reconciliation ────────────────────────────────────────────────────
# The live `signals` table was created by an earlier migration (migrate_to_v2.py)
# with a different column set than this module expects. CREATE TABLE IF NOT EXISTS
# above is a no-op against that existing table, so the columns save_signal() /
# get_signals_for_institution() need must be added additively here. Safe to run
# on every init_db() call — each ALTER is guarded against re-running.
_SIGNALS_V1_COLUMNS = {
    "institution":   "TEXT",
    "priority":      "TEXT",
    "headline":      "TEXT",
    "detail":        "TEXT",
    "source_url":    "TEXT",
    "source_name":   "TEXT DEFAULT ''",
    "score_impact":  "INTEGER DEFAULT 0",
    "detected_at":   "TEXT",   # non-constant defaults aren't allowed via ALTER TABLE; set explicitly in INSERT
    "used_in_touch": "INTEGER DEFAULT 0",
}

def _ensure_signals_columns(conn: sqlite3.Connection) -> None:
    existing = {r["name"] for r in conn.execute("PRAGMA table_info(signals)").fetchall()}
    with conn:
        for col, decl in _SIGNALS_V1_COLUMNS.items():
            if col not in existing:
                conn.execute(f"ALTER TABLE signals ADD COLUMN {col} {decl}")
                logger.info("Added missing column signals.{}", col)
        # Safe now that the `institution` column is guaranteed to exist.
        conn.execute("CREATE INDEX IF NOT EXISTS idx_signals_institution ON signals(institution)")


def _ensure_unsubscribes_columns(conn: sqlite3.Connection) -> None:
    existing = {r["name"] for r in conn.execute("PRAGMA table_info(unsubscribes)").fetchall()}
    if "token" not in existing:
        with conn:
            conn.execute("ALTER TABLE unsubscribes ADD COLUMN token TEXT DEFAULT ''")
            logger.info("Added missing column unsubscribes.token")


# ─── Account CRUD ─────────────────────────────────────────────────────────────

def upsert_account(name, account_type, segment, country="Saudi Arabia",
                   is_greenfield=False, description="") -> int:
    conn = get_conn()
    with conn:
        cur = conn.execute("""
            INSERT INTO accounts (name, account_type, segment, country, is_greenfield, description)
            VALUES (?,?,?,?,?,?)
            ON CONFLICT(name) DO UPDATE SET
                account_type=excluded.account_type,
                description=COALESCE(excluded.description, description),
                updated_at=datetime('now')
        """, (name, account_type, segment, country, int(is_greenfield), description))
        if cur.lastrowid:
            return cur.lastrowid
        row = conn.execute("SELECT id FROM accounts WHERE name=?", (name,)).fetchone()
        return row["id"]

def get_all_accounts() -> list[dict]:
    conn = get_conn()
    return [dict(r) for r in conn.execute(
        "SELECT * FROM accounts WHERE is_active=1 ORDER BY composite_score DESC"
    ).fetchall()]

def update_account_score(account_id, score, tier):
    conn = get_conn()
    with conn:
        conn.execute("""
            UPDATE accounts SET composite_score=?, tier=?,
            score_updated_at=datetime('now'), updated_at=datetime('now')
            WHERE id=?
        """, (score, tier, account_id))


# ─── Contact CRUD ─────────────────────────────────────────────────────────────

def upsert_contact(c) -> int:
    conn = get_conn()
    with conn:
        existing = conn.execute(
            "SELECT id FROM contacts WHERE full_name=? AND institution=?",
            (c.full_name, c.institution)
        ).fetchone()
        if existing:
            conn.execute("""
                UPDATE contacts SET
                    role=?, persona=?, seniority=?, is_ksa_national=?,
                    relationship_type=?,
                    email=COALESCE(?,email), email_confidence=COALESCE(?,email_confidence),
                    linkedin_url=COALESCE(?,linkedin_url),
                    whatsapp=COALESCE(?,whatsapp), phone=COALESCE(?,phone),
                    phone_status=COALESCE(?,phone_status),
                    key_signal=COALESCE(NULLIF(?,?),key_signal),
                    outreach_angle=COALESCE(NULLIF(?,?),outreach_angle),
                    product_fit=COALESCE(NULLIF(?,?),product_fit),
                    warmness=?, has_warm_relationship=?,
                    background_notes=COALESCE(?,background_notes),
                    pitch_notes=COALESCE(?,pitch_notes),
                    connection_paths=COALESCE(?,connection_paths),
                    priority_score=?, tier=?,
                    updated_at=datetime('now')
                WHERE id=?
            """, (
                c.role, c.persona, c.seniority, int(c.is_ksa_national),
                c.relationship_type,
                c.email, c.email_confidence, c.linkedin_url,
                c.whatsapp, c.phone, c.phone_status,
                c.key_signal, "", c.outreach_angle, "", c.product_fit, "",
                c.warmness, int(c.has_warm_relationship),
                c.background_notes, c.pitch_notes, c.connection_paths,
                c.priority_score, c.tier,
                existing["id"]
            ))
            return existing["id"]
        cur = conn.execute("""
            INSERT INTO contacts (
                account_id, full_name, role, persona, seniority, is_ksa_national,
                relationship_type,
                institution, country, institution_type, segment,
                email, email_confidence, linkedin_url, whatsapp, phone, phone_status,
                key_signal, outreach_angle, product_fit, warmness,
                has_warm_relationship, background_notes, pitch_notes, connection_paths,
                priority_score, tier
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            getattr(c, "account_id", None),
            c.full_name, c.role, c.persona, c.seniority, int(c.is_ksa_national),
            c.relationship_type,
            c.institution, c.country, c.institution_type, c.segment,
            c.email, c.email_confidence, c.linkedin_url,
            c.whatsapp, c.phone, c.phone_status,
            c.key_signal, c.outreach_angle, c.product_fit, c.warmness,
            int(c.has_warm_relationship),
            c.background_notes, c.pitch_notes, c.connection_paths,
            c.priority_score, c.tier
        ))
        return cur.lastrowid


def get_contacts_due_for_outreach(limit=20) -> list[dict]:
    """Contacts ready for next touch — HOT first, warm relationships first."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT c.* FROM contacts c
        LEFT JOIN touch_records t
            ON t.contact_id = c.id AND t.status = 'SENT'
            AND t.sent_at > datetime('now', '-3 days')
        WHERE c.is_active = 1 AND c.replied = 0 AND c.current_touch < 5
          AND t.id IS NULL
        ORDER BY
            CASE c.tier WHEN 'HOT' THEN 1 WHEN 'WARM' THEN 2 ELSE 3 END,
            c.has_warm_relationship DESC,
            c.priority_score DESC
        LIMIT ?
    """, (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_contacts_for_scoring() -> list[dict]:
    conn = get_conn()
    return [dict(r) for r in conn.execute(
        "SELECT * FROM contacts WHERE is_active=1 ORDER BY institution, priority_score DESC"
    ).fetchall()]


def get_all_contacts(search="", relationship_type="", tier="") -> list[dict]:
    conn = get_conn()
    sql = "SELECT * FROM contacts WHERE is_active=1"
    params = []
    if search:
        sql += " AND (full_name LIKE ? OR institution LIKE ? OR role LIKE ?)"
        params += [f"%{search}%", f"%{search}%", f"%{search}%"]
    if relationship_type:
        sql += " AND relationship_type=?"
        params.append(relationship_type)
    if tier:
        sql += " AND tier=?"
        params.append(tier)
    sql += " ORDER BY priority_score DESC, full_name"
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def get_contact_by_id(contact_id) -> Optional[dict]:
    conn = get_conn()
    row = conn.execute("SELECT * FROM contacts WHERE id=?", (contact_id,)).fetchone()
    return dict(row) if row else None


def update_contact_score(contact_id, score, tier):
    conn = get_conn()
    with conn:
        conn.execute("""
            UPDATE contacts SET priority_score=?, tier=?, updated_at=datetime('now') WHERE id=?
        """, (score, tier, contact_id))


def mark_contact_replied(contact_id):
    conn = get_conn()
    with conn:
        conn.execute("""
            UPDATE contacts SET replied=1, updated_at=datetime('now') WHERE id=?
        """, (contact_id,))


def increment_touch(contact_id):
    conn = get_conn()
    with conn:
        conn.execute("""
            UPDATE contacts SET current_touch=current_touch+1,
            last_touch_at=datetime('now'), updated_at=datetime('now') WHERE id=?
        """, (contact_id,))


def update_hubspot_id(contact_id, hubspot_id):
    conn = get_conn()
    with conn:
        conn.execute(
            "UPDATE contacts SET hubspot_contact_id=? WHERE id=?",
            (hubspot_id, contact_id)
        )


# ─── Draft Messages ───────────────────────────────────────────────────────────

def save_draft(contact_id, touch_number, touch_type, language,
               subject, body_en, body_ar, hook_used) -> int:
    conn = get_conn()
    with conn:
        cur = conn.execute("""
            INSERT INTO draft_messages
                (contact_id, touch_number, touch_type, language,
                 subject, body_en, body_ar, hook_used, status)
            VALUES (?,?,?,?,?,?,?,?,'DRAFT')
        """, (contact_id, touch_number, touch_type, language,
              subject, body_en, body_ar, hook_used))
        return cur.lastrowid


def get_pending_drafts(limit=50) -> list[dict]:
    """All drafts waiting for human approval."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT d.*, c.full_name, c.institution, c.role, c.tier,
               c.relationship_type, c.email, c.linkedin_url,
               c.background_notes, c.pitch_notes
        FROM draft_messages d
        JOIN contacts c ON c.id = d.contact_id
        WHERE d.status = 'DRAFT'
        ORDER BY
            CASE c.tier WHEN 'HOT' THEN 1 WHEN 'WARM' THEN 2 ELSE 3 END,
            d.generated_at DESC
        LIMIT ?
    """, (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_draft_by_id(draft_id) -> Optional[dict]:
    conn = get_conn()
    row = conn.execute("""
        SELECT d.*, c.full_name, c.institution, c.role, c.tier,
               c.relationship_type, c.email, c.linkedin_url
        FROM draft_messages d
        JOIN contacts c ON c.id = d.contact_id
        WHERE d.id=?
    """, (draft_id,)).fetchone()
    return dict(row) if row else None


def approve_draft(draft_id) -> bool:
    conn = get_conn()
    with conn:
        conn.execute("""
            UPDATE draft_messages SET status='APPROVED', reviewed_at=datetime('now')
            WHERE id=? AND status='DRAFT'
        """, (draft_id,))
    return True


def reject_draft(draft_id, reason="") -> bool:
    conn = get_conn()
    with conn:
        conn.execute("""
            UPDATE draft_messages SET status='REJECTED',
            rejection_reason=?, reviewed_at=datetime('now')
            WHERE id=? AND status='DRAFT'
        """, (reason, draft_id))
    return True


def update_draft_body(draft_id, subject, body_en, body_ar=None):
    conn = get_conn()
    with conn:
        conn.execute("""
            UPDATE draft_messages SET subject=?, body_en=?, body_ar=?
            WHERE id=?
        """, (subject, body_en, body_ar, draft_id))


def get_approved_unsent_drafts() -> list[dict]:
    conn = get_conn()
    rows = conn.execute("""
        SELECT d.*, c.full_name, c.institution, c.role, c.tier,
               c.relationship_type, c.email, c.linkedin_url,
               c.hubspot_contact_id
        FROM draft_messages d
        JOIN contacts c ON c.id = d.contact_id
        WHERE d.status = 'APPROVED' AND d.sent_at IS NULL
        ORDER BY d.reviewed_at
    """).fetchall()
    return [dict(r) for r in rows]


def mark_draft_sent(draft_id, sendgrid_id=None, mailchimp_id=None,
                    heyreach_id=None, hubspot_id=None):
    conn = get_conn()
    with conn:
        conn.execute("""
            UPDATE draft_messages SET status='SENT', sent_at=datetime('now'),
            sendgrid_id=COALESCE(?,sendgrid_id),
            mailchimp_id=COALESCE(?,mailchimp_id),
            heyreach_id=COALESCE(?,heyreach_id),
            hubspot_id=COALESCE(?,hubspot_id)
            WHERE id=?
        """, (sendgrid_id, mailchimp_id, heyreach_id, hubspot_id, draft_id))


def get_draft_counts() -> dict:
    conn = get_conn()
    row = conn.execute("""
        SELECT
            SUM(CASE WHEN status='DRAFT'    THEN 1 ELSE 0 END) pending,
            SUM(CASE WHEN status='APPROVED' AND sent_at IS NULL THEN 1 ELSE 0 END) approved,
            SUM(CASE WHEN status='REJECTED' THEN 1 ELSE 0 END) rejected,
            SUM(CASE WHEN status='SENT'     THEN 1 ELSE 0 END) sent
        FROM draft_messages
    """).fetchone()
    return dict(row) if row else {}


# ─── Signal CRUD ──────────────────────────────────────────────────────────────

def save_signal(institution, signal_type, priority, headline, detail,
                source_url="", source_name="", score_impact=0) -> int:
    conn = get_conn()
    with conn:
        existing = conn.execute("""
            SELECT id FROM signals WHERE institution=? AND headline=?
            AND detected_at > datetime('now', '-7 days')
        """, (institution, headline)).fetchone()
        if existing:
            return existing["id"]
        cur = conn.execute("""
            INSERT INTO signals (institution, signal_type, priority, headline,
                detail, source_url, source_name, score_impact, detected_at)
            VALUES (?,?,?,?,?,?,?,?,datetime('now'))
        """, (institution, signal_type, priority, headline, detail,
              source_url, source_name, score_impact))
        return cur.lastrowid


def get_signals_for_institution(institution, days=30) -> list[dict]:
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM signals WHERE institution=?
        AND detected_at > datetime('now', ? || ' days')
        ORDER BY CASE priority WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 ELSE 3 END,
                 detected_at DESC
    """, (institution, f"-{days}")).fetchall()
    return [dict(r) for r in rows]


def get_recent_signals(hours=24) -> list[dict]:
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM signals
        WHERE detected_at > datetime('now', ? || ' hours')
        ORDER BY CASE priority WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 ELSE 3 END,
                 detected_at DESC
    """, (f"-{hours}",)).fetchall()
    return [dict(r) for r in rows]


# ─── News Items ───────────────────────────────────────────────────────────────

def save_news_item(category, headline, summary, institution="",
                   contact_name=None, source_url="", source_name="",
                   relevance_score=5) -> int:
    conn = get_conn()
    with conn:
        existing = conn.execute("""
            SELECT id FROM news_items WHERE headline=?
            AND detected_at > datetime('now', '-3 days')
        """, (headline,)).fetchone()
        if existing:
            return existing["id"]
        cur = conn.execute("""
            INSERT INTO news_items
                (category, institution, contact_name, headline, summary,
                 source_url, source_name, relevance_score)
            VALUES (?,?,?,?,?,?,?,?)
        """, (category, institution, contact_name, headline, summary,
              source_url, source_name, relevance_score))
        logger.info("News: [{}] {} — {}", category, institution or contact_name, headline[:60])
        return cur.lastrowid


def get_news_feed(category="", unread_only=False, limit=50) -> list[dict]:
    conn = get_conn()
    sql = "SELECT * FROM news_items WHERE 1=1"
    params = []
    if category:
        sql += " AND category=?"
        params.append(category)
    if unread_only:
        sql += " AND is_read=0"
    sql += " ORDER BY relevance_score DESC, detected_at DESC LIMIT ?"
    params.append(limit)
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def mark_news_read(news_id):
    conn = get_conn()
    with conn:
        conn.execute("UPDATE news_items SET is_read=1 WHERE id=?", (news_id,))


def get_news_counts() -> dict:
    conn = get_conn()
    row = conn.execute("""
        SELECT
            SUM(CASE WHEN is_read=0 THEN 1 ELSE 0 END) unread,
            SUM(CASE WHEN category='BANK_FI' AND is_read=0 THEN 1 ELSE 0 END) bank_fi,
            SUM(CASE WHEN category='VENDOR'  AND is_read=0 THEN 1 ELSE 0 END) vendor,
            SUM(CASE WHEN category='SAMA'    AND is_read=0 THEN 1 ELSE 0 END) sama,
            SUM(CASE WHEN category='LEADERSHIP' AND is_read=0 THEN 1 ELSE 0 END) leadership
        FROM news_items
    """).fetchone()
    return dict(row) if row else {}


# ─── Score Breakdown ──────────────────────────────────────────────────────────

def save_score_breakdown(contact_id, institution, signal_strength,
                         regulatory_pressure, persona_reachability,
                         existing_relationship, composite_score, tier):
    conn = get_conn()
    with conn:
        conn.execute("""
            INSERT INTO score_breakdowns
                (contact_id, institution, signal_strength, regulatory_pressure,
                 persona_reachability, existing_relationship, composite_score, tier)
            VALUES (?,?,?,?,?,?,?,?)
        """, (contact_id, institution, signal_strength, regulatory_pressure,
              persona_reachability, existing_relationship, composite_score, tier))


# ─── Touch Records ────────────────────────────────────────────────────────────

def save_touch(t) -> int:
    conn = get_conn()
    with conn:
        cur = conn.execute("""
            INSERT INTO touch_records
                (contact_id, draft_id, touch_number, touch_type, language, status,
                 subject, body, body_ar, signal_used)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (
            t.contact_id, getattr(t, "draft_id", None),
            t.touch_number, t.touch_type,
            getattr(t, "language", "EN"), t.status,
            t.subject, t.body, getattr(t, "body_ar", None),
            getattr(t, "signal_used", None)
        ))
        return cur.lastrowid


def update_touch_status(touch_id, status, sendgrid_id=None, mailchimp_id=None,
                        heyreach_id=None, hubspot_id=None, error=None):
    now = datetime.utcnow().isoformat()
    conn = get_conn()
    with conn:
        conn.execute("""
            UPDATE touch_records SET
                status=?,
                sent_at=CASE WHEN ?='SENT' THEN ? ELSE sent_at END,
                sendgrid_id=COALESCE(?,sendgrid_id),
                mailchimp_id=COALESCE(?,mailchimp_id),
                heyreach_id=COALESCE(?,heyreach_id),
                hubspot_id=COALESCE(?,hubspot_id),
                error=COALESCE(?,error)
            WHERE id=?
        """, (status, status, now, sendgrid_id, mailchimp_id,
              heyreach_id, hubspot_id, error, touch_id))


def get_touch_history(contact_id) -> list[dict]:
    conn = get_conn()
    return [dict(r) for r in conn.execute(
        "SELECT * FROM touch_records WHERE contact_id=? ORDER BY touch_number",
        (contact_id,)
    ).fetchall()]


# ─── Engagement Events ────────────────────────────────────────────────────────

def save_engagement(e) -> int:
    conn = get_conn()
    with conn:
        cur = conn.execute("""
            INSERT INTO engagement_events (contact_id, touch_id, event_type, raw_content)
            VALUES (?,?,?,?)
        """, (e.contact_id, e.touch_id, e.event_type, e.raw_content))
        return cur.lastrowid


def get_unnotified_events() -> list[dict]:
    conn = get_conn()
    rows = conn.execute("""
        SELECT e.*, c.full_name, c.institution, c.role, c.tier
        FROM engagement_events e
        JOIN contacts c ON c.id=e.contact_id
        WHERE e.notified=0 ORDER BY e.received_at DESC
    """).fetchall()
    return [dict(r) for r in rows]


def mark_events_notified(ids):
    if not ids:
        return
    placeholders = ",".join("?" * len(ids))
    conn = get_conn()
    with conn:
        conn.execute(
            f"UPDATE engagement_events SET notified=1 WHERE id IN ({placeholders})", ids
        )


# ─── KPI ─────────────────────────────────────────────────────────────────────

def compute_kpi_for_week(week_start) -> dict:
    conn = get_conn()
    week_end = (datetime.fromisoformat(week_start) + timedelta(days=7)).isoformat()

    def q(sql, *args):
        return conn.execute(sql, args).fetchone()[0] or 0

    emails_sent   = q("SELECT COUNT(*) FROM touch_records WHERE touch_type='EMAIL' AND status='SENT' AND sent_at>=? AND sent_at<?", week_start, week_end)
    li_sent       = q("SELECT COUNT(*) FROM touch_records WHERE touch_type='LINKEDIN' AND status='SENT' AND sent_at>=? AND sent_at<?", week_start, week_end)
    emails_opened = q("SELECT COUNT(*) FROM engagement_events WHERE event_type='email_open' AND received_at>=? AND received_at<?", week_start, week_end)
    replies       = q("SELECT COUNT(*) FROM engagement_events WHERE event_type IN ('email_reply','linkedin_reply') AND received_at>=? AND received_at<?", week_start, week_end)
    li_accepts    = q("SELECT COUNT(*) FROM engagement_events WHERE event_type='linkedin_accept' AND received_at>=? AND received_at<?", week_start, week_end)

    def tier_replies(tier):
        return conn.execute("""
            SELECT COUNT(*) FROM engagement_events e
            JOIN contacts c ON c.id=e.contact_id
            WHERE e.event_type IN ('email_reply','linkedin_reply')
              AND e.received_at>=? AND e.received_at<? AND c.tier=?
        """, (week_start, week_end, tier)).fetchone()[0] or 0

    touches    = emails_sent + li_sent
    open_rate  = round(emails_opened / emails_sent * 100, 1) if emails_sent else 0.0
    reply_rate = round(replies / emails_sent * 100, 1) if emails_sent else 0.0
    eng_rate   = round((replies + emails_opened + li_accepts) / touches * 100, 1) if touches else 0.0

    return {
        "touches_sent": touches, "emails_sent": emails_sent, "linkedin_sent": li_sent,
        "emails_opened": emails_opened, "replies_received": replies,
        "linkedin_accepts": li_accepts, "meetings_booked": 0,
        "pipeline_value_usd": 0, "open_rate_pct": open_rate,
        "reply_rate_pct": reply_rate, "engagement_rate_pct": eng_rate,
        "hot_replies": tier_replies("HOT"), "warm_replies": tier_replies("WARM"),
        "cold_replies": tier_replies("COLD"),
    }


def upsert_kpi_snapshot(week_start, data):
    conn = get_conn()
    with conn:
        conn.execute("""
            INSERT INTO kpi_snapshots (week_start, touches_sent, emails_sent, linkedin_sent,
                emails_opened, replies_received, linkedin_accepts, meetings_booked,
                pipeline_value_usd, open_rate_pct, reply_rate_pct, engagement_rate_pct,
                hot_replies, warm_replies, cold_replies, computed_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(week_start) DO UPDATE SET
                touches_sent=excluded.touches_sent, emails_sent=excluded.emails_sent,
                linkedin_sent=excluded.linkedin_sent, emails_opened=excluded.emails_opened,
                replies_received=excluded.replies_received, linkedin_accepts=excluded.linkedin_accepts,
                meetings_booked=excluded.meetings_booked, pipeline_value_usd=excluded.pipeline_value_usd,
                open_rate_pct=excluded.open_rate_pct, reply_rate_pct=excluded.reply_rate_pct,
                engagement_rate_pct=excluded.engagement_rate_pct,
                hot_replies=excluded.hot_replies, warm_replies=excluded.warm_replies,
                cold_replies=excluded.cold_replies, computed_at=excluded.computed_at
        """, (
            week_start,
            data.get("touches_sent",0), data.get("emails_sent",0),
            data.get("linkedin_sent",0), data.get("emails_opened",0),
            data.get("replies_received",0), data.get("linkedin_accepts",0),
            data.get("meetings_booked",0), data.get("pipeline_value_usd",0),
            data.get("open_rate_pct",0.0), data.get("reply_rate_pct",0.0),
            data.get("engagement_rate_pct",0.0),
            data.get("hot_replies",0), data.get("warm_replies",0),
            data.get("cold_replies",0),
            datetime.utcnow().isoformat()
        ))


def get_dashboard_stats() -> dict:
    conn = get_conn()
    contacts = conn.execute("""
        SELECT
            COUNT(*) total,
            SUM(CASE WHEN tier='HOT' THEN 1 ELSE 0 END) hot,
            SUM(CASE WHEN tier='WARM' THEN 1 ELSE 0 END) warm,
            SUM(CASE WHEN tier='COLD' THEN 1 ELSE 0 END) cold,
            SUM(CASE WHEN replied=1 THEN 1 ELSE 0 END) replied,
            SUM(CASE WHEN relationship_type='TARGET'    THEN 1 ELSE 0 END) targets,
            SUM(CASE WHEN relationship_type='VENDOR'    THEN 1 ELSE 0 END) vendors,
            SUM(CASE WHEN relationship_type='CONNECTOR' THEN 1 ELSE 0 END) connectors,
            SUM(CASE WHEN relationship_type='CHAMPION'  THEN 1 ELSE 0 END) champions
        FROM contacts WHERE is_active=1
    """).fetchone()
    drafts = get_draft_counts()
    news   = get_news_counts()
    return {
        "contacts": dict(contacts) if contacts else {},
        "drafts":   drafts,
        "news":     news,
    }


# ─── Account queries (dashboard) ──────────────────────────────────────────────

def get_account_by_id(account_id) -> Optional[dict]:
    conn = get_conn()
    row = conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
    return dict(row) if row else None


def get_accounts_filtered(search="", tier="", segment="") -> list[dict]:
    conn = get_conn()
    sql = """
        SELECT a.*,
            (SELECT COUNT(*) FROM contacts c WHERE c.account_id=a.id AND c.is_active=1) as contact_count,
            (SELECT COUNT(*) FROM signals s WHERE s.institution=a.name) as signal_count,
            (SELECT COUNT(*) FROM draft_messages d JOIN contacts c ON c.id=d.contact_id WHERE c.account_id=a.id) as draft_count
        FROM accounts a WHERE a.is_active=1
    """
    params = []
    if search:
        sql += " AND (a.name LIKE ? OR a.segment LIKE ?)"
        params += [f"%{search}%", f"%{search}%"]
    if tier:
        sql += " AND a.tier=?"
        params.append(tier)
    if segment:
        sql += " AND a.segment=?"
        params.append(segment)
    sql += " ORDER BY CASE a.tier WHEN 'HOT' THEN 1 WHEN 'WARM' THEN 2 ELSE 3 END, a.composite_score DESC, a.name"
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def get_contacts_for_account(account_id) -> list[dict]:
    conn = get_conn()
    return [dict(r) for r in conn.execute("""
        SELECT * FROM contacts WHERE account_id=? AND is_active=1 ORDER BY seniority, full_name
    """, (account_id,)).fetchall()]


def get_signals_for_account_name(institution, limit=20) -> list[dict]:
    conn = get_conn()
    return [dict(r) for r in conn.execute("""
        SELECT * FROM signals WHERE institution=? ORDER BY detected_at DESC LIMIT ?
    """, (institution, limit)).fetchall()]


def get_drafts_for_account(account_id, limit=10) -> list[dict]:
    conn = get_conn()
    return [dict(r) for r in conn.execute("""
        SELECT d.*, c.full_name as contact_name FROM draft_messages d
        JOIN contacts c ON c.id=d.contact_id
        WHERE c.account_id=? ORDER BY d.generated_at DESC LIMIT ?
    """, (account_id, limit)).fetchall()]


def get_touches_for_account(account_id, limit=20) -> list[dict]:
    conn = get_conn()
    return [dict(r) for r in conn.execute("""
        SELECT t.*, c.full_name as contact_name FROM touch_records t
        JOIN contacts c ON c.id=t.contact_id
        WHERE c.account_id=? ORDER BY t.sent_at DESC LIMIT ?
    """, (account_id, limit)).fetchall()]


# ─── Contact consent ───────────────────────────────────────────────────────────

def update_contact_consent(contact_id, consent_status, consent_source="") -> None:
    conn = get_conn()
    with conn:
        conn.execute("""
            UPDATE contacts SET consent_status=?, consent_date=datetime('now'),
            consent_source=?, updated_at=datetime('now') WHERE id=?
        """, (consent_status, consent_source, contact_id))


# ─── Templates (dashboard CRUD) ────────────────────────────────────────────────

def get_templates() -> list[dict]:
    conn = get_conn()
    return [dict(r) for r in conn.execute(
        "SELECT * FROM templates ORDER BY updated_at DESC"
    ).fetchall()]


def get_template_by_id(template_id) -> Optional[dict]:
    conn = get_conn()
    row = conn.execute("SELECT * FROM templates WHERE id=?", (template_id,)).fetchone()
    return dict(row) if row else None


def save_template(template_id, name, channel, subject, body) -> int:
    conn = get_conn()
    with conn:
        if template_id:
            conn.execute("""
                UPDATE templates SET name=?, channel=?, subject=?, body=?,
                updated_at=datetime('now') WHERE id=?
            """, (name, channel, subject, body, template_id))
            return template_id
        cur = conn.execute("""
            INSERT INTO templates (name, channel, subject, body) VALUES (?,?,?,?)
        """, (name, channel, subject, body))
        return cur.lastrowid


def delete_template(template_id) -> None:
    conn = get_conn()
    with conn:
        conn.execute("DELETE FROM templates WHERE id=?", (template_id,))


# ─── Audit log ─────────────────────────────────────────────────────────────────

def log_action(action, details="") -> None:
    conn = get_conn()
    with conn:
        conn.execute(
            "INSERT INTO audit_log (action, details) VALUES (?,?)", (action, details)
        )


def get_audit_log(limit=200) -> list[dict]:
    conn = get_conn()
    return [dict(r) for r in conn.execute(
        "SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT ?", (limit,)
    ).fetchall()]


# ─── Unsubscribes ───────────────────────────────────────────────────────────────

def add_unsubscribe(email, token="") -> None:
    conn = get_conn()
    with conn:
        conn.execute("""
            INSERT INTO unsubscribes (email, token) VALUES (?,?)
            ON CONFLICT(email) DO NOTHING
        """, (email, token))
        conn.execute("UPDATE contacts SET do_not_contact=1 WHERE email=?", (email,))


def is_unsubscribed(email) -> bool:
    if not email:
        return False
    conn = get_conn()
    row = conn.execute("SELECT id FROM unsubscribes WHERE email=?", (email,)).fetchone()
    return row is not None


# ─── Backup ─────────────────────────────────────────────────────────────────────

def backup_db() -> str:
    import sqlite3 as _sqlite3
    backup_dir = DB_PATH.parent / "backups"
    backup_dir.mkdir(exist_ok=True)
    dest = backup_dir / f"abm_backup_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.db"
    src = _sqlite3.connect(str(DB_PATH))
    dst = _sqlite3.connect(str(dest))
    src.backup(dst)
    dst.close()
    src.close()
    return dest.name
```

---

## File: `abm_engine/dashboard/app.py` (full rewrite — was PostgreSQL, now SQLite)

```python
"""
app.py — ABM Dashboard (SQLite, Claude-based system)
Human review UI for draft_messages / accounts / contacts, backed by
abm_engine/database/db.py — the same store the orchestrator/scoring engine use.
"""
from __future__ import annotations
import os, sys, hmac, hashlib, time as _time
from pathlib import Path
from functools import wraps
from flask import Flask, render_template, request, jsonify, redirect, url_for, session, g
from flask_cors import CORS
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent.parent
ENV_PATH = ROOT / "abm_engine" / ".env"
load_dotenv(ENV_PATH)

sys.path.insert(0, str(ROOT))
from abm_engine.database import db

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.environ.get("FLASK_SECRET", "decimal-abm-CHANGE-ME-" + hashlib.sha256(str(ROOT).encode()).hexdigest()[:16])
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Strict"
CORS(app, origins=["http://localhost:5000", "http://127.0.0.1:5000"])

DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "decimal2026")
UNSUBSCRIBE_BASE = os.environ.get("UNSUBSCRIBE_URL", "http://localhost:5000/unsubscribe")
LOGIN_ATTEMPTS = {}; MAX_ATTEMPTS = 5; LOCKOUT_SECONDS = 300

db.init_db()


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("authenticated"): return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


@app.route("/login", methods=["GET", "POST"])
def login():
    ip = request.remote_addr
    if request.method == "POST":
        now = _time.time()
        attempts = LOGIN_ATTEMPTS.get(ip, [])
        attempts = [t for t in attempts if now - t < LOCKOUT_SECONDS]
        if len(attempts) >= MAX_ATTEMPTS:
            return render_template("login.html", error=f"Too many attempts. Try again in {int(LOCKOUT_SECONDS/60)} minutes.")
        pwd = request.form.get("password", "")
        if hmac.compare_digest(pwd.encode(), DASHBOARD_PASSWORD.encode()):
            session["authenticated"] = True; LOGIN_ATTEMPTS.pop(ip, None)
            db.log_action("LOGIN", f"Successful from {ip}"); return redirect("/")
        else:
            attempts.append(now); LOGIN_ATTEMPTS[ip] = attempts
            db.log_action("LOGIN_FAIL", f"Failed from {ip} ({len(attempts)}/{MAX_ATTEMPTS})")
            return render_template("login.html", error="Incorrect password")
    return render_template("login.html", error=None)


@app.route("/logout")
def logout():
    session.pop("authenticated", None); return redirect("/login")


@app.before_request
def inject_pending_count():
    if request.path.startswith(("/api/", "/health", "/static/", "/unsubscribe")):
        g.pending_count = 0; return
    if session.get("authenticated"):
        try:
            g.pending_count = db.get_draft_counts().get("pending", 0)
        except Exception:
            g.pending_count = 0
    else:
        g.pending_count = 0


@app.context_processor
def utility_processor():
    return {"pending_count": getattr(g, "pending_count", 0)}


def make_unsub_token(email):
    return hmac.new(app.secret_key.encode(), email.encode(), hashlib.sha256).hexdigest()[:16]


@app.route("/unsubscribe")
def unsubscribe():
    email = request.args.get("email", ""); token = request.args.get("token", "")
    if not email: return "Invalid link", 400
    if not hmac.compare_digest(token, make_unsub_token(email)): return "Invalid or expired unsubscribe link", 403
    db.add_unsubscribe(email, token)
    db.log_action("UNSUBSCRIBE", email)
    return render_template("unsubscribed.html", email=email)


@app.errorhandler(404)
def page_not_found(e): return render_template("error.html", code=404, message="Page not found"), 404


@app.errorhandler(500)
def server_error(e): return render_template("error.html", code=500, message="Something went wrong"), 500


@app.route("/health")
def health():
    try:
        db.get_conn().execute("SELECT 1")
        return jsonify({"status": "ok", "db": "sqlite"})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/")
@login_required
def overview():
    accounts = db.get_all_accounts()
    stats = {
        "total": len(accounts),
        "hot": sum(1 for a in accounts if a["tier"] == "HOT"),
        "warm": sum(1 for a in accounts if a["tier"] == "WARM"),
        "cold": sum(1 for a in accounts if a["tier"] == "COLD"),
        "banks": sum(1 for a in accounts if a["account_type"] == "BANK"),
        "digital": sum(1 for a in accounts if a["segment"] == "DIGITAL"),
        "fintech": sum(1 for a in accounts if a["account_type"] in ("FI", "VENDOR")),
    }
    dash = db.get_dashboard_stats()
    news = db.get_news_feed(limit=5)
    top_accounts = sorted(accounts, key=lambda a: a["composite_score"], reverse=True)[:10]
    return render_template(
        "overview.html", acct_stats=stats,
        contact_count=dash["contacts"].get("total") or 0,
        signal_count=dash["news"].get("unread") or 0,
        product_count=0,
        top_accounts=top_accounts, recent_signals=news,
    )


@app.route("/accounts")
@login_required
def accounts_list():
    tier_f = request.args.get("tier", ""); seg_f = request.args.get("segment", ""); search = request.args.get("q", "")
    accts = db.get_accounts_filtered(search=search, tier=tier_f, segment=seg_f)
    all_accounts = db.get_all_accounts()
    all_tiers = sorted({a["tier"] for a in all_accounts if a.get("tier")})
    all_segs = sorted({a["segment"] for a in all_accounts if a.get("segment")})
    return render_template("accounts.html", accounts=accts, search=search, tier_filter=tier_f, seg_filter=seg_f, all_tiers=all_tiers, all_segments=all_segs)


@app.route("/account/<int:aid>")
@login_required
def account_detail_page(aid):
    acct = db.get_account_by_id(aid)
    if not acct: return render_template("error.html", code=404, message="Account not found"), 404
    contacts_list = db.get_contacts_for_account(aid)
    signals_list = db.get_signals_for_account_name(acct["name"], limit=20)
    drafts_list = db.get_drafts_for_account(aid, limit=10)
    touch_history = db.get_touches_for_account(aid, limit=20)
    return render_template(
        "account_detail.html", account=acct, contacts=contacts_list,
        signals=signals_list, drafts=drafts_list, touches=touch_history,
    )


@app.route("/drafts")
@login_required
def drafts():
    sf = request.args.get("status", "pending")
    status_map = {"pending": "DRAFT", "approved": "APPROVED", "sent": "SENT", "rejected": "REJECTED"}
    conn = db.get_conn()
    if sf == "all":
        rows = conn.execute("""
            SELECT d.*, c.full_name as contact_name, c.institution as company, c.role as title,
                   c.linkedin_url, c.do_not_contact, c.email as contact_email
            FROM draft_messages d LEFT JOIN contacts c ON d.contact_id = c.id
            ORDER BY d.generated_at DESC
        """).fetchall()
    else:
        rows = conn.execute("""
            SELECT d.*, c.full_name as contact_name, c.institution as company, c.role as title,
                   c.linkedin_url, c.do_not_contact, c.email as contact_email
            FROM draft_messages d LEFT JOIN contacts c ON d.contact_id = c.id
            WHERE d.status = ? ORDER BY d.generated_at DESC
        """, (status_map.get(sf, sf.upper()),)).fetchall()
    return render_template("drafts.html", drafts=[dict(r) for r in rows], current_filter=sf)


@app.route("/contacts")
@login_required
def contacts():
    search = request.args.get("q", ""); tier_f = request.args.get("tier", ""); type_f = request.args.get("type", "")
    rows = db.get_all_contacts(search=search, relationship_type=type_f, tier=tier_f)
    all_contacts = db.get_all_contacts()
    all_tiers = sorted({c["tier"] for c in all_contacts if c.get("tier")})
    all_types = sorted({c["relationship_type"] for c in all_contacts if c.get("relationship_type")})
    return render_template("contacts.html", contacts=rows, search=search, tier_filter=tier_f, type_filter=type_f, all_tiers=all_tiers, all_types=all_types)


@app.route("/contact/<int:cid>")
@login_required
def contact_detail(cid):
    c = db.get_contact_by_id(cid)
    if not c: return render_template("error.html", code=404, message="Contact not found"), 404
    touches = db.get_touch_history(cid)
    conn = db.get_conn()
    pending = [dict(r) for r in conn.execute(
        "SELECT * FROM draft_messages WHERE contact_id=? AND status='DRAFT'", (cid,)
    ).fetchall()]
    is_unsub = db.is_unsubscribed(c.get("email", ""))
    return render_template("contact_detail.html", contact=c, touches=touches, pending=pending, is_unsubscribed=is_unsub)


@app.route("/intelligence")
@login_required
def intelligence():
    return render_template("intelligence.html", signals=db.get_news_feed(limit=100))


@app.route("/templates")
@login_required
def templates():
    return render_template("templates.html", templates=db.get_templates())


@app.route("/audit")
@login_required
def audit():
    return render_template("audit.html", logs=db.get_audit_log(200))


@app.route("/api/draft/<int:did>/approve", methods=["POST"])
@login_required
def api_approve(did):
    draft = db.get_draft_by_id(did)
    if not draft: return jsonify({"ok": False, "error": "Draft not found"}), 404
    contact = db.get_contact_by_id(draft["contact_id"])
    if contact and contact.get("do_not_contact"): return jsonify({"ok": False, "error": "Contact is marked do-not-contact"}), 400
    if contact and contact.get("email") and db.is_unsubscribed(contact["email"]):
        return jsonify({"ok": False, "error": "Contact has unsubscribed"}), 400
    db.approve_draft(did)
    db.log_action("APPROVE", f"Draft #{did}")
    return jsonify({"ok": True})


@app.route("/api/draft/<int:did>/reject", methods=["POST"])
@login_required
def api_reject(did):
    notes = request.json.get("notes", "") if request.is_json else ""
    db.reject_draft(did, notes)
    db.log_action("REJECT", f"Draft #{did}: {notes}")
    return jsonify({"ok": True})


@app.route("/api/draft/<int:did>/edit", methods=["POST"])
@login_required
def api_edit(did):
    data = request.json
    draft = db.get_draft_by_id(did)
    if not draft: return jsonify({"ok": False}), 404
    db.update_draft_body(
        did,
        subject=data.get("subject", draft.get("subject")),
        body_en=data.get("body", draft.get("body_en")),
        body_ar=draft.get("body_ar"),
    )
    db.log_action("EDIT", f"Draft #{did}")
    return jsonify({"ok": True})


@app.route("/api/draft/<int:did>/send", methods=["POST"])
@login_required
def api_send(did):
    """Manually trigger the send-approved pipeline (Mailchimp/SendGrid/Heyreach) for this one draft."""
    draft = db.get_draft_by_id(did)
    if not draft: return jsonify({"ok": False, "error": "Not found"}), 404
    if draft["status"] != "APPROVED": return jsonify({"ok": False, "error": "Must be approved first"}), 400
    try:
        from abm_engine.core.orchestrator import Orchestrator
        Orchestrator()._send_draft(draft)
        db.log_action("SEND", f"Draft #{did}")
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": f"Send failed: {str(e)[:150]}"}), 500


@app.route("/api/draft/<int:did>/redraft", methods=["POST"])
@login_required
def api_redraft(did):
    conn = db.get_conn()
    with conn:
        conn.execute("DELETE FROM draft_messages WHERE id=? AND status='REJECTED'", (did,))
    db.log_action("REDRAFT", f"Deleted draft #{did}")
    return jsonify({"ok": True, "message": "Draft deleted. A fresh one will be generated next cycle."})


@app.route("/api/draft/<int:did>/use-as-template", methods=["POST"])
@login_required
def api_use_as_template(did):
    draft = db.get_draft_by_id(did)
    if not draft: return jsonify({"ok": False}), 404
    name = (request.json or {}).get("name", f"Template from draft #{did}")
    channel = "email" if draft.get("touch_type") == "EMAIL" else "whatsapp"
    db.save_template(None, name, channel, draft.get("subject", ""), draft.get("body_en", ""))
    db.log_action("TEMPLATE_FROM_DRAFT", f"'{name}' from #{did}")
    return jsonify({"ok": True})


@app.route("/api/contact/<int:cid>/consent", methods=["POST"])
@login_required
def api_update_consent(cid):
    d = request.json
    db.update_contact_consent(cid, d.get("consent_status", "none"), d.get("consent_source", ""))
    db.log_action("CONSENT", f"Contact #{cid}: {d.get('consent_status')}")
    return jsonify({"ok": True})


@app.route("/api/signal/<int:sid>/read", methods=["POST"])
@login_required
def api_mark_read(sid):
    db.mark_news_read(sid)
    return jsonify({"ok": True})


@app.route("/api/backup", methods=["POST"])
@login_required
def api_backup():
    try:
        filename = db.backup_db()
        db.log_action("BACKUP", filename)
        return jsonify({"ok": True, "file": filename})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 500


@app.route("/api/template/save", methods=["POST"])
@login_required
def api_template_save():
    d = request.json; tid = d.get("id"); name = d.get("name", "Untitled")
    ch = d.get("channel", "email"); subj = d.get("subject", ""); body = d.get("body", "")
    db.save_template(tid, name, ch, subj, body)
    db.log_action("TEMPLATE_SAVE", name)
    return jsonify({"ok": True})


@app.route("/api/template/<int:tid>/delete", methods=["POST"])
@login_required
def api_template_delete(tid):
    db.delete_template(tid)
    db.log_action("TEMPLATE_DELETE", f"#{tid}")
    return jsonify({"ok": True})


@app.route("/api/template/<int:tid>")
@login_required
def api_template_get(tid):
    t = db.get_template_by_id(tid)
    return jsonify(t if t else {})


@app.route("/api/contacts/stats")
@login_required
def api_stats():
    return jsonify(db.get_dashboard_stats()["contacts"])


def run_dashboard(host="127.0.0.1", port=5000, debug=False):
    print(f"\n  ABM Dashboard (SQLite) | http://localhost:{port} | DB: {db.DB_PATH}\n")
    app.run(host=host, port=port, debug=debug, use_reloader=False)


if __name__ == "__main__":
    run_dashboard()
```

---

## File: `abm_engine/__main__.py` (env loading + Unicode fix)

```python
"""
abm_engine/__main__.py
───────────────────────
CLI entry point for the complete 7-layer ABM engine.

Commands:
  setup      Load contacts from Excel + run initial scoring
  run        Run one outreach cycle now
  signals    Run signal detection now (all sources)
  score      Re-score all contacts now
  report     Generate this week's KPI report
  start      Start the full automatic scheduler (keep terminal open)
  webhook    Start reply detection server
  status     Full pipeline status dashboard
  test       Test full pipeline on 1 contact (no sends)
"""
from __future__ import annotations
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

# Explicit path — plain load_dotenv() only searches cwd and its ancestors, so it
# never finds .env when invoked as `python -m abm_engine` from the parent directory
# (which is required for -m to resolve this package at all).
load_dotenv(Path(__file__).resolve().parent / ".env")

# The CLI prints emoji (✅ ❌ 🔍 etc.) — Windows consoles default to cp1252, which
# can't encode them and crashes the whole command. Force UTF-8 stdout/stderr.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from loguru import logger
logger.remove()
logger.add(sys.stderr,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
    level=os.environ.get("LOG_LEVEL", "INFO"))
logger.add("logs/engine.log", rotation="10 MB", retention="30 days", level="DEBUG")

from .database.db import init_db


def cmd_setup():
    init_db()
    from .core.loader import load_contacts_from_excel
    from .scoring.engine import ScoringEngine

    excel = os.environ.get("CONTACTS_EXCEL_PATH", "./data/abm_contacts.xlsx")
    if not __import__("pathlib").Path(excel).exists():
        print(f"\n❌  Excel not found: {excel}\n    Set CONTACTS_EXCEL_PATH in .env\n")
        sys.exit(1)

    n = load_contacts_from_excel(excel)
    print(f"\n✅  Loaded {n} contacts")

    print("   Running initial scoring...")
    engine = ScoringEngine()
    result = engine.run()
    print(f"   Scored: {result['contacts_scored']} contacts | HOT upgrades: {result['upgraded']}\n")


def cmd_run():
    init_db()
    from .core.orchestrator import Orchestrator
    print("\n▶  Running outreach cycle...")
    result = Orchestrator().run()
    print(f"\n✅  Done: {result}\n")


def cmd_signals():
    init_db()
    from .signals.monitor import SignalMonitor
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    print("\n🔍  Running signal detection...")
    result = SignalMonitor(api_key=api_key).run_full()
    print(f"\n✅  Signals detected: {result}\n")


def cmd_score():
    init_db()
    from .scoring.engine import ScoringEngine
    print("\n📊  Running scoring engine...")
    result = ScoringEngine().run()
    print(f"\n✅  {result}\n")


def cmd_report():
    init_db()
    from .reporting.kpi import KPIReporter
    print("\n📈  Generating KPI report...")
    result = KPIReporter().run()
    print(f"\n✅  Report sent: {result}\n")


def cmd_start():
    from .scheduler.runner import start_scheduler
    start_scheduler()


def cmd_webhook():
    from .channels.webhook_server import start_webhook_server
    start_webhook_server()


def cmd_status():
    init_db()
    from .database.db import get_conn
    conn = get_conn()

    print("\n" + "═" * 65)
    print("  DECIMAL ABM ENGINE — FULL PIPELINE STATUS")
    print("═" * 65)

    # Contact pipeline
    tiers = conn.execute("""
        SELECT tier,
            COUNT(*) total,
            SUM(CASE WHEN current_touch=0 THEN 1 ELSE 0 END) not_started,
            SUM(CASE WHEN current_touch>0 AND current_touch<5 THEN 1 ELSE 0 END) in_progress,
            SUM(CASE WHEN current_touch>=5 THEN 1 ELSE 0 END) completed,
            SUM(CASE WHEN replied=1 THEN 1 ELSE 0 END) replied
        FROM contacts WHERE is_active=1
        GROUP BY tier
        ORDER BY CASE tier WHEN 'HOT' THEN 1 WHEN 'WARM' THEN 2 ELSE 3 END
    """).fetchall()

    print(f"\n{'TIER':<8} {'TOTAL':>6} {'NOT STARTED':>12} {'IN PROGRESS':>12} {'DONE':>6} {'REPLIED':>8}")
    print("-" * 55)
    for r in tiers:
        print(f"{r['tier']:<8} {r['total']:>6} {r['not_started']:>12} {r['in_progress']:>12} {r['completed']:>6} {r['replied']:>8}")

    # Signals
    sig_counts = conn.execute("""
        SELECT priority, COUNT(*) n FROM signals
        WHERE detected_at > datetime('now', '-7 days')
        GROUP BY priority ORDER BY priority
    """).fetchall()
    print(f"\nSIGNALS (last 7 days):")
    for r in sig_counts:
        print(f"  {r['priority']}: {r['n']}")

    # Touch status
    touch_counts = conn.execute("""
        SELECT status, COUNT(*) n FROM touch_records GROUP BY status
    """).fetchall()
    print(f"\nTOUCH RECORDS:")
    for r in touch_counts:
        print(f"  {r['status']:<12}: {r['n']}")

    # Recent KPIs
    kpi = conn.execute("""
        SELECT * FROM kpi_snapshots ORDER BY week_start DESC LIMIT 1
    """).fetchone()
    if kpi:
        print(f"\nLAST KPI WEEK ({kpi['week_start']}):")
        print(f"  Sent: {kpi['touches_sent']} | Replies: {kpi['replies_received']} | Eng rate: {kpi['engagement_rate_pct']}%")
        print(f"  Meetings: {kpi['meetings_booked']} | Pipeline: ${kpi['pipeline_value_usd']:,}")

    print("\n" + "═" * 65 + "\n")


def cmd_test():
    init_db()
    from .database.db import get_conn
    conn = get_conn()
    row  = conn.execute(
        "SELECT * FROM contacts WHERE is_active=1 ORDER BY priority_score DESC LIMIT 1"
    ).fetchone()

    if not row:
        print("\n❌  No contacts found. Run `setup` first.\n")
        sys.exit(1)

    from .core.orchestrator import Orchestrator
    contact = Orchestrator._row_to_contact(dict(row))

    print(f"\n🔬  Test run: {contact.full_name} @ {contact.institution}")
    print(f"    Tier: {contact.tier} | Score: {contact.priority_score}")
    print(f"    Persona: {contact.persona} | Segment: {contact.segment}")
    print(f"    KSA National: {contact.is_ksa_national} | Warm: {contact.has_warm_relationship}\n")

    from .agents.researcher import ResearchAgent
    from .agents.writer     import WriterAgent
    from .scoring.engine    import ScoringEngine

    api_key = os.environ["ANTHROPIC_API_KEY"]

    # Show score breakdown
    scorer    = ScoringEngine()
    breakdown = scorer.score_one(dict(row))
    print("  SCORE BREAKDOWN:")
    print(f"    Signal Strength:       {breakdown['signal_strength']:>3}/35")
    print(f"    Regulatory Pressure:   {breakdown['regulatory_pressure']:>3}/30")
    print(f"    Persona Reachability:  {breakdown['persona_reachability']:>3}/20")
    print(f"    Existing Relationship: {breakdown['existing_relationship']:>3}/15")
    print(f"    ─────────────────────────────")
    print(f"    COMPOSITE SCORE:       {breakdown['composite_score']:>3}/100  [{breakdown['tier']}]\n")

    print("  [1/2] Researching...")
    researcher = ResearchAgent(api_key=api_key)
    research   = researcher.research_contact(contact)
    print(f"  Hook: {research.recommended_hook}\n")

    print("  [2/2] Generating email T1...")
    writer = WriterAgent(api_key=api_key)
    email  = writer.generate_email(contact, research, touch=1)
    print(f"\n  Subject: {email.subject}")
    print(f"  ({'EN+AR' if contact.needs_arabic else 'EN only'})")
    print(f"  {'─'*50}")
    print(f"  {email.body}\n")

    print("  LinkedIn T1 connection note:")
    dm = writer.generate_linkedin_dm(contact, research, touch=1)
    print(f"  ({len(dm.body)} chars)\n  {dm.body}\n")
    print("✅  Test complete.\n")


COMMANDS = {
    "setup":   cmd_setup,
    "run":     cmd_run,
    "signals": cmd_signals,
    "score":   cmd_score,
    "report":  cmd_report,
    "start":   cmd_start,
    "webhook": cmd_webhook,
    "status":  cmd_status,
    "test":    cmd_test,
}

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    if cmd not in COMMANDS:
        print(__doc__)
        sys.exit(0)
    COMMANDS[cmd]()


def cmd_dashboard():
    """Start the web dashboard on http://localhost:5000"""
    from .dashboard.app import app
    port = int(os.environ.get("DASHBOARD_PORT", 5000))
    print(f"\n  Decimal ABM Dashboard → http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=False)

COMMANDS["dashboard"] = cmd_dashboard
```

---

## File: `abm_engine/scheduler/runner.py` (env loading fix)

```python
"""
abm_engine/scheduler/runner.py
────────────────────────────────
All scheduled jobs.

Jobs:
  Every 1h    → Quick intelligence check (SAMA + leadership)
  Every 6h    → Full intelligence check (all sources)
  Daily 9AM   → Generate drafts for contacts due outreach
  Every 30min → Send approved drafts (after human review)
  Every 15min → Reply check + human alert (WhatsApp + Email)
  Monday 8AM  → Scoring re-run + weekly KPI report
"""
from __future__ import annotations
import os, signal, sys
from datetime import datetime
from pathlib import Path
from loguru import logger
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron       import CronTrigger
from dotenv import load_dotenv

# Explicit path — see abm_engine/__main__.py for why plain load_dotenv() doesn't work here.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from ..database.db        import init_db, get_unnotified_events, mark_events_notified
from ..core.orchestrator  import Orchestrator, _make_notifier
from ..signals.monitor    import SignalMonitor
from ..scoring.engine     import ScoringEngine
from ..reporting.kpi      import KPIReporter


def job_signal_quick():
    logger.info("⏰ Quick intelligence check")
    try:
        result = SignalMonitor(os.environ.get("ANTHROPIC_API_KEY","")).run_quick()
        if result.get("total",0) > 0:
            from ..database.db import get_recent_signals
            if any(s["priority"]=="P1" for s in get_recent_signals(hours=1)):
                job_scoring()
    except Exception as e:
        logger.error("Quick intelligence check failed: {}", e)


def job_signal_full():
    logger.info("⏰ Full intelligence check")
    try:
        SignalMonitor(os.environ.get("ANTHROPIC_API_KEY","")).run_full()
    except Exception as e:
        logger.error("Full intelligence check failed: {}", e)


def job_generate_drafts():
    logger.info("⏰ Draft generation job")
    try:
        Orchestrator().generate_drafts()
    except Exception as e:
        logger.exception("Draft generation crashed: {}", e)
        _make_notifier().engine_error(str(e))


def job_send_approved():
    """Runs every 30 min — sends drafts approved in the dashboard."""
    try:
        result = Orchestrator().send_approved_drafts()
        if result.get("sent",0) > 0:
            logger.info("Sent {} approved drafts", result["sent"])
    except Exception as e:
        logger.error("Send approved drafts failed: {}", e)


def job_reply_check():
    events = get_unnotified_events()
    if not events:
        return
    notifier   = _make_notifier()
    notify_ids = []
    for ev in events:
        if ev["event_type"] in ("email_reply","linkedin_reply"):
            notifier.reply_received(
                contact_name  = ev.get("full_name","Unknown"),
                institution   = ev.get("institution",""),
                role          = ev.get("role",""),
                touch_number  = ev.get("touch_id",0),
                channel       = "email" if "email" in ev["event_type"] else "linkedin",
                reply_snippet = (ev.get("raw_content") or "")[:300],
            )
        notify_ids.append(ev["id"])
    mark_events_notified(notify_ids)


def job_scoring():
    try:
        ScoringEngine().run()
    except Exception as e:
        logger.error("Scoring failed: {}", e)


def job_weekly_report():
    try:
        KPIReporter().run()
    except Exception as e:
        logger.error("Weekly report failed: {}", e)


def start_scheduler():
    init_db()
    start_hour   = int(os.environ.get("SCHEDULER_START_HOUR", 9))
    start_minute = int(os.environ.get("SCHEDULER_START_MINUTE", 0))
    tz           = os.environ.get("SCHEDULER_TIMEZONE", "Asia/Riyadh")

    scheduler = BlockingScheduler(timezone=tz)

    scheduler.add_job(job_signal_quick, CronTrigger(minute=0),
        id="signal_quick", misfire_grace_time=3600)
    scheduler.add_job(job_signal_full, CronTrigger(hour="0,6,12,18"),
        id="signal_full",  misfire_grace_time=3600)
    scheduler.add_job(job_generate_drafts, CronTrigger(hour=start_hour, minute=start_minute),
        id="generate_drafts", misfire_grace_time=3600)
    scheduler.add_job(job_send_approved, CronTrigger(minute="*/30"),
        id="send_approved")
    scheduler.add_job(job_reply_check, CronTrigger(minute="*/15"),
        id="reply_check")
    scheduler.add_job(job_scoring, CronTrigger(day_of_week="mon", hour=8),
        id="scoring", misfire_grace_time=3600)
    scheduler.add_job(job_weekly_report, CronTrigger(day_of_week="mon", hour=8, minute=5),
        id="weekly_report", misfire_grace_time=3600)

    def shutdown(signum, frame):
        scheduler.shutdown(); sys.exit(0)
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    logger.info("ABM Engine scheduler started | Drafts generated: {:02d}:{:02d} {} | Sends: every 30min | Intelligence: every hour",
        start_hour, start_minute, tz)
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")
```

---

## File: `abm_engine/agents/researcher.py` (one-line async fix)

Only change: `async def research_contact` → `def research_contact` (removed `async` — there
was no actual `await` anywhere inside; the Anthropic client call is synchronous, so the
function was a coroutine with no async work, and every caller invoked it without `await`,
producing an unawaited coroutine object instead of a result).

```python
"""
abm_engine/agents/researcher.py
────────────────────────────────
Uses Claude with web_search tool to find the freshest signal
for each contact before writing their outreach message.
This is what replaces Clay's signal detection.
"""
from __future__ import annotations
import json
from datetime import datetime
from loguru import logger
import anthropic

from ..core.models import Contact, ResearchResult


SYSTEM_PROMPT = """\
You are a senior B2B sales intelligence analyst at Decimal Technologies.

Decimal Technologies is a B2B fintech infrastructure company headquartered in India,
expanding into the GCC (Saudi Arabia, UAE, Qatar, Kuwait, Oman).

Decimal's products:
- API-first digital account opening (retail + SME + corporate)
- AI-powered credit decisioning and digital lending
- Open banking infrastructure and API marketplace (1,200+ APIs)
- No-code banking product configurator (go-live in weeks, not months)
- SAMA/CBUAE regulatory compliance modules

Your job: research a specific banking executive and their institution.
Find the FRESHEST, most specific business signal that Decimal can use to
open a conversation. Think: new product launches, regulatory responses,
hiring signals, partnership announcements, technology investments.

Always return a JSON object — no prose, no markdown, just valid JSON.
"""


RESEARCH_PROMPT = """\
Research this contact and their institution. Find the most relevant, recent signal
that Decimal Technologies can use as an outreach hook.

Contact:
- Name: {full_name}
- Role: {role}
- Institution: {institution}
- Country: {country}
- Known signal (may be outdated): {key_signal}
- Decimal product fit: {product_fit}

Search for:
1. Recent news about {institution} in the last 6 months
2. Any regulatory announcements (SAMA, CBUAE) affecting {institution}
3. Any technology or digital banking investments by {institution}
4. Any LinkedIn activity or public statements by {full_name}

Return ONLY this JSON (no other text):
{{
  "fresh_signals": [
    "Signal 1 — specific and recent",
    "Signal 2 — specific and recent",
    "Signal 3 — specific and recent"
  ],
  "recommended_hook": "The single best signal to use as the email/DM opener",
  "context_summary": "2–3 sentence background on the account and why Decimal fits right now"
}}
"""


class ResearchAgent:
    """
    Calls Claude with web_search to get fresh account intelligence.
    Results are cached in DB — won't re-research the same contact
    within 7 days unless forced.
    """

    def __init__(self, api_key: str):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model  = "claude-sonnet-4-6"

    def research_contact(self, contact: Contact) -> ResearchResult:
        logger.info(
            "Researching {} @ {} (touch {}/5)",
            contact.full_name, contact.institution, contact.current_touch + 1
        )

        prompt = RESEARCH_PROMPT.format(
            full_name    = contact.full_name,
            role         = contact.role,
            institution  = contact.institution,
            country      = contact.country,
            key_signal   = contact.key_signal,
            product_fit  = contact.product_fit,
        )

        try:
            response = self.client.messages.create(
                model     = self.model,
                max_tokens= 1024,
                system    = SYSTEM_PROMPT,
                tools     = [{"type": "web_search_20250305", "name": "web_search"}],
                messages  = [{"role": "user", "content": prompt}]
            )

            # Extract the text block from the response
            result_text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    result_text += block.text

            # Parse JSON
            data = json.loads(result_text)

            return ResearchResult(
                contact_id       = contact.id,
                contact_name     = contact.full_name,
                institution      = contact.institution,
                fresh_signals    = data.get("fresh_signals", [contact.key_signal]),
                recommended_hook = data.get("recommended_hook", contact.key_signal),
                context_summary  = data.get("context_summary", ""),
                researched_at    = datetime.utcnow(),
            )

        except json.JSONDecodeError as e:
            logger.warning(
                "JSON parse failed for {} — using fallback signal. Error: {}",
                contact.full_name, e
            )
            return ResearchResult(
                contact_id       = contact.id,
                contact_name     = contact.full_name,
                institution      = contact.institution,
                fresh_signals    = [contact.key_signal],
                recommended_hook = contact.key_signal,
                context_summary  = contact.outreach_angle,
                researched_at    = datetime.utcnow(),
            )

        except Exception as e:
            logger.error("Research failed for {}: {}", contact.full_name, e)
            # Graceful fallback — don't crash the engine
            return ResearchResult(
                contact_id       = contact.id,
                contact_name     = contact.full_name,
                institution      = contact.institution,
                fresh_signals    = [contact.key_signal],
                recommended_hook = contact.key_signal,
                context_summary  = contact.outreach_angle,
                researched_at    = datetime.utcnow(),
            )
```

---

## Dashboard templates (field-name fixes, Postgres/v2 → SQLite/Claude-system naming)

All under `abm_engine/dashboard/templates/`. Pattern applied throughout: `accounts.tier`
`'Tier 1'/'Tier 2'/'Tier 3'` → `'HOT'/'WARM'/'COLD'` directly; `a.score` → `a.composite_score`;
`draft.channel` (`'email'/'whatsapp'`) → `draft.touch_type` (`'EMAIL'/'LINKEDIN'`);
`draft.body` → `draft.body_en`; draft status `'pending'/'approved'/'rejected'/'sent'` →
`'DRAFT'/'APPROVED'/'REJECTED'/'SENT'` (lowercased via `|lower` filter for CSS class
matching); signals `source/title/url/created_at` → `source_name/headline/source_url/detected_at`
(switched the Intelligence page from the legacy `signals` table shape to the clean
`news_items` table, which has no schema collision); `relationship_type`/`persona` values
lowercased via `|lower` for the `.rtype` CSS classes, which are lowercase while the enum
values are uppercase. Product Fit / Relationships / Opportunities sections were dropped from
`account_detail.html` (no Claude-system equivalent exists yet — noted as future work, not
faked).

### `abm_engine/dashboard/templates/base.html`

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{% block title %}ABM{% endblock %} — Decimal Technologies</title>
<style>
:root{--bg:#0f1117;--surface:#1a1d27;--surface2:#232735;--border:#2d3245;--text:#e4e6f0;--text-dim:#8b8fa3;--accent:#4f8cff;--accent-dim:#2a5bbf;--green:#34d399;--green-bg:rgba(52,211,153,.12);--red:#f87171;--red-bg:rgba(248,113,113,.12);--yellow:#fbbf24;--yellow-bg:rgba(251,191,36,.12);--orange:#fb923c}
*{margin:0;padding:0;box-sizing:border-box}body{font-family:'Segoe UI',-apple-system,sans-serif;background:var(--bg);color:var(--text)}a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
.topnav{background:var(--surface);border-bottom:1px solid var(--border);padding:0 24px;display:flex;align-items:center;gap:24px;height:56px;position:sticky;top:0;z-index:100;overflow-x:auto}
.topnav .logo{font-weight:700;font-size:15px;color:var(--accent);letter-spacing:.5px;white-space:nowrap}.topnav .logo span{color:var(--text-dim);font-weight:400}
.topnav a.nl{color:var(--text-dim);font-size:13px;font-weight:500;padding:16px 0;border-bottom:2px solid transparent;transition:.15s;white-space:nowrap}
.topnav a.nl:hover,.topnav a.nl.active{color:var(--text);border-bottom-color:var(--accent);text-decoration:none}
.topnav .badge{background:var(--red);color:#fff;font-size:11px;font-weight:700;padding:2px 6px;border-radius:10px;margin-left:4px}
.container{max-width:1200px;margin:0 auto;padding:28px 24px}.page-header{margin-bottom:24px}.page-header h1{font-size:22px;font-weight:700}.page-header p{color:var(--text-dim);font-size:13px;margin-top:4px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:20px;margin-bottom:16px}.card h3{font-size:13px;font-weight:600;color:var(--text-dim);text-transform:uppercase;letter-spacing:.5px;margin-bottom:12px}
.stats-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin-bottom:24px}
.stat-card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:16px 20px;text-align:center}.stat-card .num{font-size:32px;font-weight:700}.stat-card .label{font-size:12px;color:var(--text-dim);margin-top:4px;text-transform:uppercase;letter-spacing:.5px}
.stat-card.hot .num{color:var(--red)}.stat-card.warm .num{color:var(--yellow)}.stat-card.cold .num{color:var(--accent)}.stat-card.total .num{color:var(--green)}
table{width:100%;border-collapse:collapse;font-size:13px}th{text-align:left;padding:10px 12px;color:var(--text-dim);font-size:11px;text-transform:uppercase;letter-spacing:.5px;border-bottom:1px solid var(--border);font-weight:600}td{padding:10px 12px;border-bottom:1px solid var(--border);vertical-align:middle}tr:hover td{background:rgba(79,140,255,.04)}
.tier{font-size:11px;font-weight:700;padding:3px 8px;border-radius:4px;display:inline-block}.tier.HOT{background:var(--red-bg);color:var(--red)}.tier.WARM{background:var(--yellow-bg);color:var(--yellow)}.tier.COLD{background:rgba(79,140,255,.12);color:var(--accent)}
.rtype{font-size:11px;padding:3px 8px;border-radius:4px;display:inline-block;background:var(--surface2);color:var(--text-dim)}.rtype.target{background:rgba(79,140,255,.12);color:var(--accent)}.rtype.vendor{background:var(--yellow-bg);color:var(--yellow)}.rtype.subsidiary{background:var(--green-bg);color:var(--green)}.rtype.connector{background:rgba(251,146,60,.12);color:var(--orange)}.rtype.champion{background:var(--red-bg);color:var(--red)}
.status{font-size:11px;font-weight:600;padding:3px 8px;border-radius:4px;display:inline-block}.status.pending,.status.draft{background:var(--yellow-bg);color:var(--yellow)}.status.approved{background:var(--green-bg);color:var(--green)}.status.rejected{background:var(--red-bg);color:var(--red)}.status.sent{background:rgba(79,140,255,.12);color:var(--accent)}.status.send_failed,.status.bounced{background:var(--red-bg);color:var(--red)}.status.cancelled,.status.skipped{background:var(--surface2);color:var(--text-dim)}.status.opened{background:rgba(79,140,255,.12);color:var(--accent)}.status.replied{background:var(--green-bg);color:var(--green)}
.btn{padding:7px 16px;border-radius:6px;font-size:12px;font-weight:600;border:none;cursor:pointer;transition:.15s;display:inline-flex;align-items:center;gap:4px}.btn-approve{background:var(--green);color:#000}.btn-approve:hover{background:#2cc48a}.btn-reject{background:var(--red-bg);color:var(--red);border:1px solid rgba(248,113,113,.3)}.btn-reject:hover{background:rgba(248,113,113,.2)}.btn-send{background:var(--accent);color:#fff}.btn-send:hover{background:var(--accent-dim)}.btn-sm{padding:4px 10px;font-size:11px}.btn-group{display:flex;gap:6px;flex-wrap:wrap}
.filters{display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap;align-items:center}.filters input,.filters select{background:var(--surface2);border:1px solid var(--border);color:var(--text);padding:7px 12px;border-radius:6px;font-size:13px;outline:none}.filters input:focus,.filters select:focus{border-color:var(--accent)}.filters input{min-width:200px}
.draft-body{background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:14px;font-size:13px;line-height:1.6;white-space:pre-wrap;word-break:break-word;margin:10px 0}.draft-subject{font-weight:600;color:var(--text);margin-bottom:4px}
.detail-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}.detail-grid .field-label{font-size:11px;color:var(--text-dim);text-transform:uppercase;letter-spacing:.5px;margin-bottom:2px}.detail-grid .field-value{font-size:14px}
.signal-item{padding:14px 0;border-bottom:1px solid var(--border)}.signal-item:last-child{border-bottom:none}.signal-source{font-size:11px;color:var(--accent);text-transform:uppercase;font-weight:600;letter-spacing:.5px}.signal-title{font-size:14px;font-weight:600;margin:4px 0}.signal-summary{font-size:13px;color:var(--text-dim);line-height:1.5}.signal-time{font-size:11px;color:var(--text-dim);margin-top:4px}
.empty{text-align:center;padding:48px 20px;color:var(--text-dim)}.empty h3{font-size:16px;color:var(--text);margin-bottom:8px}.empty p{font-size:13px}
.score-bar{width:60px;height:6px;background:var(--surface2);border-radius:3px;overflow:hidden;display:inline-block;vertical-align:middle;margin-right:6px}.score-fill{height:100%;border-radius:3px}
.warn-badge{font-size:10px;padding:2px 6px;border-radius:4px;background:var(--red-bg);color:var(--red);font-weight:600}
@media(max-width:768px){.stats-row{grid-template-columns:repeat(2,1fr)}.detail-grid{grid-template-columns:1fr}.topnav{gap:12px}}
</style>
</head>
<body>
<nav class="topnav">
<div class="logo">DECIMAL <span>ABM</span></div>
<a href="/" class="nl {% if request.path == '/' %}active{% endif %}">Overview</a>
<a href="/accounts" class="nl {% if '/accounts' in request.path or '/account/' in request.path %}active{% endif %}">Accounts</a>
<a href="/drafts" class="nl {% if '/drafts' in request.path %}active{% endif %}">Drafts {% if pending_count %}<span class="badge">{{ pending_count }}</span>{% endif %}</a>
<a href="/contacts" class="nl {% if '/contacts' in request.path and '/account' not in request.path %}active{% endif %}">Contacts</a>
<a href="/templates" class="nl {% if '/templates' in request.path %}active{% endif %}">Templates</a>
<a href="/intelligence" class="nl {% if '/intelligence' in request.path %}active{% endif %}">Intelligence</a>
<a href="/audit" class="nl {% if '/audit' in request.path %}active{% endif %}">Audit</a>
<a href="/logout" class="nl" style="margin-left:auto;color:var(--red);">Logout</a>
</nav>
<div class="container">{% block content %}{% endblock %}</div>
{% block scripts %}{% endblock %}
</body>
</html>
```

### `abm_engine/dashboard/templates/overview.html`

```html
{% extends "base.html" %}
{% block title %}Overview{% endblock %}
{% block content %}
<div class="page-header"><h1>ABM Intelligence Dashboard</h1><p>Decimal Technologies — KSA Market Intelligence</p></div>

<div class="stats-row">
<div class="stat-card total"><div class="num">{{ acct_stats.total or 0 }}</div><div class="label">Accounts</div></div>
<div class="stat-card hot"><div class="num">{{ acct_stats.hot or 0 }}</div><div class="label">Hot</div></div>
<div class="stat-card warm"><div class="num">{{ acct_stats.warm or 0 }}</div><div class="label">Warm</div></div>
<div class="stat-card cold"><div class="num">{{ acct_stats.cold or 0 }}</div><div class="label">Cold</div></div>
<div class="stat-card" style="border-color:var(--accent)"><div class="num" style="color:var(--accent)">{{ signal_count }}</div><div class="label">Signals</div></div>
</div>

<div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
<div class="card"><h3>Account Universe</h3>
<table>
<tr><td>Commercial Banks</td><td style="text-align:right;font-weight:600;">{{ acct_stats.banks or 0 }}</td></tr>
<tr><td>Digital Banks</td><td style="text-align:right;font-weight:600;">{{ acct_stats.digital or 0 }}</td></tr>
<tr><td>Fintechs</td><td style="text-align:right;font-weight:600;">{{ acct_stats.fintech or 0 }}</td></tr>
</table>
<div style="margin-top:12px;"><a href="/accounts" class="btn btn-send btn-sm">View All Accounts →</a></div>
</div>

<div class="card"><h3>Intelligence Status</h3>
<table>
<tr><td>Total Signals</td><td style="text-align:right;font-weight:600;">{{ signal_count }}</td></tr>
<tr><td>Products Mapped</td><td style="text-align:right;font-weight:600;">{{ product_count }}</td></tr>
<tr><td>Contacts Loaded</td><td style="text-align:right;font-weight:600;">{{ contact_count }}</td></tr>
<tr><td>Pending Drafts</td><td style="text-align:right;font-weight:600;">{{ pending_count }}</td></tr>
</table>
</div>
</div>

<div class="card" style="margin-top:16px;"><h3>Recent Signals</h3>
{% if recent_signals %}{% for s in recent_signals %}
<div class="signal-item">
<div style="display:flex;justify-content:space-between;align-items:flex-start;">
<div>
<span class="signal-source">{{ s.source_name or s.category or 'signal' }}</span>
{% if s.institution %}<span style="font-size:11px;padding:2px 6px;border-radius:4px;background:rgba(79,140,255,.12);color:var(--accent);margin-left:6px;font-weight:600;">{{ s.institution }}</span>{% endif %}
{% if s.relevance_score and s.relevance_score >= 8 %}<span style="font-size:11px;padding:2px 6px;border-radius:4px;background:var(--red-bg);color:var(--red);margin-left:4px;">HIGH</span>{% endif %}
</div>
<span class="signal-time">{{ s.detected_at }}</span>
</div>
<div class="signal-title">{{ s.headline }}</div>
<div class="signal-summary">{{ s.summary or '' }}</div>
</div>{% endfor %}
<div style="margin-top:12px;"><a href="/intelligence" class="btn btn-sm" style="background:var(--surface2);color:var(--text);">View All Signals →</a></div>
{% else %}<div class="empty"><p>No signals yet. Engine scans every 6 hours.</p></div>{% endif %}
</div>

<div class="card" style="margin-top:16px;"><h3>Top Accounts</h3>
{% if top_accounts %}<table>
<tr><th>Account</th><th>Segment</th><th>Tier</th><th>Digital Maturity</th><th>Core Banking</th><th>Score</th></tr>
{% for a in top_accounts %}<tr>
<td><a href="/account/{{ a.id }}">{{ a.name }}</a></td>
<td style="font-size:12px;">{{ a.segment or '—' }}</td>
<td><span class="tier {{ a.tier or 'COLD' }}">{{ a.tier or '—' }}</span></td>
<td style="text-align:center;">{% if a.digital_maturity %}<div class="score-bar"><div class="score-fill" style="width:{{ a.digital_maturity * 10 }}%;background:{% if a.digital_maturity >= 8 %}var(--green){% elif a.digital_maturity >= 5 %}var(--yellow){% else %}var(--red){% endif %};"></div></div>{{ a.digital_maturity }}/10{% endif %}</td>
<td style="font-size:12px;color:var(--text-dim);">{{ a.core_banking or '—' }}</td>
<td>{{ a.composite_score or 0 }}</td>
</tr>{% endfor %}</table>
{% else %}<div class="empty"><p>No accounts loaded</p></div>{% endif %}
</div>
{% endblock %}
```

### `abm_engine/dashboard/templates/accounts.html`

```html
{% extends "base.html" %}{% block title %}Accounts{% endblock %}
{% block content %}
<div class="page-header"><h1>Account Universe</h1><p>KSA Banks, Digital Banks, and Fintechs — your target market</p></div>

<div class="filters"><form method="get" action="/accounts" style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;">
<input type="text" name="q" value="{{ search }}" placeholder="Search accounts...">
<select name="tier" onchange="this.form.submit()"><option value="">All Tiers</option>{% for t in all_tiers %}<option value="{{ t }}" {% if tier_filter==t %}selected{% endif %}>{{ t }}</option>{% endfor %}</select>
<select name="segment" onchange="this.form.submit()"><option value="">All Segments</option>{% for s in all_segments %}<option value="{{ s }}" {% if seg_filter==s %}selected{% endif %}>{{ s }}</option>{% endfor %}</select>
<button type="submit" class="btn btn-send btn-sm">Search</button>
{% if search or tier_filter or seg_filter %}<a href="/accounts" class="btn btn-reject btn-sm">Clear</a>{% endif %}
</form></div>

<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:14px;">
{% for a in accounts %}
<a href="/account/{{ a.id }}" style="text-decoration:none;color:inherit;">
<div class="card" style="cursor:pointer;transition:border-color .15s;min-height:180px;" onmouseover="this.style.borderColor='var(--accent)'" onmouseout="this.style.borderColor='var(--border)'">
<div style="display:flex;justify-content:space-between;align-items:flex-start;">
<div>
<div style="font-size:16px;font-weight:600;color:var(--text);">{{ a.name }}</div>
<div style="font-size:12px;color:var(--text-dim);margin-top:2px;">{{ a.segment or '' }}{% if a.sub_segment %} · {{ a.sub_segment }}{% endif %}</div>
</div>
<span class="tier {{ a.tier or 'COLD' }}">{{ a.tier or '—' }}</span>
</div>

<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:16px;text-align:center;">
<div><div style="font-size:18px;font-weight:600;color:var(--accent);">{{ a.contact_count or 0 }}</div><div style="font-size:10px;color:var(--text-dim);">CONTACTS</div></div>
<div><div style="font-size:18px;font-weight:600;color:var(--yellow);">{{ a.signal_count or 0 }}</div><div style="font-size:10px;color:var(--text-dim);">SIGNALS</div></div>
<div><div style="font-size:18px;font-weight:600;color:var(--green);">{{ a.composite_score or 0 }}</div><div style="font-size:10px;color:var(--text-dim);">SCORE</div></div>
<div><div style="font-size:18px;font-weight:600;color:var(--text-dim);">{{ a.draft_count or 0 }}</div><div style="font-size:10px;color:var(--text-dim);">DRAFTS</div></div>
</div>

<div style="display:flex;gap:6px;margin-top:14px;flex-wrap:wrap;">
{% if a.core_banking %}<span style="font-size:10px;padding:2px 6px;border-radius:4px;background:var(--surface2);color:var(--text-dim);">{{ a.core_banking }}</span>{% endif %}
{% if a.open_banking and a.open_banking != 'Unknown' %}<span style="font-size:10px;padding:2px 6px;border-radius:4px;background:{% if a.open_banking == 'Active' %}var(--green-bg){% else %}var(--yellow-bg){% endif %};color:{% if a.open_banking == 'Active' %}var(--green){% else %}var(--yellow){% endif %};">OB: {{ a.open_banking }}</span>{% endif %}
{% if a.digital_maturity %}<span style="font-size:10px;padding:2px 6px;border-radius:4px;background:var(--surface2);color:var(--text-dim);">DM: {{ a.digital_maturity }}/10</span>{% endif %}
{% if a.employees %}<span style="font-size:10px;padding:2px 6px;border-radius:4px;background:var(--surface2);color:var(--text-dim);">{{ a.employees }} emp</span>{% endif %}
</div>
</div>
</a>
{% endfor %}
</div>

{% if not accounts %}<div class="card"><div class="empty"><h3>No accounts match</h3></div></div>{% endif %}
{% endblock %}
```

### `abm_engine/dashboard/templates/account_detail.html`

```html
{% extends "base.html" %}{% block title %}{{ account.name }}{% endblock %}
{% block content %}
<div class="page-header" style="display:flex;justify-content:space-between;align-items:flex-start;">
<div>
<h1>{{ account.name }}</h1>
<p>{{ account.segment or '' }}{% if account.sub_segment %} · {{ account.sub_segment }}{% endif %} · {{ account.country or 'KSA' }}</p>
</div>
<div style="display:flex;gap:8px;flex-wrap:wrap;">
<span class="tier {{ account.tier or 'COLD' }}">{{ account.tier or '—' }}</span>
<span style="font-size:11px;padding:3px 8px;border-radius:4px;background:var(--surface2);color:var(--text-dim);">Score: {{ account.composite_score or 0 }}</span>
</div>
</div>

<!-- Quick stats -->
<div class="stats-row">
<div class="stat-card"><div class="num" style="color:var(--accent);">{{ contacts|length }}</div><div class="label">Contacts</div></div>
<div class="stat-card"><div class="num" style="color:var(--yellow);">{{ signals|length }}</div><div class="label">Signals</div></div>
<div class="stat-card"><div class="num" style="color:var(--green);">{{ account.digital_maturity or '—' }}</div><div class="label">Digital Maturity</div></div>
<div class="stat-card"><div class="num" style="color:var(--text-dim);">{{ drafts|length }}</div><div class="label">Drafts</div></div>
</div>

<!-- Account info -->
<div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
<div class="card"><h3>Account Profile</h3>
<div class="detail-grid">
<div><div class="field-label">Core Banking</div><div class="field-value">{{ account.core_banking or 'Unknown' }}</div></div>
<div><div class="field-label">Open Banking</div><div class="field-value">{{ account.open_banking or 'Unknown' }}</div></div>
<div><div class="field-label">Employees</div><div class="field-value">{{ account.employees or '—' }}</div></div>
<div><div class="field-label">Website</div><div class="field-value">{% if account.website %}<a href="{{ account.website }}" target="_blank">{{ account.website }}</a>{% else %}—{% endif %}</div></div>
<div><div class="field-label">Owner</div><div class="field-value">{{ account.owner or '—' }}</div></div>
<div><div class="field-label">Warm Contact</div><div class="field-value">{{ 'Yes' if account.has_warm_contact else 'No' }}</div></div>
</div>
</div>
</div>

<!-- Contacts at this account -->
<div class="card" style="margin-top:16px;"><h3>Contacts ({{ contacts|length }})</h3>
{% if contacts %}
<table><tr><th>Name</th><th>Role</th><th>Seniority</th><th>Persona</th><th>Email</th><th>Consent</th></tr>
{% for c in contacts %}<tr>
<td><a href="/contact/{{ c.id }}">{{ c.full_name }}</a>{% if c.do_not_contact %} <span class="warn-badge">DNC</span>{% endif %}</td>
<td style="font-size:12px;">{{ c.role or '—' }}</td>
<td style="font-size:12px;">{{ c.seniority or '—' }}</td>
<td>{% if c.persona %}<span class="rtype {{ c.persona|lower }}">{{ c.persona }}</span>{% else %}—{% endif %}</td>
<td style="font-size:12px;color:var(--text-dim);">{{ c.email or '—' }}</td>
<td><span style="font-size:11px;color:{% if c.consent_status=='opted_in' %}var(--green){% elif c.consent_status=='denied' %}var(--red){% else %}var(--text-dim){% endif %};">{{ c.consent_status or 'none' }}</span></td>
</tr>{% endfor %}</table>
{% else %}<div class="empty"><p>No contacts loaded for this account yet</p></div>{% endif %}
</div>

<!-- Signals for this account -->
<div class="card" style="margin-top:16px;"><h3>Signals ({{ signals|length }})</h3>
{% if signals %}{% for s in signals %}
<div class="signal-item">
<div style="display:flex;justify-content:space-between;">
<div>
<span class="signal-source">{{ s.source_name or '' }}</span>
{% if s.signal_type %}<span style="font-size:10px;padding:2px 6px;border-radius:4px;background:var(--surface2);color:var(--text-dim);margin-left:4px;">{{ s.signal_type }}</span>{% endif %}
{% if s.priority in ('P1','P2') %}<span style="font-size:10px;padding:2px 6px;border-radius:4px;background:{% if s.priority=='P1' %}var(--red-bg){% else %}var(--yellow-bg){% endif %};color:{% if s.priority=='P1' %}var(--red){% else %}var(--yellow){% endif %};margin-left:4px;">{{ s.priority }}</span>{% endif %}
</div>
<span class="signal-time">{{ s.detected_at }}</span>
</div>
<div class="signal-title">{{ s.headline or s.title or '' }}</div>
<div class="signal-summary">{{ s.detail or s.summary or '' }}</div>
{% if s.source_url or s.url %}<a href="{{ s.source_url or s.url }}" target="_blank" style="font-size:11px;">Source →</a>{% endif %}
</div>
{% endfor %}
{% else %}<div class="empty"><p>No signals attributed to this account yet</p></div>{% endif %}
</div>

<!-- Drafts -->
{% if drafts %}
<div class="card" style="margin-top:16px;"><h3>Recent Drafts</h3>
{% for d in drafts %}
<div style="padding:10px 0;border-bottom:1px solid var(--border);">
<div style="display:flex;justify-content:space-between;align-items:center;">
<div><span style="font-weight:600;">{{ d.contact_name or 'Unknown' }}</span> <span style="color:var(--text-dim);font-size:12px;">· {{ d.touch_type }}</span></div>
<span class="status {{ d.status|lower }}">{{ d.status }}</span>
</div>
{% if d.subject %}<div style="font-size:12px;margin-top:4px;">{{ d.subject }}</div>{% endif %}
</div>
{% endfor %}
</div>
{% endif %}

<!-- Touch History -->
{% if touches %}
<div class="card" style="margin-top:16px;"><h3>Touch History</h3>
<table><tr><th>Date</th><th>Contact</th><th>Channel</th><th>Subject</th><th>Status</th></tr>
{% for t in touches %}<tr>
<td style="font-size:12px;white-space:nowrap;">{{ t.sent_at }}</td>
<td>{{ t.contact_name or '—' }}</td>
<td>{{ t.touch_type }}</td>
<td style="font-size:12px;">{{ t.subject or '—' }}</td>
<td><span class="status {{ t.status|lower }}">{{ t.status }}</span></td>
</tr>{% endfor %}</table>
</div>
{% endif %}

<div style="margin-top:16px;"><a href="/accounts" style="font-size:13px;">← Back to accounts</a></div>
{% endblock %}
```

### `abm_engine/dashboard/templates/contacts.html`

```html
{% extends "base.html" %}{% block title %}Contacts{% endblock %}
{% block content %}
<div class="page-header"><h1>Contact Directory</h1><p>All contacts across banks, vendors, subsidiaries, connectors and champions</p></div>
<div class="filters"><form method="get" action="/contacts" style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;">
<input type="text" name="q" value="{{ search }}" placeholder="Search name, company, role...">
<select name="tier" onchange="this.form.submit()"><option value="">All Tiers</option>{% for t in all_tiers %}<option value="{{ t }}" {% if tier_filter==t %}selected{% endif %}>{{ t }}</option>{% endfor %}</select>
<select name="type" onchange="this.form.submit()"><option value="">All Types</option>{% for t in all_types %}<option value="{{ t }}" {% if type_filter==t %}selected{% endif %}>{{ t }}</option>{% endfor %}</select>
<button type="submit" class="btn btn-send btn-sm">Search</button>
{% if search or tier_filter or type_filter %}<a href="/contacts" class="btn btn-reject btn-sm">Clear</a>{% endif %}
</form></div>
<div class="card"><div style="margin-bottom:12px;"><h3 style="margin:0;">{{ contacts|length }} contacts</h3></div>
{% if contacts %}<table><tr><th>Name</th><th>Institution</th><th>Role</th><th>Type</th><th>Tier</th><th>Score</th><th>Consent</th><th>Touch</th></tr>
{% for c in contacts %}<tr>
<td><a href="/contact/{{ c.id }}">{{ c.full_name }}</a>{% if c.do_not_contact %} <span class="warn-badge">DNC</span>{% endif %}</td>
<td>{{ c.institution or '—' }}</td><td style="color:var(--text-dim);font-size:12px;">{{ c.role or '—' }}</td>
<td><span class="rtype {{ (c.relationship_type or '')|lower }}">{{ c.relationship_type or '—' }}</span></td>
<td><span class="tier {{ c.tier or '' }}">{{ c.tier or '—' }}</span></td>
<td><div class="score-bar"><div class="score-fill" style="width:{{ c.priority_score or 0 }}%;background:{% if (c.priority_score or 0)>=75 %}var(--red){% elif (c.priority_score or 0)>=50 %}var(--yellow){% else %}var(--accent){% endif %};"></div></div>{{ c.priority_score or 0 }}</td>
<td><span style="font-size:11px;color:{% if c.consent_status=='opted_in' %}var(--green){% elif c.consent_status=='denied' %}var(--red){% else %}var(--text-dim){% endif %}">{{ c.consent_status or 'none' }}</span></td>
<td>{{ c.current_touch or 0 }}</td></tr>{% endfor %}</table>
{% else %}<div class="empty"><h3>No contacts match</h3></div>{% endif %}</div>
{% endblock %}
```

### `abm_engine/dashboard/templates/contact_detail.html`

```html
{% extends "base.html" %}{% block title %}{{ contact.full_name }}{% endblock %}
{% block content %}
<div class="page-header" style="display:flex;justify-content:space-between;align-items:flex-start;">
<div><h1>{{ contact.full_name }}</h1><p>{{ contact.role or '' }} {% if contact.institution %}at {{ contact.institution }}{% endif %}</p></div>
<div style="display:flex;gap:8px;flex-wrap:wrap;">
<span class="tier {{ contact.tier or '' }}">{{ contact.tier or 'COLD' }}</span>
<span class="rtype {{ (contact.relationship_type or '')|lower }}">{{ contact.relationship_type or 'TARGET' }}</span>
{% if contact.do_not_contact %}<span class="warn-badge">DO NOT CONTACT</span>{% endif %}
{% if is_unsubscribed %}<span class="warn-badge">UNSUBSCRIBED</span>{% endif %}
</div></div>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
<div class="card"><h3>Contact Info</h3><div class="detail-grid">
<div><div class="field-label">Email</div><div class="field-value">{{ contact.email or '—' }}</div></div>
<div><div class="field-label">Phone</div><div class="field-value">{{ contact.phone or '—' }}</div></div>
<div><div class="field-label">WhatsApp</div><div class="field-value">{{ contact.whatsapp or '—' }}</div></div>
<div><div class="field-label">LinkedIn</div><div class="field-value">{% if contact.linkedin_url %}<a href="{{ contact.linkedin_url }}" target="_blank">Profile</a>{% else %}—{% endif %}</div></div>
<div><div class="field-label">Persona</div><div class="field-value">{{ contact.persona or '—' }}</div></div>
<div><div class="field-label">Warmness</div><div class="field-value">{{ contact.warmness or 'Cold' }}</div></div>
</div></div>
<div class="card"><h3>Scoring & Compliance</h3><div class="detail-grid">
<div><div class="field-label">Priority Score</div><div class="field-value" style="font-size:28px;font-weight:700;color:{% if (contact.priority_score or 0)>=75 %}var(--red){% elif (contact.priority_score or 0)>=50 %}var(--yellow){% else %}var(--accent){% endif %};">{{ contact.priority_score or 0 }}/100</div></div>
<div><div class="field-label">Touch Count</div><div class="field-value" style="font-size:28px;font-weight:700;">{{ contact.current_touch or 0 }}</div></div>
<div><div class="field-label">Consent Status</div><div class="field-value"><span style="color:{% if contact.consent_status=='opted_in' %}var(--green){% elif contact.consent_status=='denied' %}var(--red){% else %}var(--yellow){% endif %}">{{ contact.consent_status or 'none' }}</span>
<div class="btn-group" style="margin-top:6px;"><button class="btn btn-sm btn-approve" onclick="setConsent({{ contact.id }},'opted_in')">Opted In</button><button class="btn btn-sm btn-reject" onclick="setConsent({{ contact.id }},'denied')">Denied</button></div></div></div>
<div><div class="field-label">Consent Source</div><div class="field-value">{{ contact.consent_source or '—' }}</div></div>
<div><div class="field-label">Outreach Angle</div><div class="field-value">{{ contact.outreach_angle or '—' }}</div></div>
<div><div class="field-label">Product Fit</div><div class="field-value">{{ contact.product_fit or '—' }}</div></div>
<div style="grid-column:span 2;"><div class="field-label">Key Signal</div><div class="field-value">{{ contact.key_signal or '—' }}</div></div>
{% if contact.background_notes %}<div style="grid-column:span 2;"><div class="field-label">Background</div><div class="field-value" style="font-size:13px;color:var(--text-dim);">{{ contact.background_notes }}</div></div>{% endif %}
{% if contact.pitch_notes %}<div style="grid-column:span 2;"><div class="field-label">Pitch Notes</div><div class="field-value" style="font-size:13px;color:var(--text-dim);">{{ contact.pitch_notes }}</div></div>{% endif %}
</div></div></div>
{% if pending %}<div class="card" style="margin-top:16px;"><h3>Pending Drafts</h3>{% for d in pending %}<div style="padding:10px 0;border-bottom:1px solid var(--border);">{% if d.subject %}<div class="draft-subject">{{ d.subject }}</div>{% endif %}<div class="draft-body">{{ d.body_en }}</div><div class="btn-group" style="margin-top:8px;"><button class="btn btn-approve btn-sm" onclick="approve({{ d.id }})">Approve</button><button class="btn btn-reject btn-sm" onclick="reject({{ d.id }})">Reject</button></div></div>{% endfor %}</div>{% endif %}
<div class="card" style="margin-top:16px;"><h3>Touch History</h3>{% if touches %}<table><tr><th>Date</th><th>Channel</th><th>Subject</th><th>Status</th></tr>{% for t in touches %}<tr><td style="font-size:12px;">{{ t.sent_at }}</td><td>{{ t.touch_type }}</td><td>{{ t.subject or '—' }}</td><td><span class="status {{ t.status|lower }}">{{ t.status }}</span></td></tr>{% endfor %}</table>{% else %}<div class="empty"><p>No outreach history</p></div>{% endif %}</div>
<div style="margin-top:16px;"><a href="/contacts" style="font-size:13px;">Back to contacts</a></div>
{% endblock %}
{% block scripts %}<script>
async function approve(id){const r=await fetch(`/api/draft/${id}/approve`,{method:'POST'});const d=await r.json();if(d.ok)location.reload();else alert(d.error||'Failed')}
async function reject(id){const n=prompt('Reason:');const r=await fetch(`/api/draft/${id}/reject`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({notes:n||''})});if(r.ok)location.reload()}
async function setConsent(cid,status){const src=prompt('Source (e.g. LinkedIn, email reply, conference):');const r=await fetch(`/api/contact/${cid}/consent`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({consent_status:status,consent_source:src||''})});if(r.ok)location.reload()}
</script>{% endblock %}
```

### `abm_engine/dashboard/templates/drafts.html`

```html
{% extends "base.html" %}
{% block title %}Drafts{% endblock %}
{% block content %}
<div class="page-header"><h1>Message Drafts</h1><p>Review, edit, approve or reject before anything sends</p></div>
<div class="filters">
<a href="/drafts?status=pending" class="btn {% if current_filter=='pending' %}btn-approve{% else %}btn-reject{% endif %} btn-sm">Pending</a>
<a href="/drafts?status=approved" class="btn {% if current_filter=='approved' %}btn-approve{% else %}btn-reject{% endif %} btn-sm">Approved</a>
<a href="/drafts?status=sent" class="btn {% if current_filter=='sent' %}btn-send{% else %}btn-reject{% endif %} btn-sm">Sent</a>
<a href="/drafts?status=rejected" class="btn {% if current_filter=='rejected' %}btn-approve{% else %}btn-reject{% endif %} btn-sm">Rejected</a>
<a href="/drafts?status=all" class="btn {% if current_filter=='all' %}btn-approve{% else %}btn-reject{% endif %} btn-sm">All</a>
</div>
<!-- Edit modal -->
<div id="edit-modal" style="display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.7);z-index:200;padding:40px;overflow-y:auto;">
<div style="max-width:600px;margin:0 auto;background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:24px;">
<div style="display:flex;justify-content:space-between;margin-bottom:16px;"><h2 style="font-size:16px;">Edit Draft</h2><button onclick="closeEditModal()" style="background:none;border:none;color:var(--text-dim);font-size:20px;cursor:pointer;">&times;</button></div>
<input type="hidden" id="edit-id">
<div style="margin-bottom:12px;"><label style="font-size:12px;color:var(--text-dim);display:block;margin-bottom:4px;">SUBJECT</label><input type="text" id="edit-subject" style="width:100%;background:var(--surface2);border:1px solid var(--border);color:var(--text);padding:10px;border-radius:6px;font-size:14px;"></div>
<div style="margin-bottom:12px;"><label style="font-size:12px;color:var(--text-dim);display:block;margin-bottom:4px;">BODY</label><textarea id="edit-body" rows="12" style="width:100%;background:var(--surface2);border:1px solid var(--border);color:var(--text);padding:10px;border-radius:6px;font-size:13px;line-height:1.6;resize:vertical;font-family:inherit;"></textarea></div>
<div style="display:flex;gap:8px;justify-content:flex-end;"><button class="btn btn-reject" onclick="closeEditModal()">Cancel</button><button class="btn btn-approve" onclick="saveEdit()">Save</button></div>
</div></div>
{% if drafts %}{% for d in drafts %}
<div class="card" id="draft-{{ d.id }}">
<div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:8px;">
<div>
<a href="/contact/{{ d.contact_id }}" style="font-weight:600;font-size:15px;">{{ d.contact_name or 'Unknown' }}</a>
<span style="color:var(--text-dim);font-size:12px;margin-left:8px;">{{ d.company or '' }} · {{ d.title or '' }}</span>
{% if d.do_not_contact %}<span class="warn-badge" style="margin-left:6px;">DO NOT CONTACT</span>{% endif %}
</div>
<div style="display:flex;gap:8px;align-items:center;">
<span class="status {{ d.status|lower }}">{{ d.status }}</span>
{% if d.touch_type == 'LINKEDIN' %}<span style="font-size:11px;padding:3px 8px;border-radius:4px;background:rgba(79,140,255,.12);color:var(--accent);font-weight:600;">LinkedIn · T{{ d.touch_number }}</span>{% else %}<span style="color:var(--text-dim);font-size:11px;">email · T{{ d.touch_number }}</span>{% endif %}
</div></div>
{% if d.subject %}<div class="draft-subject" style="margin-top:10px;">Subject: {{ d.subject }}</div>{% endif %}
<div class="draft-body">{{ d.body_en or '(empty)' }}</div>
<div style="display:flex;justify-content:space-between;align-items:center;margin-top:8px;">
<span style="color:var(--text-dim);font-size:11px;">{{ d.generated_at }}</span>
{% if d.status == 'DRAFT' %}
<div class="btn-group">
<button class="btn btn-approve btn-sm" onclick="approve({{ d.id }})">Approve</button>
<button class="btn btn-reject btn-sm" onclick="reject({{ d.id }})">Reject</button>
<button class="btn btn-sm" style="background:var(--surface2);color:var(--text);" onclick="openEditModal({{ d.id }},'{{ d.subject|default("",true)|e }}')">Edit</button>
<button class="btn btn-sm" style="background:var(--surface2);color:var(--accent);" onclick="useTemplate({{ d.id }})">Use as Template</button>
</div>
{% elif d.status == 'APPROVED' %}
<div class="btn-group">
{% if d.touch_type == 'LINKEDIN' and d.linkedin_url %}<a class="btn btn-sm" style="background:var(--surface2);color:var(--text);" href="{{ d.linkedin_url }}" target="_blank">Open LinkedIn</a>{% endif %}
<button class="btn btn-send btn-sm" onclick="sendNow({{ d.id }})">Send Now</button>
</div>
{% elif d.status == 'REJECTED' %}
<button class="btn btn-sm" style="background:var(--surface2);color:var(--accent);" onclick="redraft({{ d.id }})">Redraft</button>
{% endif %}
</div>
{% if d.rejection_reason %}<div style="margin-top:8px;font-size:12px;color:var(--text-dim);font-style:italic;">{{ d.rejection_reason }}</div>{% endif %}
</div>{% endfor %}
{% else %}<div class="card"><div class="empty"><h3>No {{ current_filter }} drafts</h3><p>The engine generates drafts daily and sends approved ones every 30 minutes.</p></div></div>{% endif %}
{% endblock %}
{% block scripts %}
<script>
async function approve(id){const r=await fetch(`/api/draft/${id}/approve`,{method:'POST'});const d=await r.json();if(d.ok)location.reload();else alert(d.error||'Failed')}
async function reject(id){const n=prompt('Reason (optional):');const r=await fetch(`/api/draft/${id}/reject`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({notes:n||''})});if(r.ok)location.reload()}
async function sendNow(id){if(!confirm('Send this message now?'))return;const r=await fetch(`/api/draft/${id}/send`,{method:'POST'});const d=await r.json();if(d.ok)location.reload();else alert(d.error||'Send failed')}
async function redraft(id){if(!confirm('Delete this draft and regenerate on next cycle?'))return;const r=await fetch(`/api/draft/${id}/redraft`,{method:'POST'});if(r.ok)location.reload()}
async function useTemplate(id){const n=prompt('Template name:','My Template');if(!n)return;const r=await fetch(`/api/draft/${id}/use-as-template`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:n})});if(r.ok)location.href='/templates'}
function openEditModal(id,subj){document.getElementById('edit-id').value=id;document.getElementById('edit-subject').value=subj;document.getElementById('edit-body').value=document.querySelector(`#draft-${id} .draft-body`).innerText;document.getElementById('edit-modal').style.display='block'}
function closeEditModal(){document.getElementById('edit-modal').style.display='none'}
async function saveEdit(){const id=document.getElementById('edit-id').value;const r=await fetch(`/api/draft/${id}/edit`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({subject:document.getElementById('edit-subject').value,body:document.getElementById('edit-body').value})});if(r.ok)location.reload()}
</script>
{% endblock %}
```

### `abm_engine/dashboard/templates/intelligence.html`

```html
{% extends "base.html" %}
{% block title %}Intelligence{% endblock %}
{% block content %}
<div class="page-header">
    <h1>Intelligence Feed</h1>
    <p>Signals from banks, vendors, SAMA, leadership changes, and CRM updates</p>
</div>

<div class="card">
    {% if signals %}
    {% for s in signals %}
    <div class="signal-item" id="signal-{{ s.id }}" style="{% if s.is_read %}opacity:0.5;{% endif %}">
        <div style="display:flex; justify-content:space-between; align-items:flex-start;">
            <div>
                <span class="signal-source">{{ s.source_name or s.category or 'signal' }}</span>
                {% if s.institution %}
                <span style="font-size:11px; color:var(--accent); margin-left:8px;">{{ s.institution }}</span>
                {% endif %}
                {% if s.relevance_score %}
                <span style="font-size:11px; color:var(--text-dim); margin-left:8px;">relevance {{ s.relevance_score }}/10</span>
                {% endif %}
            </div>
            {% if not s.is_read %}
            <button class="btn btn-sm" style="background:var(--surface2);color:var(--text-dim);" onclick="markRead({{ s.id }})">Mark read</button>
            {% endif %}
        </div>
        <div class="signal-title">{{ s.headline }}</div>
        <div class="signal-summary">{{ s.summary or '' }}</div>
        {% if s.source_url %}
        <a href="{{ s.source_url }}" target="_blank" style="font-size:12px;">Read source →</a>
        {% endif %}
        <div class="signal-time">{{ s.detected_at }}</div>
    </div>
    {% endfor %}
    {% else %}
    <div class="empty">
        <h3>No signals yet</h3>
        <p>Run signal detection to scan for news:</p>
        <code style="background:var(--surface2);padding:8px 14px;border-radius:6px;display:inline-block;margin-top:12px;">python -m abm_engine signals</code>
    </div>
    {% endif %}
</div>
{% endblock %}

{% block scripts %}
<script>
async function markRead(id) {
    const res = await fetch(`/api/signal/${id}/read`, {method:'POST'});
    if (res.ok) {
        document.getElementById(`signal-${id}`).style.opacity = '0.5';
    }
}
</script>
{% endblock %}
```

*(`templates.html` and `audit.html` were not changed — their field names already matched
the SQLite `templates`/`audit_log` tables exactly.)*

---

## `abm_engine/.env` (not included — contains live API keys)

Two changes, described rather than dumped here since this file holds real secrets:
1. Removed a stale duplicate `CONTACTS_EXCEL_PATH=C:\Users\Puneet\Desktop\decimal_abm\...`
   line pointing at a path from before the project moved into the `ABM business logic`
   folder — it was silently overriding the correct relative path.
2. Corrected the remaining `CONTACTS_EXCEL_PATH` to `./abm_engine/data/abm_contacts.xlsx`,
   relative to the `decimal_abm/` directory `-m abm_engine` must be invoked from.

## `abm_engine/README.md`

Added a note that `engine_scheduler.py` is superseded (don't run it alongside the CLI
commands), and added the `python -m abm_engine dashboard` command to the "Running the
engine" section (Terminal 3).
