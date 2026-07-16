"""
Module 23 — API Gateway  [PARTIAL]
Service surface. This module is (at least partly) implemented; the real code
lives in: main.app (FastAPI surface). This file is the stable import point so the rest of the
platform depends on `platform.m23_api_gateway.service` rather than deep paths.
"""
WIRED_TO = ['main.app (FastAPI surface)']
STATUS = "PARTIAL"


def implementation():
    """Return the concrete implementation object(s) for this module, imported
    lazily so a missing optional dep never breaks `import platform`."""
    return {"module": "23 API Gateway", "status": STATUS, "wired_to": WIRED_TO}
