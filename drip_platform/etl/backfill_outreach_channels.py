"""
backfill_outreach_channels.py — one-off recovery script.

Normally the outreach_channels backfill (moving old outreach_connection_sent/accepted/
messaged/response_notes data into a proper 'linkedin' row) runs as part of the
0b37c89cd6e1 migration. If that migration failed with "relation outreach_channels
already exists" (because the dashboard's auto-create-tables-on-startup beat the
migration to it), the schema is fine but this backfill never ran. This script does
the same backfill directly via the ORM, and is safe to re-run — it skips any person
who already has a 'linkedin' row.

Usage:
    python etl/backfill_outreach_channels.py
"""
from __future__ import annotations
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))
from database import SessionLocal
import models


def main():
    db = SessionLocal()
    try:
        candidates = db.query(models.Person).filter(
            (models.Person.outreach_connection_sent == True) |  # noqa: E712
            (models.Person.outreach_messaged == True) |  # noqa: E712
            (models.Person.outreach_response_notes.isnot(None))
        ).all()

        created, skipped = 0, 0
        for p in candidates:
            existing = db.query(models.OutreachChannel).filter(
                models.OutreachChannel.person_id == p.id,
                models.OutreachChannel.channel == "linkedin").first()
            if existing:
                skipped += 1
                continue

            stage_parts = []
            if p.outreach_connection_sent:
                stage_parts.append("Connection request sent")
            if p.outreach_connection_accepted:
                stage_parts.append("accepted")
            if p.outreach_messaged:
                stage_parts.append("messaged")

            db.add(models.OutreachChannel(
                person_id=p.id, channel="linkedin",
                stage=" · ".join(stage_parts) if stage_parts else None,
                notes=p.outreach_response_notes,
                next_step=p.next_step,
                updated_by=p.outreach_updated_by,
                updated_at=p.outreach_updated_at or datetime.utcnow(),
            ))
            created += 1

        db.commit()
        print(f"Backfill complete. Created {created} linkedin channel row(s), skipped {skipped} (already had one).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
