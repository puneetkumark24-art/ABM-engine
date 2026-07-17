"""
auth.py — authentication & authorization (P0-A, BOMB 2 fix).

Self-contained HS256 JWT (stdlib only — no new dependency) plus FastAPI
dependencies that (1) require a valid token, (2) extract the tenant_id and
scopes, and (3) enforce per-route scopes. Tokens carry: sub (user id),
tenant_id, roles, scopes, exp.

In production the signing/verification moves to an OIDC provider (Keycloak/
Cognito/Auth0) behind the gateway; this module is the enforcement point inside
the app and the interface stays identical.

Secret comes from JWT_SECRET (env) — in production a rotated key from the
secrets manager, NOT a checked-in default.
"""
from __future__ import annotations
import base64
import hashlib
import hmac
import json
import os
import time
from typing import Optional
from fastapi import Depends, Header, HTTPException
from tenancy import get_tenant_db  # noqa: F401  (re-exported for convenience)

_SECRET = os.environ.get("JWT_SECRET", "drip-dev-jwt-secret-change-me")
_ALG = "HS256"


def _b64u(b: bytes) -> bytes:
    return base64.urlsafe_b64encode(b).rstrip(b"=")


def _b64u_dec(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def issue_token(sub: str, tenant_id: str, roles: list[str] | None = None,
                scopes: list[str] | None = None, ttl_seconds: int = 3600,
                secret: str | None = None) -> str:
    secret = secret or _SECRET
    header = {"alg": _ALG, "typ": "JWT"}
    payload = {"sub": sub, "tenant_id": tenant_id, "roles": roles or [],
               "scopes": scopes or [], "iat": int(time.time()),
               "exp": int(time.time()) + ttl_seconds}
    seg = _b64u(json.dumps(header, separators=(",", ":")).encode()) + b"." + \
        _b64u(json.dumps(payload, separators=(",", ":")).encode())
    sig = hmac.new(secret.encode(), seg, hashlib.sha256).digest()
    return (seg + b"." + _b64u(sig)).decode()


def verify_token(token: str, secret: str | None = None) -> dict:
    secret = secret or _SECRET
    try:
        header_b64, payload_b64, sig_b64 = token.split(".")
    except ValueError:
        raise HTTPException(status_code=401, detail="malformed token")
    seg = f"{header_b64}.{payload_b64}".encode()
    expected = hmac.new(secret.encode(), seg, hashlib.sha256).digest()
    if not hmac.compare_digest(_b64u_dec(sig_b64), expected):
        raise HTTPException(status_code=401, detail="bad signature")
    payload = json.loads(_b64u_dec(payload_b64))
    if payload.get("exp", 0) < time.time():
        raise HTTPException(status_code=401, detail="token expired")
    if not payload.get("tenant_id"):
        raise HTTPException(status_code=401, detail="token missing tenant")
    return payload


class Principal:
    def __init__(self, payload: dict):
        self.sub = payload["sub"]
        self.tenant_id = payload["tenant_id"]
        self.roles = payload.get("roles", [])
        self.scopes = set(payload.get("scopes", []))

    def has_scope(self, scope: str) -> bool:
        if "*" in self.scopes:
            return True
        if scope in self.scopes:
            return True
        # wildcard prefix e.g. "crm.*" grants "crm.read"
        return any(s.endswith(".*") and scope.startswith(s[:-1]) for s in self.scopes)


# ── FastAPI dependencies ─────────────────────────────────────
def current_principal(authorization: Optional[str] = Header(None)) -> Principal:
    """Require a valid Bearer token; return the Principal."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    return Principal(verify_token(token))


def require_scope(scope: str):
    """Route dependency factory enforcing a scope."""
    def _dep(principal: Principal = Depends(current_principal)) -> Principal:
        if not principal.has_scope(scope):
            raise HTTPException(status_code=403, detail=f"missing scope: {scope}")
        return principal
    return _dep


def tenant_db_for(principal: Principal = Depends(current_principal)):
    """Tenant-scoped DB session bound to the authenticated principal's tenant.
    This is the dependency real routes should use: auth + tenancy in one."""
    from tenancy import SessionLocal, set_tenant
    db = SessionLocal()
    try:
        set_tenant(db, principal.tenant_id)
        yield db
    finally:
        db.close()
