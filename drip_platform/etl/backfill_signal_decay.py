"""
backfill_signal_decay.py — Signal Pipeline P1, one-off backfill.

Every Signal row created before this pass has confidence_score/decay_category/
decay_expires_at/source_reliability = NULL (the migration that added those
columns is purely additive). New signals get stamped automatically at save
time (dashboard/app.py's signal_new/signal_edit now call
etl.signal_decay.stamp_signal_intelligence). This script does the same stamp
for everything that already existed before that wiring went in.

Safe to re-run: only touches rows where decay_category IS NULL, so it never
overwrites a stamp that a later, smarter Intelligence layer (P2+) may have
set with better information.

Usage:
    python etl/backfill_signal_decay.py
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from database import SessionLocal
import models
from etl.signal_decay import stamp_signal_intelligence


def main():
    db = SessionLocal()
    try:
        candidates = db.query(models.Signal).filter(models.Signal.decay_category.is_(None)).all()

        by_category = {}
        for sig in candidates:
            stamp_signal_intelligence(sig)
            by_category[sig.decay_category] = by_category.get(sig.decay_category, 0) + 1

        db.commit()

        total = len(candidates)
        print(f"Backfill complete. Stamped {total} signal(s) with confidence_score + decay_category + decay_expires_at.")
        if by_category:
            print("By decay category:")
            for cat, n in sorted(by_category.items()):
                print(f"  {cat}: {n}")
        already_stamped = db.query(models.Signal).filter(models.Signal.decay_category.isnot(None)).count()
        print(f"Already-stamped rows left untouched: {already_stamped - total if already_stamped >= total else 0}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
