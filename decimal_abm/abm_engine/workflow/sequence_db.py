"""
abm_engine/workflow/sequence_db.py
─────────────────────────────────────
Additive schema for the sequencing / drip engine.

Three new tables, none of which touch or replace an existing one:

    sequence_definitions   named cadence (e.g. "Default 5-Touch",
                            "Connector Fast Track")
    sequence_steps         per-step channel + wait_days_after_previous,
                            ordered by step_number
    sequence_enrollments   one row per (contact, sequence) — current_step +
                            status (ACTIVE/PAUSED/COMPLETED/EXITED)

Why not just add columns to `contacts`? Because a single hardcoded cadence
(the old "current_touch < 5, one send per 3 days" logic in database/db.py)
can't express "Connector relationships get a slower, warmer cadence" or "HOT
tier accounts get touch 2 after 2 days instead of 3" without another
if/elif chain. Modeling it as definitions+steps+enrollments means new
cadences are a data change, not a code change — the same reason HubSpot (and
every other marketing-automation product) models workflows this way rather
than hardcoding step counts per contact type.

Uses the same sqlite3 connection helper as database/db.py so both modules
operate on the one physical abm_engine.db — no second database, no sync job.
"""
from __future__ import annotations

from typing import Optional

from loguru import logger

from ..database.db import get_conn


