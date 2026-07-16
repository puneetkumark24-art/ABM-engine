"""
drip_platform/sequences/send_window.py
────────────────────────────────────────
KSA send-window guard — ported from decimal_abm/abm_engine/workflow/send_window.py.

Build Artifact 3 (ABM business logic / build artifcat / ABM_BuildArtifact_3)
names this explicitly as a critical-path acceptance test:

    T-TIME-2  KSA blackout — "Send attempt Friday or during Ramadan blackout
              returns 403"

Every send path (scheduler tick + any manual "send now") should call
`is_within_send_window()` before dispatching and SKIP — not error — when it
returns False. Skipped sends stay due and go out on the next tick inside the
window.

KSA's weekend is Friday–Saturday. Business hours default to 08:00–18:00
Asia/Riyadh, Sunday–Thursday. All env-configurable so it can be tightened or
loosened without a code change.

Only difference from the decimal_abm original: uses the stdlib `logging`
module instead of `loguru` (loguru is not a DRIP dependency).
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, date
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger("drip.sequences.send_window")

# Python weekday(): Monday=0 ... Sunday=6. Default KSA weekend = Fri(4), Sat(5).
_DEFAULT_BLACKOUT_WEEKDAYS = {4, 5}


def _tz() -> ZoneInfo:
    return ZoneInfo(os.environ.get("SCHEDULER_TIMEZONE", "Asia/Riyadh"))


def _blackout_weekdays() -> set[int]:
    raw = os.environ.get("SEND_BLACKOUT_WEEKDAYS", "")
    if not raw.strip():
        return set(_DEFAULT_BLACKOUT_WEEKDAYS)
    try:
        return {int(x) for x in raw.split(",") if x.strip() != ""}
    except ValueError:
        logger.warning("SEND_BLACKOUT_WEEKDAYS=%r unparseable, using default Fri/Sat", raw)
        return set(_DEFAULT_BLACKOUT_WEEKDAYS)


def _business_hours() -> tuple[int, int]:
    start = int(os.environ.get("SEND_WINDOW_START_HOUR", 8))
    end = int(os.environ.get("SEND_WINDOW_END_HOUR", 18))
    return start, end


def _blackout_dates() -> set[date]:
    """
    Optional static blackout dates (Ramadan, Eid, National Day, ...) loaded from
    a JSON file of "YYYY-MM-DD" strings. If RAMADAN_BLACKOUT_DATES_FILE isn't set
    or doesn't exist, this is a no-op. File-based (not hardcoded) because Hijri
    holiday dates shift every Gregorian year and must not require a code change.
    """
    path = os.environ.get("RAMADAN_BLACKOUT_DATES_FILE", "")
    if not path or not Path(path).exists():
        return set()
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return {date.fromisoformat(d) for d in raw}
    except Exception as e:
        logger.warning("Could not load blackout dates from %s: %s", path, e)
        return set()


def is_within_send_window(now: Optional[datetime] = None) -> tuple[bool, str]:
    """
    Returns (allowed, reason). `reason` is always populated, even when
    allowed=True (useful for logging what window matched).
    """
    now_local = (now or datetime.now(tz=_tz())).astimezone(_tz())

    if now_local.date() in _blackout_dates():
        return False, f"blackout date {now_local.date().isoformat()}"

    if now_local.weekday() in _blackout_weekdays():
        return False, f"KSA weekend (weekday={now_local.weekday()})"

    start_hour, end_hour = _business_hours()
    if not (start_hour <= now_local.hour < end_hour):
        return False, f"outside business hours ({start_hour:02d}:00-{end_hour:02d}:00 {now_local.tzinfo})"

    return True, f"within window ({now_local.strftime('%a %H:%M')} {now_local.tzinfo})"
