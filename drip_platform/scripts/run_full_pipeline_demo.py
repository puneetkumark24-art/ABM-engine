"""run_full_pipeline_demo.py -- runs the ENTIRE chain end-to-end, once, against
your real Postgres database, and prints exactly what happened at each step:

  1. Export any scoring-eligible shadow signals (signal_engine.db) into the
     real `signals` table (abm_platform.services.signal_v2_bridge) -- the one
     human-triggered step in the whole pipeline, run here explicitly because
     you asked to see the full chain, not because it's now automatic.
  2. Pick the most recent real Signal and its Organization.
  3. Find a real Person at that organization ("associate account and
     individual to that signal") -- if none exists, this stops and tells you
     so plainly. It will NOT invent a fake contact.
  4. Enroll that person into the default outreach sequence
     (sequences.engine.enroll_person) -- compliance-gated (do-not-contact /
     consent / suppression all still apply).
  5. Run the AI Decision Engine (abm_platform.services.decision.decide) --
     shows the live reasoning, including the signal that drove it.
  6. Run one orchestrator tick (abm_platform.services.orchestrator.run_tick)
     -- due -> AI draft -> QC -> c-suite human-hold or auto-approve ->
     dry-run "send" -> sequence advance -> engagement rollup -> re-tier.

Safety, unchanged from every other script in this integration:
  - Delivery is hardcoded dry_run inside orchestrator.py -- nothing is ever
    actually sent, regardless of what this script does.
  - c-suite contacts are always held for human approval, never auto-sent.
  - SendGrid is never touched.

Run:
    python scripts/run_full_pipeline_demo.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from database import SessionLocal  # noqa: E402
import models  # noqa: E402
from abm_platform.services import signal_v2_bridge as bridge  # noqa: E402
from sequences import engine as seq_engine  # noqa: E402
from abm_platform.services import decision, orchestrator  # noqa: E402


def _signal_db_path() -> str:
    # Must match signal_engine.cli.DEFAULT_DB (work/signal_engine.db) -- the
    # file the autonomous scheduled pipeline actually writes to. See
    # routers/signal_review.py for the full explanation.
    import os
    from signal_engine.cli import DEFAULT_DB
    return os.environ.get("SIGNAL_V2_DB", str(DEFAULT_DB))


def main() -> None:
    report: dict = {}
    db = SessionLocal()
    try:
        # 1. Export shadow -> real signals
        print("[1/6] Exporting scoring-eligible shadow signals into real `signals`...")
        export_result = bridge.export_scoring_eligible(db, _signal_db_path())
        report["export"] = export_result
        print(json.dumps(export_result, indent=2, ensure_ascii=False))

        # 2. Most recent real signal + its org
        print("\n[2/6] Finding the most recent real signal...")
        sig = (db.query(models.Signal).filter(models.Signal.org_id.isnot(None))
               .order_by(models.Signal.created_at.desc()).first())
        if sig is None:
            report["stopped_at"] = "no real signals exist yet (none exported and none pre-existing)"
            print(json.dumps(report, indent=2, ensure_ascii=False)); return
        org = db.get(models.Organization, sig.org_id)
        report["signal"] = {"id": sig.id, "title": sig.title, "urgency": sig.urgency,
                            "source": sig.source, "org_id": sig.org_id,
                            "org_name": org.canonical_name if org else None}
        print(json.dumps(report["signal"], indent=2, ensure_ascii=False))

        # 3. A real person at that org -- never fabricated
        print("\n[3/6] Looking for a real contact at this organization...")
        person = (db.query(models.Person)
                  .filter(models.Person.current_org_id == sig.org_id)
                  .order_by(models.Person.decision_weight.desc().nullslast()).first())
        if person is None:
            report["stopped_at"] = (
                f"signal exported/found for '{org.canonical_name if org else sig.org_id}', "
                "but no contact exists for this organization in `persons` yet -- "
                "add one before the pipeline has anyone to enroll or draft for. "
                "Nothing invented.")
            print(json.dumps(report, indent=2, ensure_ascii=False)); return
        report["person"] = {"id": person.id, "name": person.full_name,
                            "title": person.current_title, "seniority": person.seniority_level,
                            "email": person.primary_email}
        print(json.dumps(report["person"], indent=2, ensure_ascii=False))

        # 4. Enroll
        print("\n[4/6] Enrolling this person into the default sequence...")
        enr, enroll_status = seq_engine.enroll_person(db, person.id)
        report["enrollment"] = {"status": enroll_status,
                                "enrollment_id": enr.id if enr else None}
        print(json.dumps(report["enrollment"], indent=2, ensure_ascii=False))

        # 5. Decision engine (shows the signal feeding the reasoning)
        print("\n[5/6] Running the AI Decision Engine...")
        dec = decision.decide(db, person.id)
        report["decision"] = {"action": dec.action, "channel": dec.channel,
                              "confidence": dec.confidence, "reasons": dec.reasons}
        print(json.dumps(report["decision"], indent=2, ensure_ascii=False))

        # 6. One orchestrator tick -- draft, QC, hold/approve, dry-run send, rescore
        force = "--force" in sys.argv
        print("\n[6/6] Running one orchestrator tick (draft -> QC -> dry-run send -> rescore)...")
        if force:
            print("      (--force: bypassing the KSA business-hours send-window gate for this test run only)")
        tick = orchestrator.run_tick(db, limit=10, respect_send_window=not force)
        report["tick"] = tick
        print(json.dumps(tick, indent=2, ensure_ascii=False))

        # Show the actual draft text that was generated, if any
        # Draft.id is a random uuid4() (see models.uid()), NOT time-sortable --
        # ordering by id.desc() returns an essentially random row, not the
        # newest one. Must order by created_at instead.
        draft = (db.query(models.Draft).filter_by(person_id=person.id)
                .order_by(models.Draft.created_at.desc()).first())
        if draft:
            report["draft_preview"] = {"status": draft.status, "subject": draft.subject,
                                       "body": draft.body}
            print("\n--- DRAFT (status: %s) ---\n%s" % (draft.status, draft.body))

    finally:
        db.close()

    print("\n=== FULL REPORT ===")
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
