"""
tenant_middleware.py — request-scoped tenancy + route-level authorization
(Sprint 1, S1-01 + P0-A.2).

Per request it:
  1. verifies the JWT (if present) and extracts tenant_id + scopes,
  2. enforces a per-path-prefix SCOPE_POLICY (route-level authorization — the
     audit's 0-routers-enforce-auth finding), and
  3. stashes tenant_id in a contextvar so database.get_db scopes the session
     (RLS) — every route becomes tenant-scoped without editing routes.

Enforcement is gated by AUTH_ENFORCED (default off for dev/tests). Public paths
(tracking pixels/redirects, landing pages, health, metrics, docs) are always
exempt. A protected path with no matching policy entry requires a valid token
but no specific scope.
"""
from __future__ import annotations
import os
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from database import current_tenant_var
from auth import verify_token, Principal

PUBLIC_PREFIXES = ("/t/", "/p/", "/health", "/metrics", "/docs", "/openapi.json", "/redoc",
                   "/auth/login")
# Exact-match public pages (NOT prefixes — "/" as a prefix would open everything):
# the portal and console are static shells; every API call they make is still
# individually authorized.
PUBLIC_EXACT = ("/", "/app", "/legacy", "/legacy-portal")

# Route-level authorization: (path prefix, required scope). Longest match wins.
# Scopes use wildcards (crm.* grants crm.read). Extend as routers are added.
SCOPE_POLICY = [
    ("/crm", "crm.read"),
    ("/px/rules", "rules.manage"),
    ("/px/ai", "ai.generate"),
    ("/px/linkedin", "linkedin.manage"),
    ("/engine/tick", "engine.run"),
    ("/engine/merge", "crm.merge"),
    ("/decide", "ai.decide"),
    ("/sequences", "sequences.manage"),
    ("/mkt", "marketing.manage"),
    ("/admin", "admin.full"),
]


def _is_public(path: str) -> bool:
    if path in PUBLIC_EXACT:
        return True
    return any(path == p or path.startswith(p) for p in PUBLIC_PREFIXES)


def _required_scope(path: str) -> str | None:
    match = None
    for prefix, scope in SCOPE_POLICY:
        if path.startswith(prefix) and (match is None or len(prefix) > len(match[0])):
            match = (prefix, scope)
    return match[1] if match else None


def _enforced() -> bool:
    return os.environ.get("AUTH_ENFORCED", "false").lower() == "true"


class TenantMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path
        principal: Principal | None = None
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            try:
                principal = Principal(verify_token(auth.split(" ", 1)[1].strip()))
            except Exception:
                principal = None
                if _enforced() and not _is_public(path):
                    return JSONResponse({"detail": "invalid token"}, status_code=401)

        if _enforced() and not _is_public(path):
            if principal is None:
                return JSONResponse({"detail": "authentication required"}, status_code=401)
            scope = _required_scope(path)
            if scope and not principal.has_scope(scope):
                return JSONResponse({"detail": f"missing scope: {scope}"}, status_code=403)

        token_tenant = principal.tenant_id if principal else None
        reset = current_tenant_var.set(token_tenant)
        try:
            return await call_next(request)
        finally:
            current_tenant_var.reset(reset)
