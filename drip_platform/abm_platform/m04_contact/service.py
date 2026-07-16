"""
Module 04 — Contact Intelligence Engine  [PARTIAL]
Service surface. This module is (at least partly) implemented; the real code
lives in: models.Person, routers.persons. This file is the stable import point so the rest of the
platform depends on `platform.m04_contact.service` rather than deep paths.
"""
WIRED_TO = ['models.Person', 'routers.persons']
STATUS = "PARTIAL"


def implementation():
    """Return the concrete implementation object(s) for this module, imported
    lazily so a missing optional dep never breaks `import platform`."""
    return {"module": "04 Contact Intelligence Engine", "status": STATUS, "wired_to": WIRED_TO}
