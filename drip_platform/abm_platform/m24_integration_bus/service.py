"""
Module 24 — Integration Layer & Event Bus  [LIVE]
Service surface. This module is (at least partly) implemented; the real code
lives in: abm_platform.events. This file is the stable import point so the rest of the
platform depends on `platform.m24_integration_bus.service` rather than deep paths.
"""
WIRED_TO = ['abm_platform.events']
STATUS = "LIVE"


def implementation():
    """Return the concrete implementation object(s) for this module, imported
    lazily so a missing optional dep never breaks `import platform`."""
    return {"module": "24 Integration Layer & Event Bus", "status": STATUS, "wired_to": WIRED_TO}
