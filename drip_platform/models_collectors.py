"""
models_collectors.py — Parity Mission: signal-source registry for the collector
framework. One row per external source (RSS feed, news page); tracks schedule,
health, and consecutive failures so a broken source disables itself instead of
poisoning the pipeline.
"""
from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Integer, Boolean, Text
from database import Base


def _id() -> str:
    return str(uuid.uuid4())


class SignalSource(Base):
    __tablename__ = "signal_sources"
    id = Column(String(36), primary_key=True, default=_id)
    tenant_id = Column(String(36), index=True)
    name = Column(String(120), nullable=False)
    kind = Column(String(20), default="rss")          # rss | atom
    url = Column(String(600), nullable=False)
    signal_type = Column(String(40), default="news")  # news | regulatory | hiring | tender
    interval_minutes = Column(Integer, default=60)
    enabled = Column(Boolean, default=True)
    last_run_at = Column(DateTime)
    last_status = Column(String(200))
    error_count = Column(Integer, default=0)          # consecutive; auto-disable at 5
    items_ingested = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


COLLECTOR_TABLES = ["signal_sources"]
