"""
routers/auth_login.py — U1-deploy: a minimal login endpoint so the platform can
run publicly with AUTH_ENFORCED=true.

POST /auth/login {email, password} → JWT (scopes per role). Users come from
env for phase-1 deployment (ADMIN_EMAIL/ADMIN_PASSWORD, optional VIEWER_*);
replace with the app_users table + IdP SSO in Sprint 9-02. The password check
is constant-time. Refuses to run with the default password in enforced mode.
"""
from __future__ import annotations
import hmac
import os

import time

from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Request

from auth import issue_token

router = APIRouter(tags=["auth"])

# ── brute-force protection (audit risk closure) ──────────────
# Sliding window: max 5 failed attempts per (ip, email) per 5 minutes.
_ATTEMPTS: dict[str, list[float]] = {}
_WINDOW_S = 300
_MAX_FAILS = 5


def _throttled(key: str) -> bool:
    now = time.time()
    hits = [t for t in _ATTEMPTS.get(key, []) if now - t < _WINDOW_S]
    _ATTEMPTS[key] = hits
    return len(hits) >= _MAX_FAILS


def _record_fail(key: str) -> None:
    _ATTEMPTS.setdefault(key, []).append(time.time())


class LoginReq(BaseModel):
    email: str
    password: str


def _env_users() -> dict:
    users = {}
    admin_email = os.environ.get("ADMIN_EMAIL", "admin@drip.local")
    admin_pw = os.environ.get("ADMIN_PASSWORD", "")
    if admin_pw:
        users[admin_email.lower()] = (admin_pw, ["*"], "admin")
    viewer_email = os.environ.get("VIEWER_EMAIL")
    viewer_pw = os.environ.get("VIEWER_PASSWORD")
    if viewer_email and viewer_pw:
        users[viewer_email.lower()] = (viewer_pw, ["crm.read", "abm.read"], "viewer")
    return users


@router.post("/auth/login")
def login(req: LoginReq, request: Request = None):
    users = _env_users()
    if not users:
        raise HTTPException(status_code=503,
                            detail="login not configured: set ADMIN_EMAIL + ADMIN_PASSWORD")
    ip = request.client.host if request and request.client else "?"
    key = f"{ip}|{req.email.strip().lower()}"
    if _throttled(key):
        raise HTTPException(status_code=429,
                            detail="too many failed attempts; try again in 5 minutes")
    entry = users.get(req.email.strip().lower())
    if entry is None or not hmac.compare_digest(entry[0], req.password):
        _record_fail(key)
        raise HTTPException(status_code=401, detail="invalid credentials")
    password, scopes, role = entry
    tenant_id = os.environ.get("DEFAULT_TENANT_ID", "00000000-0000-0000-0000-000000000001")
    token = issue_token(sub=req.email.strip().lower(), tenant_id=tenant_id,
                        roles=[role], scopes=scopes, ttl_seconds=12 * 3600)
    return {"access_token": token, "token_type": "bearer", "role": role,
            "expires_in": 12 * 3600}
