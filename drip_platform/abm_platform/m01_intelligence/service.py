"""
Module 01 — Intelligence Engine  [PARTIAL]
Service surface. This module is (at least partly) implemented; the real code
lives in: scoring, etl.signal_intel. This file is the stable import point so the rest of the
platform depends on `platform.m01_intelligence.service` rather than deep paths.
"""
WIRED_TO = ['scoring', 'etl.signal_intel']
STATUS = "PARTIAL"


def implementation():
    """Return the concrete implementation object(s) for this module, imported
    lazily so a missing optional dep never breaks `import platform`."""
    return {"module": "01 Intelligence Engine", "status": STATUS, "wired_to": WIRED_TO}
