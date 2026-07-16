"""
Module 02 — Signal Detection Engine  [LIVE]
Service surface. This module is (at least partly) implemented; the real code
lives in: etl.signal_decay, etl.signal_intel, models.Signal. This file is the stable import point so the rest of the
platform depends on `platform.m02_signal_detection.service` rather than deep paths.
"""
WIRED_TO = ['etl.signal_decay', 'etl.signal_intel', 'models.Signal']
STATUS = "LIVE"


def implementation():
    """Return the concrete implementation object(s) for this module, imported
    lazily so a missing optional dep never breaks `import platform`."""
    return {"module": "02 Signal Detection Engine", "status": STATUS, "wired_to": WIRED_TO}