def init_sequence_tables() -> None:
    conn = get_conn()
    with conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sequence_definitions (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                name                TEXT NOT NULL UNIQUE,
                relationship_type   TEXT,               -- NULL = fallback/default sequence
                is_active           INTEGER DEFAULT 1,
                created_at          TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS sequence_steps (
                id                          INTEGER PRIMARY KEY AUTOINCREMENT,
                sequence_id                 INTEGER NOT NULL REFERENCES sequence_definitions(id),
                step_number                 INTEGER NOT NULL,
                channel                     TEXT NOT NULL DEFAULT 'EMAIL',  -- EMAIL | LINKEDIN | BOTH
                wait_days_after_previous    INTEGER NOT NULL DEFAULT 3,
                is_final                    INTEGER DEFAULT 0,
                UNIQUE(sequence_id, step_number)
            );

            CREATE TABLE IF NOT EXISTS sequence_enrollments (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                contact_id      INTEGER NOT NULL REFERENCES contacts(id),
                sequence_id     INTEGER NOT NULL REFERENCES sequence_definitions(id),
                status          TEXT NOT NULL DEFAULT 'ACTIVE',  -- ACTIVE | PAUSED | COMPLETED | EXITED
                current_step    INTEGER NOT NULL DEFAULT 0,
                enrolled_at     TEXT DEFAULT (datetime('now')),
                paused_at       TEXT,
                pause_reason    TEXT,
                completed_at    TEXT,
                updated_at      TEXT DEFAULT (datetime('now')),
                UNIQUE(contact_id, sequence_id)
            );

            CREATE INDEX IF NOT EXISTS idx_enrollments_contact ON sequence_enrollments(contact_id);
            CREATE INDEX IF NOT EXISTS idx_enrollments_status  ON sequence_enrollments(status);
            CREATE INDEX IF NOT EXISTS idx_steps_sequence      ON sequence_steps(sequence_id);
        """)
    logger.info("Sequence engine tables ready (sequence_definitions/steps/enrollments)")


# ─── Definitions & steps ──────────────────────────────────────────────────────

def get_sequence_by_name(name: str) -> Optional[dict]:
    conn = get_conn()
    row = conn.execute("SELECT * FROM sequence_definitions WHERE name=?", (name,)).fetchone()
    return dict(row) if row else None


def create_sequence(name: str, relationship_type: Optional[str] = None) -> int:
    conn = get_conn()
    with conn:
        cur = conn.execute(
            "INSERT INTO sequence_definitions (name, relationship_type) VALUES (?,?)",
            (name, relationship_type),
        )
        return cur.lastrowid


def add_step(sequence_id: int, step_number: int, channel: str,
             wait_days_after_previous: int, is_final: bool = False) -> int:
    conn = get_conn()
    with conn:
        cur = conn.execute("""
            INSERT INTO sequence_steps
                (sequence_id, step_number, channel, wait_days_after_previous, is_final)
            VALUES (?,?,?,?,?)
            ON CONFLICT(sequence_id, step_number) DO UPDATE SET
                channel=excluded.channel,
                wait_days_after_previous=excluded.wait_days_after_previous,
                is_final=excluded.is_final
        """, (sequence_id, step_number, channel, wait_days_after_previous, int(is_final)))
        return cur.lastrowid


def get_steps(sequence_id: int) -> list[dict]:
    conn = get_conn()
    return [dict(r) for r in conn.execute(
        "SELECT * FROM sequence_steps WHERE sequence_id=? ORDER BY step_number", (sequence_id,)
    ).fetchall()]


def get_step(sequence_id: int, step_number: int) -> Optional[dict]:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM sequence_steps WHERE sequence_id=? AND step_number=?",
        (sequence_id, step_number),
    ).fetchone()
    return dict(row) if row else None


def sequence_for_relationship_type(relationship_type: str) -> Optional[dict]:
    """Most specific match wins; falls back to the NULL/default sequence."""
    conn = get_conn()
    row = conn.execute("""
        SELECT * FROM sequence_definitions
        WHERE is_active=1 AND relationship_type=?
        ORDER BY id LIMIT 1
    """, (relationship_type,)).fetchone()
    if row:
        return dict(row)
    row = conn.execute("""
        SELECT * FROM sequence_definitions
        WHERE is_active=1 AND relationship_type IS NULL
        ORDER BY id LIMIT 1
    """).fetchone()
    return dict(row) if row else None


# ─── Enrollments ───────────────────────────────────────────────────────────────

def get_enrollment(contact_id: int, sequence_id: int) -> Optional[dict]:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM sequence_enrollments WHERE contact_id=? AND sequence_id=?",
        (contact_id, sequence_id),
    ).fetchone()
    return dict(row) if row else None


def get_active_enrollment_for_contact(contact_id: int) -> Optional[dict]:
    conn = get_conn()
    row = conn.execute("""
        SELECT * FROM sequence_enrollments
        WHERE contact_id=? AND status='ACTIVE'
        ORDER BY id DESC LIMIT 1
    """, (contact_id,)).fetchone()
    return dict(row) if row else None


def enroll(contact_id: int, sequence_id: int, current_step: int = 0) -> int:
    """Idempotent — enrolling an already-enrolled contact is a no-op that
    returns the existing enrollment id, so backfill can run safely on every
    startup without duplicating rows."""
    existing = get_enrollment(contact_id, sequence_id)
    if existing:
        return existing["id"]
    conn = get_conn()
    with conn:
        cur = conn.execute("""
            INSERT INTO sequence_enrollments (contact_id, sequence_id, current_step, status)
            VALUES (?,?,?, 'ACTIVE')
        """, (contact_id, sequence_id, current_step))
        return cur.lastrowid


def advance_enrollment(enrollment_id: int, is_final_step: bool) -> None:
    conn = get_conn()
    with conn:
        if is_final_step:
            conn.execute("""
                UPDATE sequence_enrollments
                SET current_step = current_step + 1, status='COMPLETED',
                    completed_at=datetime('now'), updated_at=datetime('now')
                WHERE id=?
            """, (enrollment_id,))
        else:
            conn.execute("""
                UPDATE sequence_enrollments
                SET current_step = current_step + 1, updated_at=datetime('now')
                WHERE id=?
            """, (enrollment_id,))


def pause_enrollment(enrollment_id: int, reason: str) -> None:
    conn = get_conn()
    with conn:
        conn.execute("""
            UPDATE sequence_enrollments
            SET status='PAUSED', paused_at=datetime('now'), pause_reason=?,
                updated_at=datetime('now')
            WHERE id=? AND status='ACTIVE'
        """, (reason, enrollment_id))


def pause_all_for_contact(contact_id: int, reason: str) -> None:
    conn = get_conn()
    with conn:
        conn.execute("""
            UPDATE sequence_enrollments
            SET status='PAUSED', paused_at=datetime('now'), pause_reason=?,
                updated_at=datetime('now')
            WHERE contact_id=? AND status='ACTIVE'
        """, (reason, contact_id))


def get_enrollment_counts() -> dict:
    conn = get_conn()
    row = conn.execute("""
        SELECT
            SUM(CASE WHEN status='ACTIVE'    THEN 1 ELSE 0 END) active,
            SUM(CASE WHEN status='PAUSED'    THEN 1 ELSE 0 END) paused,
            SUM(CASE WHEN status='COMPLETED' THEN 1 ELSE 0 END) completed,
            SUM(CASE WHEN status='EXITED'    THEN 1 ELSE 0 END) exited,
            COUNT(*) total
        FROM sequence_enrollments
    """).fetchone()
    return dict(row) if row else {}
