"""Module 14 — Asset Library: versioned collateral, HMAC-signed expiring links
for gated assets, usage/download tracking.
AST-001: gated assets are only reachable via a valid signed link."""
from __future__ import annotations
import hashlib
import hmac as hmac_mod
import os
import time
from datetime import datetime
from sqlalchemy.orm import Session
import models_ext as mx

_SECRET = os.environ.get("ASSET_LINK_SECRET", "drip-dev-secret-change-me").encode()


def register(db: Session, name: str, asset_type: str = "pdf", storage_url: str = "",
             gated: bool = False, tags: list[str] | None = None) -> mx.Asset:
    """New upload of an existing name auto-increments version (AST-002)."""
    latest = (db.query(mx.Asset).filter_by(name=name)
              .order_by(mx.Asset.version.desc()).first())
    version = (latest.version + 1) if latest else 1
    a = mx.Asset(name=name, asset_type=asset_type, storage_url=storage_url,
                 gated=gated, tags=tags or [], version=version)
    db.add(a); db.commit()
    return a


def sign_link(asset_id: str, ttl_seconds: int = 3600) -> str:
    """HMAC-signed expiring token: '<asset_id>.<expiry>.<sig>'."""
    exp = int(time.time()) + ttl_seconds
    payload = f"{asset_id}.{exp}".encode()
    sig = hmac_mod.new(_SECRET, payload, hashlib.sha256).hexdigest()[:32]
    return f"{asset_id}.{exp}.{sig}"


def verify_link(token: str) -> tuple[bool, str]:
    try:
        asset_id, exp_s, sig = token.rsplit(".", 2)
        exp = int(exp_s)
    except ValueError:
        return False, "malformed"
    expected = hmac_mod.new(_SECRET, f"{asset_id}.{exp}".encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac_mod.compare_digest(sig, expected):
        return False, "bad_signature"
    if time.time() > exp:
        return False, "expired"
    return True, asset_id


def download(db: Session, token: str, context_type: str = "landing",
             context_id: str | None = None) -> tuple[mx.Asset | None, str]:
    """Serve a gated asset only via a valid signed link; track usage."""
    ok, result = verify_link(token)
    if not ok:
        return None, result
    asset = db.get(mx.Asset, result)
    if asset is None:
        return None, "not_found"
    usage = (db.query(mx.AssetUsage)
             .filter_by(asset_id=asset.id, context_type=context_type, context_id=context_id)
             .first())
    if usage is None:
        usage = mx.AssetUsage(asset_id=asset.id, context_type=context_type, context_id=context_id)
        db.add(usage)
    usage.downloads = (usage.downloads or 0) + 1
    usage.last_used_at = datetime.utcnow()
    db.commit()
    return asset, "ok"


def usage_report(db: Session, asset_id: str) -> dict:
    rows = db.query(mx.AssetUsage).filter_by(asset_id=asset_id).all()
    return {"contexts": len(rows), "total_downloads": sum(r.downloads or 0 for r in rows)}
