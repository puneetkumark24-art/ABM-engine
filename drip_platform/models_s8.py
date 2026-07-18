"""
models_s8.py — Sprint 8 (Developer Platform): API keys + outbound webhooks.

Three additive tables:
  api_keys              — hashed programmatic credentials (plaintext shown once).
  webhook_subscriptions — tenant-registered endpoints + signing secret + filter.
  webhook_deliveries    — durable outbound delivery attempts (signed, retried,
                          dead-lettered), mirroring the Sprint-6 durability model.
"""
from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Integer, JSON, Boolean, Text, Index
from database import Base


def _id() -> str:
    return str(uuid.uuid4())


class ApiKey(Base):
    __tablename__ = "api_keys"
    id = Column(String(36), primary_key=True, default=_id)
    tenant_id = Column(String(36), index=True)
    name = Column(String(120), nullable=False)
    prefix = Column(String(12), index=True)          # visible id, e.g. dk_ab12cd
    key_hash = Column(String(64), nullable=False, index=True)  # sha256(secret)
    scopes = Column(JSON, default=list)
    active = Column(Boolean, default=True)
    last_used_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)


class WebhookSubscription(Base):
    __tablename__ = "webhook_subscriptions"
    id = Column(String(36), primary_key=True, default=_id)
    tenant_id = Column(String(36), index=True)
    url = Column(String(500), nullable=False)
    event_types = Column(JSON, default=list)         # [] = all
    secret = Column(String(64), nullable=False)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"
    id = Column(String(36), primary_key=True, default=_id)
    tenant_id = Column(String(36), index=True)
    subscription_id = Column(String(36), index=True, nullable=False)
    event_type = Column(String(80), nullable=False)
    payload = Column(JSON)
    signature = Column(String(80))
    status = Column(String(20), default="pending")   # pending|delivered|failed|dead_letter
    attempts = Column(Integer, default=0)
    max_attempts = Column(Integer, default=5)
    next_attempt_at = Column(DateTime, index=True)
    response_code = Column(Integer)
    last_error = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index("ix_wh_delivery_retry", "status", "next_attempt_at"),)


S8_TABLES = ["api_keys", "webhook_subscriptions", "webhook_deliveries"]
