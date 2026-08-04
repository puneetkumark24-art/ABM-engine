from __future__ import annotations

import argparse
import json

from .bridge import SignalBridge


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Safely export eligible signal-v2 records into DRIP Intelligence")
    parser.add_argument("--signal-db", required=True)
    parser.add_argument("--drip-db", required=True)
    parser.add_argument("--apply", action="store_true", help="write exports; omit for read-only preview")
    args = parser.parse_args(argv)
    bridge = SignalBridge(args.signal_db, args.drip_db)
    if args.apply:
        result = bridge.export_scoring_eligible()
    else:
        candidates = bridge.preview()
        result = {"preview": True, "eligible": len(candidates), "signals": [r["id"] for r in candidates]}
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
