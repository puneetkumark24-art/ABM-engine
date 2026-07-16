"""
Module 08 — Journey / Sequence Engine  [LIVE]
Service surface. This module is (at least partly) implemented; the real code
lives in: sequences.engine, sequences.send_window. This file is the stable import point so the rest of the
platform depends on `platform.m08_journey.service` rather than deep paths.
"""
WIRED_TO = ['sequences.engine', 'sequences.send_window']
STATUS = "LIVE"


def implementation():
    """Return the concrete implementation object(s) for this module, imported
    lazily so a missing optional dep never breaks `import platform`."""
    return {"module": "08 Journey / Sequence Engine", "status": STATUS, "wired_to": WIRED_TO}
