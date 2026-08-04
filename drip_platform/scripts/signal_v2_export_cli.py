"""signal_v2_export_cli.py -- one-way, human-triggered export from the
isolated signal_engine shadow database into DRIP's real Signal table.

Adapted from drip_integration/abm_engine/signal_integration/export_cli.py.
Same two modes as the original:

  Preview (default, read-only, changes nothing):
      python scripts/signal_v2_export_cli.py --signal-db signal_engine.db

  Apply (writes into Postgres `signals` + the signal_v2_exports ledger):
      python scripts/signal_v2_export_cli.py --signal-db signal_engine.db --apply

Requires DATABASE_URL to be set (or picked up from drip_platform/.env, same
as the main app) so it writes into the SAME Postgres database the running
DRIP OS reads from -- not a separate copy.
"""
from __future__ import annotations
import argparse
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)


def main(argv=None) -> int:
    from signal_engine.cli import DEFAULT_DB as _SE_DEFAULT_DB

    parser = argparse.ArgumentParser(description="Safely export eligible signal_engine records into DRIP")
    # Must match signal_engine.cli's own default (work/signal_engine.db) -- that
    # is where `python -m signal_engine.cli ...` (and the autonomous scheduled
    # pipeline, which never passes --db) actually writes captured data. A prior
    # version of this default pointed at a separate, stale root-level file.
    parser.add_argument("--signal-db", default=str(_SE_DEFAULT_DB))
    parser.add_argument("--apply", action="store_true", help="write exports; omit for read-only preview")
    args = parser.parse_args(argv)

    from database import SessionLocal
    from abm_platform.services import signal_v2_bridge as bridge

    db = SessionLocal()
    try:
        if args.apply:
            result = bridge.export_scoring_eligible(db, args.signal_db)
        else:
            candidates = bridge.preview(db, args.signal_db)
            blocked = [r for r in candidates if "_export_blocked_reason" in r]
            ready = [r for r in candidates if "_export_blocked_reason" not in r]
            result = {
                "preview": True,
                "eligible_total": len(candidates),
                "ready_to_export": len(ready),
                "blocked_pending_mapping": [
                    {"signal_uuid": r["id"], "account": r.get("canonical_name"), "reason": r["_export_blocked_reason"]}
                    for r in blocked
                ],
                "signal_ids_ready": [r["id"] for r in ready],
            }
    finally:
        db.close()

    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
