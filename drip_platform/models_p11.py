"""
models_p11.py — Phase 11 tables: native tracking stack, deliverability engine,
AI Decision Engine, and the AI feedback loop. New file, purely additive.
"""
from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Integer, Float, Boolean, Text, DateTime, ForeignKey,
    JSON, UniqueConstraint, Index
)
from database import Base


def uid() -> str:
    return str(uuid.uuid4())


class TrackedLink(Base):
    """Click tracking: every email link is rewritten to /t/c/{token}. The first
    request hits our server (click logged), then 302 to the real URL."""
    __tablename__ = "tracked_links"
    id = Column(String(36), primary_key=True, default=uid)
    token = Column(String(64), nullable=False, unique=True)
    message_id = Column(String(80), nullable=False)       # matches send_requests
    original_url = Column(Text, nullable=False)
    utm = Column(JSON, default=dict)                      # utm_* appended on redirect
    clicks = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (Index("idx_tlink_msg", "message_id"),)


class WebVisitor(Base):
    """Cookie identity: visitor_id cookie -> (eventually) a Person. Set on
    first tracked click/landing visit; identified when a form ties it to an
    email. This is how anonymous website activity joins the CRM timeline."""
    __tablename__ = "web_visitors"
    id = Column(String(36), primary_key=True, default=uid)
    visitor_id = Column(String(64), nullable=False, unique=True)   # cookie value
    person_id = Column(String(36), ForeignKey("persons.id"), nullable=True)
    first_seen = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow)
    first_utm = Column(JSON, default=dict)
    pages_viewed = Column(Integer, default=0)


class WebEvent(Base):
    """tracking.js event stream: page views, scroll, downloads, form starts —
    the Segment/Mixpanel-style layer. Linked to visitor (and person once
    identified)."""
    __tablename__ = "web_events"
    id = Column(String(36), primary_key=True, default=uid)
    visitor_id = Column(String(64), nullable=False)
    person_id = Column(String(36), ForeignKey("persons.id"), nullable=True)
    event_type = Column(String, nullable=False)   # page_view/scroll/download/form_start/form_complete/pricing_view
    url = Column(Text)
    props = Column(JSON, default=dict)
    utm = Column(JSON, default=dict)
    occurred_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (Index("idx_webev_visitor", "visitor_id"),
                      Index("idx_webev_person", "person_id"))


class DomainHealth(Base):
    """Deliverability engine state per sending domain: reputation, warmup,
    rolling bounce/complaint rates, and the volume gate."""
    __tablename__ = "domain_health"
    id = Column(String(36), primary_key=True, default=uid)
    domain = Column(String, nullable=False, unique=True)
    dkim_ok = Column(Boolean, default=False)
    spf_ok = Column(Boolean, default=False)
    dmarc_ok = Column(Boolean, default=False)
    warmup_stage = Column(Integer, default=1)             # 1..7 → daily cap grows
    reputation = Column(Float, default=0.7)               # 0..1 rolling
    bounce_rate = Column(Float, default=0.0)
    complaint_rate = Column(Float, default=0.0)
    sends_today = Column(Integer, default=0)
    last_reset = Column(DateTime, default=datetime.utcnow)


class DecisionLog(Base):
    """AI Decision Engine: every decision recorded with its full reasoning —
    what to do next, when, through which channel, and why. Explainability is
    mandatory (no un-audited autonomous choices)."""
    __tablename__ = "decision_log"
    id = Column(String(36), primary_key=True, default=uid)
    person_id = Column(String(36), ForeignKey("persons.id"), nullable=False)
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=True)
    action = Column(String, nullable=False)    # send_email/linkedin_touch/whatsapp/wait/notify_sales/suggest_meeting/hold_human
    channel = Column(String)
    wait_hours = Column(Integer, default=0)
    content_hint = Column(String)
    confidence = Column(Float, default=0.5)
    reasons = Column(JSON, default=list)       # ordered, human-readable
    inputs = Column(JSON, default=dict)        # the features the decision used
    executed = Column(Boolean, default=False)
    outcome = Column(String)                   # filled later: replied/meeting/none
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (Index("idx_dec_person", "person_id"),)


class VariantPerformance(Base):
    """AI feedback loop: rolling performance per template/variant/subject so
    the engine learns which content works and picks better next time."""
    __tablename__ = "variant_performance"
    id = Column(String(36), primary_key=True, default=uid)
    kind = Column(String, default="email")     # email/subject/linkedin
    variant_key = Column(String, nullable=False)   # template id / variant name / subject hash
    label = Column(String)
    sends = Column(Integer, default=0)
    opens = Column(Integer, default=0)
    clicks = Column(Integer, default=0)
    replies = Column(Integer, default=0)
    meetings = Column(Integer, default=0)
    score = Column(Float, default=0.0)         # rolling weighted performance
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (UniqueConstraint("kind", "variant_key"),)


PHASE11_TABLES = [TrackedLink, WebVisitor, WebEvent, DomainHealth,
                  DecisionLog, VariantPerformance]
