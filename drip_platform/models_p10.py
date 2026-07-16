"""
models_p10.py — Phase 10 tables: Pipeline Engine + Engagement rollup.

Deliberately a NEW file (not an edit to models.py/models_ext.py) and deliberately
link-table based (no ALTERs), so the whole phase is purely additive:
  - Pipeline / PipelineStage        configurable deal pipelines (HubSpot gap #1)
  - OpportunityStageLink            attaches an existing Opportunity to a
                                    pipeline+stage WITHOUT altering opportunities
  - PersonEngagement                per-person engagement rollup (Mailchimp loop)
                                    WITHOUT altering persons
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


class Pipeline(Base):
    __tablename__ = "pipelines"
    id = Column(String(36), primary_key=True, default=uid)
    name = Column(String, nullable=False, unique=True)
    product_id = Column(String(36), ForeignKey("products.id"), nullable=True)
    is_default = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class PipelineStage(Base):
    __tablename__ = "pipeline_stages"
    id = Column(String(36), primary_key=True, default=uid)
    pipeline_id = Column(String(36), ForeignKey("pipelines.id"), nullable=False)
    name = Column(String, nullable=False)
    order = Column(Integer, nullable=False)
    probability = Column(Float, default=0.1)              # 0..1 weighted-forecast factor
    rotting_days = Column(Integer, default=30)            # idle > this => stalled flag
    is_won = Column(Boolean, default=False)
    is_lost = Column(Boolean, default=False)
    __table_args__ = (UniqueConstraint("pipeline_id", "order"),
                      UniqueConstraint("pipeline_id", "name"),
                      Index("idx_stage_pipeline", "pipeline_id"))


class OpportunityStageLink(Base):
    """Attaches an Opportunity to a pipeline+stage. One link per opportunity.
    Keeps `opportunities` untouched (its free-text `stage` column remains as a
    human label; this link is the governed, forecastable placement)."""
    __tablename__ = "opportunity_stage_links"
    id = Column(String(36), primary_key=True, default=uid)
    opportunity_id = Column(String(36), ForeignKey("opportunities.id"), nullable=False, unique=True)
    pipeline_id = Column(String(36), ForeignKey("pipelines.id"), nullable=False)
    stage_id = Column(String(36), ForeignKey("pipeline_stages.id"), nullable=False)
    entered_stage_at = Column(DateTime, default=datetime.utcnow)
    moved_by = Column(String, default="system")
    history = Column(JSON, default=list)                  # [{stage, at, by}, ...]


class PersonEngagement(Base):
    """Per-person engagement rollup fed by delivery events, LinkedIn actions,
    form submissions and replies. engagement_score in [0,1]. This is the
    'Mailchimp loop' store: org reachability aggregates from here into
    account_scores.reachability_score (0-20)."""
    __tablename__ = "person_engagement"
    id = Column(String(36), primary_key=True, default=uid)
    person_id = Column(String(36), ForeignKey("persons.id"), nullable=False, unique=True)
    opens = Column(Integer, default=0)
    clicks = Column(Integer, default=0)
    replies = Column(Integer, default=0)
    li_accepts = Column(Integer, default=0)
    li_replies = Column(Integer, default=0)
    form_submits = Column(Integer, default=0)
    bounces = Column(Integer, default=0)
    engagement_score = Column(Float, default=0.0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


PHASE10_TABLES = [Pipeline, PipelineStage, OpportunityStageLink, PersonEngagement]
