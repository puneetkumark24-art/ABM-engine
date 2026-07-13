"""
migrate_from_decimal_abm.py — Phase 2a data recovery.

Reads the LIVE decimal_abm SQLite database directly (not schema_v2.sql, which
drifted from the live DB per Phase 1 findings) and loads it into the new DRIP
schema. Then layers in the documented contacts that never made it into any
structured file (etl/documented_contacts_seed.py).

Usage:
    python etl/migrate_from_decimal_abm.py --sqlite-path /path/to/abm_engine.db

Idempotent: re-running skips organizations/products that already exist by
canonical_name.
"""
from __future__ import annotations
import argparse
import sqlite3
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))
from database import Base, engine, SessionLocal
import models
from etl import documented_contacts_seed


def _sqlite_rows(sqlite_path: str, table: str) -> list[dict]:
    con = sqlite3.connect(sqlite_path)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute(f"SELECT * FROM {table}").fetchall()]
    except sqlite3.OperationalError:
        return []
    finally:
        con.close()


def migrate_accounts(db, sqlite_path: str) -> dict:
    rows = _sqlite_rows(sqlite_path, "accounts")
    created, skipped = 0, 0
    org_by_old_id = {}
    for r in rows:
        name = r.get("name")
        if not name:
            continue
        org = db.query(models.Organization).filter(models.Organization.canonical_name == name).first()
        if not org:
            org = models.Organization(
                canonical_name=name,
                name_ar=r.get("name_ar"),
                country=r.get("country") or "Saudi Arabia",
                website=r.get("website"),
                core_banking=r.get("core_banking"),
                employee_count=r.get("employees"),
                assets_usd_billions=r.get("assets_usd"),
                founded=r.get("founded"),
                source="decimal_abm/abm_engine.db (seed_accounts.py)",
                verification_status="verified",
            )
            db.add(org)
            db.flush()
            db.add(models.OrgTypeTag(org_id=org.id, type_tag="commercial_bank"))
            created += 1
        else:
            skipped += 1
        org_by_old_id[r["id"]] = org.id

        acc = db.get(models.AccountIntelligence, org.id)
        if not acc:
            acc = models.AccountIntelligence(
                org_id=org.id,
                segment=r.get("segment"),
                sub_segment=r.get("sub_segment"),
                digital_maturity=r.get("digital_maturity") or 5,
                open_banking=r.get("open_banking") or "Unknown",
                tier=r.get("tier") or "Tier 3",
                priority=r.get("priority") or "COLD",
                lifecycle_status=r.get("status") or "Prospect",
                score=r.get("score") or 0,
                owner=r.get("owner") or "Puneet",
            )
            db.add(acc)
    db.commit()
    return {"accounts_created": created, "accounts_existing": skipped}, org_by_old_id


def migrate_products(db, sqlite_path: str) -> dict:
    rows = _sqlite_rows(sqlite_path, "products")
    created = 0
    product_by_old_id = {}
    for r in rows:
        name = r.get("name")
        if not name:
            continue
        p = db.query(models.Product).filter(models.Product.name == name).first()
        if not p:
            p = models.Product(
                name=name, category=r.get("category"), description=r.get("description"),
                key_benefits=r.get("key_benefits"),
            )
            db.add(p)
            db.flush()
            created += 1
        product_by_old_id[r["id"]] = p.id
    db.commit()
    return {"products_created": created}, product_by_old_id


def migrate_signals(db, sqlite_path: str, org_by_old_id: dict) -> dict:
    rows = _sqlite_rows(sqlite_path, "signals")
    created, skipped = 0, 0
    seen_urls = {r[0] for r in db.query(models.Signal.url).filter(models.Signal.url.isnot(None)).all()}
    for r in rows:
        url = r.get("url")
        if url and url in seen_urls:
            skipped += 1
            continue
        if url:
            seen_urls.add(url)
        s = models.Signal(
            org_id=org_by_old_id.get(r.get("account_id")),
            signal_type=r.get("signal_type"),
            source=r.get("source"),
            title=r.get("title"),
            summary=r.get("summary"),
            url=url,
            urgency=r.get("urgency") or "LOW",
            product_match=r.get("product_match"),
            is_read=bool(r.get("is_read")),
            is_actioned=bool(r.get("is_actioned")),
        )
        db.add(s)
        created += 1
    db.commit()
    return {"signals_created": created, "signals_skipped_dupe_url": skipped}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sqlite-path", required=True, help="Path to live decimal_abm/abm_engine.db")
    args = ap.parse_args()

    if not Path(args.sqlite_path).exists():
        print(f"ERROR: sqlite file not found: {args.sqlite_path}")
        sys.exit(1)

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        report = {}
        r1, org_map = migrate_accounts(db, args.sqlite_path)
        report.update(r1)
        r2, _ = migrate_products(db, args.sqlite_path)
        report.update(r2)
        r3 = migrate_signals(db, args.sqlite_path, org_map)
        report.update(r3)
        r4 = documented_contacts_seed.run(db)
        report["documented_contacts"] = r4

        db.add(models.AuditLog(action="etl_migration",
                                details=str(report), actor="migrate_from_decimal_abm.py",
                                timestamp=datetime.utcnow()))
        db.commit()

        print("\n=== Migration report ===")
        for k, v in report.items():
            print(f"  {k}: {v}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
