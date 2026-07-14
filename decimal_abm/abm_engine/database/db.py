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
    """
    Contacts ready for next touch — HOT first, warm relationships first.

    Compliance gate (added Phase 1 — drip engine hardening): a contact who is
    do_not_contact=1 or whose consent_status is an explicit 'denied' must never
    be drafted, even if they otherwise look "due". Both columns already exist on
    the live table (added by an earlier migration) but were never checked here —
    see PHASE_1_DRIP_ENGINE_CHANGES.md for why this matters.
    """
    conn = get_conn()
    rows = conn.execute("""
        SELECT c.* FROM contacts c
        LEFT JOIN touch_records t
            ON t.contact_id = c.id AND t.status = 'SENT'
            AND t.sent_at > datetime('now', '-3 days')
        WHERE c.is_active = 1 AND c.replied = 0 AND c.current_touch < 5
          AND COALESCE(c.do_not_contact, 0) = 0
          AND COALESCE(c.consent_status, '') != 'denied'
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
    """
    Compliance gate (Phase 1): a draft can sit APPROVED for hours before the
    30-min send job runs. If the contact replied, unsubscribed, or was marked
    do_not_contact in that window, the send must not go out anyway — this is
    exactly the "no duplicate/late outreach after reply" behavior (T-STATE-1 in
    Build Artifact 3). Approval alone is no longer sufficient; the contact's
    current state is re-checked at send time.
    """
    conn = get_conn()
    rows = conn.execute("""
        SELECT d.*, c.full_name, c.institution, c.role, c.tier,
               c.relationship_type, c.email, c.linkedin_url,
               c.hubspot_contact_id
        FROM draft_messages d
        JOIN contacts c ON c.id = d.contact_id
        WHERE d.status = 'APPROVED' AND d.sent_at IS NULL
          AND c.replied = 0
          AND COALESCE(c.do_not_contact, 0) = 0
          AND COALESCE(c.consent_status, '') != 'denied'
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
