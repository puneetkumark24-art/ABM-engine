"""Signal Engine v2 bridge — one-way, idempotent export from the isolated
signal_engine shadow database into DRIP's real Signal table.

Adapted from drip_integration/abm_engine/signal_integration/bridge.py (written
for decimal_abm's Flask app + raw-sqlite3 `signals`/`news_items` tables with a
free-text `institution` column) to drip_platform's actual architecture:
SQLAlchemy models.py, org_id foreign keys (not text names), and no separate
news_items table (drip_platform's Signal row already carries source/url/title).

Safety model carried over unchanged from the original:
  - Only ever INSERTs into `signals` and this module's own `signal_v2_exports`
    audit table. Never touches drafts, contacts, sequences, or any send path.
  - Idempotent by signal_engine UUID: re-running never duplicates a signal.
  - Exports only rows that are active, scoring_eligible, action_eligible=0
    (shadow fail-safe), quality-passed with sufficient completeness/
    materiality, and not currently contested by a pending correction.
  - Read-only against signal_engine.db except for its own export ledger.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from datetime import datetime

from sqlalchemy.orm import Session
from sqlalchemy import inspect, text as sqltext

import models
from signal_engine import catalog as se_catalog

# Decimal Technologies must never appear as a prospect-monitored account.
EXCLUDED_ACCOUNT_NAMES = {"decimal technologies", "decimal"}


def _connect_signal_db(path: str | Path) -> sqlite3.Connection:
    con = sqlite3.connect(Path(path))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


def _runtime_accounts(signal_db_path: str | Path | None) -> list[dict]:
    """Accounts that exist in the signal database but not in the static catalog.

    `Pipeline.add_account()` lets an operator (or a collector) register a bank
    at run time, and capture/attribution/scoring/quality all handle those
    signals correctly. Only this map knew nothing about them -- it iterated
    `se_catalog.ACCOUNTS` alone -- so every such signal was captured, scored,
    quality-gated and then silently dropped at the CRM boundary with a skip
    reason blaming a "name mismatch", which sends you looking at the wrong
    thing entirely. Reading the signal DB's own accounts table closes that.
    """
    if not signal_db_path:
        return []
    path = Path(signal_db_path)
    if not path.exists():
        return []
    out: list[dict] = []
    try:
        with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as con:
            con.row_factory = sqlite3.Row
            cols = {r["name"] for r in con.execute("PRAGMA table_info(accounts)")}
            if not cols:
                return []
            for r in con.execute("SELECT * FROM accounts"):
                aliases = []
                raw = r["aliases"] if "aliases" in cols else None
                if raw:
                    try:
                        parsed = json.loads(raw)
                        aliases = parsed if isinstance(parsed, list) else []
                    except (ValueError, TypeError):
                        aliases = [a.strip() for a in str(raw).split(",") if a.strip()]
                name = r["canonical_name"] if "canonical_name" in cols else None
                if not name:
                    continue
                out.append({"id": r["id"], "name": name, "aliases": aliases})
    except sqlite3.Error:
        return []
    return out


def build_account_map(db: Session, signal_db_path: str | Path | None = None) -> dict:
    """Resolve each signal_engine bank to a drip_platform organizations.id (UUID).

    Covers both the static catalog (11 banks, stable ids like 'snb',
    'al_rajhi') and — when `signal_db_path` is given — any account registered
    at run time in the signal database itself.

    Matching is by exact/alias name against models.Organization.name --
    deliberately NOT a hardcoded UUID list, since those UUIDs are only known
    inside the user's real Postgres database, which this bridge script reads
    live at run time rather than assuming.

    Returns {"matched": {se_id: {"org_id":..., "org_name":..., "matched_on":...}},
             "unmatched": [se_id, ...],
             "excluded": [se_id, ...]}   -- Decimal itself, if it were ever
                                             (wrongly) present in the catalog.
    """
    orgs = db.query(models.Organization.id, models.Organization.canonical_name,
                     models.Organization.short_name, models.Organization.aliases).all()
    # normalized name -> org_id. Indexes canonical_name, short_name, AND
    # drip_platform's own stored aliases column, unioned with the
    # signal_engine catalog's alias set below, so a match on either side works.
    org_by_norm: dict[str, str] = {}
    for o in orgs:
        for cand in [o.canonical_name, o.short_name, *(o.aliases or [])]:
            if cand:
                org_by_norm.setdefault(cand.strip().lower(), o.id)

    matched, unmatched, excluded = {}, [], []
    # Catalog first, then runtime accounts the catalog does not already cover.
    known = {a["id"] for a in se_catalog.ACCOUNTS}
    all_accounts = list(se_catalog.ACCOUNTS) + [
        a for a in _runtime_accounts(signal_db_path) if a["id"] not in known]
    for acct in all_accounts:
        se_id = acct["id"]
        candidates = [acct["name"]] + acct.get("aliases", [])
        if any(c.strip().lower() in EXCLUDED_ACCOUNT_NAMES for c in candidates):
            excluded.append(se_id)
            continue
        hit = None
        for cand in candidates:
            norm = cand.strip().lower()
            if norm in org_by_norm:
                hit = (org_by_norm[norm], cand)
                break
        if hit:
            matched[se_id] = {"org_id": hit[0], "org_name": acct["name"], "matched_on": hit[1]}
        else:
            unmatched.append(se_id)
    return {"matched": matched, "unmatched": unmatched, "excluded": excluded}


def ensure_export_table(db: Session) -> None:
    db.execute(sqltext("""
        CREATE TABLE IF NOT EXISTS signal_v2_exports (
            signal_uuid      VARCHAR(64) PRIMARY KEY,
            drip_signal_id   VARCHAR(36) NOT NULL,
            se_account_id    VARCHAR(64) NOT NULL,
            org_id           VARCHAR(36),
            exported_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            export_policy    VARCHAR(64) NOT NULL
        )
    """))
    db.commit()


def _already_exported(db: Session) -> set:
    rows = db.execute(sqltext("SELECT signal_uuid FROM signal_v2_exports")).fetchall()
    return {r[0] for r in rows}


def preview(db: Session, signal_db_path: str | Path) -> list[dict]:
    """Read-only: eligible, not-yet-exported signal_engine rows. Changes nothing.

    Eligibility is deliberately stricter than just scoring_eligible=1: a row
    must also be action_eligible=0 (the shadow-only fail-safe), have passed
    the signal_engine quality gate (quality_decision='pass' with sufficient
    completeness/materiality), and have no pending contradiction/correction
    against it (claim_relations). Trusting scoring_eligible alone let
    incomplete, low-materiality, or actively-contested observations through.
    """
    # Preview must remain a true read: schema creation belongs to migration/apply.
    exported = _already_exported(db) if inspect(db.bind).has_table("signal_v2_exports") else set()
    # Same map the export will use -- including runtime accounts -- so preview
    # cannot promise a row that export then silently skips.
    acct_map = build_account_map(db, signal_db_path)
    out = []
    with closing(_connect_signal_db(signal_db_path)) as con:
        rows = con.execute("""
            SELECT s.*, a.id AS se_account_id, a.canonical_name, o.canonical_url,
                   q.quality_decision, q.completeness_score, q.materiality_score
            FROM signals s
            JOIN accounts a ON a.id = s.account_id
            JOIN observations o ON o.id = s.observation_id
            JOIN observation_quality q ON q.observation_id = o.id
            WHERE s.status='active' AND s.scoring_eligible=1 AND s.action_eligible=0
              AND q.quality_decision='pass'
              AND q.completeness_score >= .70 AND q.materiality_score >= .45
              AND NOT EXISTS (
                  SELECT 1 FROM claim_relations cr
                  WHERE cr.related_signal_id=s.id AND cr.status='pending'
              )
            ORDER BY s.event_at
        """).fetchall()
        for r in rows:
            row = dict(r)
            if row["id"] in exported:
                continue
            if row["se_account_id"] not in acct_map["matched"]:
                row["_export_blocked_reason"] = (
                    "excluded (Decimal Technologies)" if row["se_account_id"] in acct_map["excluded"]
                    else ("this signal_engine account is not linked to any organization -- "
                                    "create an organization whose name or alias matches the "
                                    "account's canonical name, then re-run the export")
                )
            out.append(row)
    return out


def export_scoring_eligible(db: Session, signal_db_path: str | Path) -> dict:
    """Apply: writes eligible, mapped rows into models.Signal + the export
    ledger. Anything without a resolved org_id is skipped, not guessed."""
    ensure_export_table(db)
    acct_map = build_account_map(db, signal_db_path)
    candidates = preview(db, signal_db_path)
    exported, skipped = [], []

    for row in candidates:
        se_account_id = row["se_account_id"]
        mapping = acct_map["matched"].get(se_account_id)
        if mapping is None:
            skipped.append({"signal_uuid": row["id"], "reason": row.get("_export_blocked_reason", "unmapped")})
            continue

        urgency = {"CRITICAL": "CRITICAL", "HIGH": "HIGH"}.get((row.get("urgency") or "").upper(), "MEDIUM" if row.get("urgency") else "LOW")
        sig = models.Signal(
            org_id=mapping["org_id"],
            signal_type=(row.get("signal_type") or "other").lower(),
            source="Signal Engine v2",
            title=row.get("title"),
            summary=row.get("summary"),
            url=row.get("canonical_url"),
            urgency=urgency,
            confidence_score=row.get("confidence"),
            content_hash=row.get("id"),  # signal_engine UUID doubles as the dedup key here
            created_at=datetime.utcnow(),
        )
        db.add(sig)
        db.flush()  # get sig.id without committing yet

        db.execute(sqltext("""
            INSERT INTO signal_v2_exports (signal_uuid, drip_signal_id, se_account_id, org_id, export_policy)
            VALUES (:uuid, :sig_id, :se_acct, :org_id, :policy)
        """), {"uuid": row["id"], "sig_id": sig.id, "se_acct": se_account_id,
               "org_id": mapping["org_id"], "policy": "quality-gated-shadow-v2"})
        exported.append(row["id"])

    db.commit()
    return {"eligible": len(candidates), "exported": len(exported), "skipped": skipped,
            "signal_ids": exported}
