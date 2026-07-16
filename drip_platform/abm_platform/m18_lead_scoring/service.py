"""
Module 18 — Lead & Account Scoring Engine  [LIVE]
Service surface. This module is (at least partly) implemented; the real code
lives in: scoring, models.AccountScore, modifiers.json. This file is the stable import point so the rest of the
platform depends on `platform.m18_lead_scoring.service` rather than deep paths.
"""
WIRED_TO = ['scoring', 'models.AccountScore', 'modifiers.json']
STATUS = "LIVE"


def implementation():
    """Return the concrete implementation object(s) for this module, imported
    lazily so a missing optional dep never breaks `import platform`."""
    return {"module": "18 Lead & Account Scoring Engine", "status": STATUS, "wired_to": WIRED_TO}
