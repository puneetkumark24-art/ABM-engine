"""
rate_limit_dep.py — FastAPI rate-limit dependency (Gap-3).

Per-principal (or per-IP if unauthenticated) fixed-window limiter using the
cache backend (Redis in prod, in-memory fallback in dev). Returns 429 with a
Retry-After when exceeded. Attach to expensive routes:

    @router.post("/ai/generate", dependencies=[Depends(rate_limited("ai", 60, 60))])
"""
from __future__ import annotations
from fastapi import Depends, HTTPException, Request
from abm_platform.services import cache


def rate_limited(bucket: str, limit: int = 120, window_seconds: int = 60):
    def _dep(request: Request):
        # prefer the authenticated principal's tenant/sub; fall back to client IP
        from database import current_tenant_var
        who = current_tenant_var.get() or (request.client.host if request.client else "anon")
        key = f"{bucket}:{who}"
        allowed, remaining = cache.rate_limit(key, limit, window_seconds)
        if not allowed:
            raise HTTPException(status_code=429, detail="rate limit exceeded",
                                headers={"Retry-After": str(window_seconds)})
        return {"remaining": remaining}
    return _dep
