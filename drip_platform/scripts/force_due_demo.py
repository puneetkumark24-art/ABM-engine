"""force_due_demo.py -- ONE-OFF VERIFICATION ONLY.

run_full_pipeline_demo.py correctly showed `due: 0` on the freshly-enrolled
test person -- sequence steps and decision-engine touches carry a built-in
wait period by design (nobody gets touched the instant they're enrolled).

This script proves the draft-generation half of the pipeline actually works,
without waiting hours/days for that wait period to elapse on its own: it
finds the most recent ACTIVE enrollment (the one run_full_pipeline_demo.py
just created), forces next_run_at into the past for THIS ONE TEST ROW ONLY,
then runs one real orchestrator tick.

Same safety guarantees as every other script in this integration:
  - delivery is hardcoded dry_run -- nothing is ever actually sent
  - c-suite contacts are still always held for human approval
  - this only rewrites next_run_at on one already-enrolled row; it creates no
    new enrollments, exports no new signals, sends nothing for real

Run:
    python scripts/force_due_demo.py
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
from datetime import datetime, timedelta

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from database import SessionLocal  # noqa: E402
import models  # noqa: E402
from abm_platform.services import orchestrator  # noqa: E402


def main() -> None:
    db = SessionLocal()
    try:
        enr = (db.query(models.SequenceEnrollment)
               .filter_by(status="ACTIVE")
               .order_by(models.SequenceEnrollment.enrolled_at.desc())
               .first())
        if enr is None:
            print(json.dumps({"error": "no ACTIVE enrollment found -- run run_full_pipeline_demo.py first"}))
            return

        person = db.get(models.Person, enr.person_id)
        print(f"Forcing next_run_at to the past for enrollment {enr.id} "
              f"(person: {person.full_name if person else enr.person_id})")
        enr.next_run_at = datetime.utcnow() - timedelta(minutes=1)
        db.commit()

        # respect_send_window=False: same intent as --force in
        # run_full_pipeline_demo.py, bypassing only the KSA business-hours
        # gate for this one verification tick -- not a compliance bypass.
        tick = orchestrator.run_tick(db, limit=10, respect_send_window=False)
        print(json.dumps(tick, indent=2, ensure_ascii=False))

        # Draft.id is a random uuid4() (see models.uid()), NOT time-sortable --
        # ordering by id.desc() returns an essentially random row, not the
        # newest one. Must order by created_at instead.
        draft = (db.query(models.Draft).filter_by(person_id=enr.person_id)
                .order_by(models.Draft.created_at.desc()).first())
        if draft:
            print(f"\n--- DRAFT (status: {draft.status}) ---")
            print(f"Subject: {draft.subject}")
            print(draft.body)
        else:
            print("\nNo draft record created -- check qc_failed/held_for_human counts above.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
