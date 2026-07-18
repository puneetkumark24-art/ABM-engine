"""routers/developer_platform.py — Sprint 8: API keys + webhook subscription
management. Mounted under /dev; add ('/dev','admin.full') to SCOPE_POLICY when
enforcing (key issuance is an admin action)."""
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from abm_platform.services import developer_platform as dp

router = APIRouter(prefix="/dev", tags=["developer-platform"])


class ApiKeyReq(BaseModel):
    name: str
    scopes: list[str] = []


@router.post("/api-keys", status_code=201)
def create_api_key(req: ApiKeyReq, db: Session = Depends(get_db)):
    # api_key is returned exactly once
    return dp.create_api_key(db, req.name, req.scopes)


@router.get("/api-keys")
def list_api_keys(db: Session = Depends(get_db)):
    import models_s8 as m8
    return [{"id": k.id, "name": k.name, "prefix": k.prefix, "active": k.active,
             "scopes": k.scopes, "last_used_at": k.last_used_at}
            for k in db.query(m8.ApiKey).all()]


@router.delete("/api-keys/{key_id}")
def revoke(key_id: str, db: Session = Depends(get_db)):
    if not dp.revoke_api_key(db, key_id):
        raise HTTPException(status_code=404, detail="api key not found")
    return {"revoked": True, "id": key_id}


class SubReq(BaseModel):
    url: str
    event_types: list[str] = []
    secret: Optional[str] = None


@router.post("/webhooks", status_code=201)
def create_subscription(req: SubReq, db: Session = Depends(get_db)):
    sub = dp.create_subscription(db, req.url, req.event_types, req.secret)
    return {"id": sub.id, "url": sub.url, "event_types": sub.event_types,
            "secret": sub.secret}


@router.get("/webhooks/{subscription_id}/deliveries")
def deliveries(subscription_id: str, db: Session = Depends(get_db)):
    import models_s8 as m8
    rows = db.query(m8.WebhookDelivery).filter_by(subscription_id=subscription_id).all()
    return [{"id": d.id, "event_type": d.event_type, "status": d.status,
             "attempts": d.attempts, "response_code": d.response_code} for d in rows]
