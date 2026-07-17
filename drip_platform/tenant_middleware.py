"""
tenant_middleware.py — request-scoped tenant context (P0-A.2).

Extracts + verifies the JWT on each request and stashes the tenant_id in a
contextvar that `database.get_db` reads to set the RLS GUC — so **every route
using Depends(get_db) becomes tenant-scoped without editing any route**.

- Public paths (tracking pixels/redirects, landing pages, health, docs) are
  exempt — they must work unauthenticated.
- Enforcement is env-gated: AUTH_ENFORCED=true → missing/invalid token on a
  protected path = 401. Default false so dev/tests (which call services directly
  or hit endpoints without tokens) keep working; a token, if present, is still
  honored for tenancy.
"""
from __future__ import annotations
import os
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from database import current_tenant_var
from auth import verify_token

PUBLIC_PREFIXES = ("/t/", "/p/", "/health", "/docs", "/openapi.json", "/redoc")
AUTH_ENFORCED = os.environ.get("AUTH_ENFORCED", "false").lower() == "true"


def _is_public(path: str) -> bool:
    return any(path == p or path.startswith(p) for p in PUBLIC_PREFIXES)


class TenantMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path
        token_tenant = None
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            try:
                payload = verify_token(auth.split(" ", 1)[1].strip())
                token_tenant = payload.get("tenant_id")
            except Exception:
                token_tenant = None
                if AUTH_ENFORCED and not _is_public(path):
                    return JSONResponse({"detail": "invalid token"}, status_code=401)
        if AUTH_ENFORCED and not _is_public(path) and not token_tenant:
            return JSONResponse({"detail": "authentication required"}, status_code=401)

        reset = current_tenant_var.set(token_tenant)
        try:
            return await call_next(request)
        finally:
            current_tenant_var.reset(reset)
