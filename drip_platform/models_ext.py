"""
models_ext.py — ORM tables for the 16 newly-implemented platform modules
(Phase 9, Enterprise Blueprint modules 03,07,09,10,11,12,13,14,15,16,17,20,21,22,25,26).

Same conventions as models.py: String(36) UUIDs generated in Python, JSON
columns, portable across SQLite (dev) and PostgreSQL (prod). ADDITIVE ONLY —
nothing here touches an existing table. Kept in a separate file so models.py
stays the reconciled core and this file is the enterprise extension layer.
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


# ── Module 03 — Enrichment ───────────────────────────────────
class EnrichmentJob(Base):
    __tablename__ = "enrichment_jobs"
    id = Column(String(36), primary_key=True, default=uid)
    entity_type = Column(String, nullable=False)          # person / organization
    entity_id = Column(String(36), nullable=False)
    status = Column(String, default="queued")             # queued/running/partial/done/failed
    providers_tried = Column(JSON, default=list)
    result = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime)
    __table_args__ = (Index("idx_enrich_entity", "entity_type", "entity_id"),)


class MergeCandidate(Base):
    __tablename__ = "merge_candidates"
    id = Column(String(36), primary_key=True, default=uid)
    entity_type = Column(String, nullable=False)
    a_id = Column(String(36), nullable=False)
    b_id = Column(String(36), nullable=False)
    similarity = Column(Float, default=0.0)
    signals = Column(JSON, default=dict)                  # which keys matched
    status = Column(String, default="pending")            # pending/merged/rejected
    created_at = Column(DateTime, default=datetime.utcnow)


# ── Module 07 — Marketing Automation ─────────────────────────
class Audience(Base):
    __tablename__ = "audiences"
    id = Column(String(36), primary_key=True, default=uid)
    name = Column(String, nullable=False, unique=True)
    kind = Column(String, default="list")                 # list (static) / segment (dynamic)
    definition = Column(JSON, default=dict)               # dynamic filter: [{field,op,value},...]
    created_at = Column(DateTime, default=datetime.utcnow)


class AudienceMember(Base):
    __tablename__ = "audience_members"
    id = Column(String(36), primary_key=True, default=uid)
    audience_id = Column(String(36), ForeignKey("audiences.id"), nullable=False)
    person_id = Column(String(36), ForeignKey("persons.id"), nullable=False)
    __table_args__ = (UniqueConstraint("audience_id", "person_id"),)


class Suppression(Base):
    __tablename__ = "suppressions"
    id = Column(String(36), primary_key=True, default=uid)
    email = Column(String, nullable=False, unique=True)
    reason = Column(String, default="manual")             # unsub/bounce/complaint/manual/invalid
    created_at = Column(DateTime, default=datetime.utcnow)


class EmailCampaign(Base):
    __tablename__ = "email_campaigns"
    id = Column(String(36), primary_key=True, default=uid)
    name = Column(String, nullable=False)
    audience_id = Column(String(36), ForeignKey("audiences.id"), nullable=True)
    template_id = Column(String(36), ForeignKey("templates.id"), nullable=True)
    subject = Column(String)
    body = Column(Text)
    status = Column(String, default="draft")              # draft/scheduled/sending/sent/paused
    ab_config = Column(JSON, default=dict)                # {variants:[{name,subject}], metric}
    scheduled_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)


class EmailMessage(Base):
    __tablename__ = "email_messages"
    id = Column(String(36), primary_key=True, default=uid)
    campaign_id = Column(String(36), ForeignKey("email_campaigns.id"), nullable=True)
    person_id = Column(String(36), ForeignKey("persons.id"), nullable=False)
    to_email = Column(String)
    variant = Column(String)
    status = Column(String, default="queued")             # queued/sent/delivered/opened/clicked/bounced/complained/unsub
    sent_at = Column(DateTime)
    __table_args__ = (Index("idx_emsg_campaign", "campaign_id"),)


# ── Module 09 — Campaign Builder ─────────────────────────────
class AbmCampaign(Base):
    __tablename__ = "abm_campaigns"
    id = Column(String(36), primary_key=True, default=uid)
    name = Column(String, nullable=False, unique=True)
    objective = Column(String, default="pipeline")        # awareness/demand/pipeline/expansion
    status = Column(String, default="planned")            # planned/active/completed/archived
    budget = Column(Float, default=0.0)
    start_date = Column(DateTime)
    end_date = Column(DateTime)
    owner = Column(String, default="Puneet")
    kpis = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)


class AbmCampaignMember(Base):
    __tablename__ = "abm_campaign_members"
    id = Column(String(36), primary_key=True, default=uid)
    campaign_id = Column(String(36), ForeignKey("abm_campaigns.id"), nullable=False)
    member_type = Column(String, nullable=False)          # sequence/email_campaign/landing_page/asset/org
    member_id = Column(String(36), nullable=False)
    __table_args__ = (UniqueConstraint("campaign_id", "member_type", "member_id"),)


# ── Module 10 — AI Personalization ───────────────────────────
class AiGeneration(Base):
    __tablename__ = "ai_generations"
    id = Column(String(36), primary_key=True, default=uid)
    kind = Column(String, default="email")                # email/subject/linkedin/brief
    person_id = Column(String(36), ForeignKey("persons.id"), nullable=True)
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=True)
    input_context = Column(JSON, default=dict)
    output = Column(Text)
    qc = Column(JSON, default=dict)                       # {passed: bool, issues: [...]}
    status = Column(String, default="draft")              # draft/qc_passed/qc_failed/approved/rejected
    model = Column(String, default="offline-template")
    created_at = Column(DateTime, default=datetime.utcnow)


# ── Module 11 — Email Delivery ───────────────────────────────
class SendRequest(Base):
    __tablename__ = "send_requests"
    id = Column(String(36), primary_key=True, default=uid)
    message_id = Column(String(80), nullable=False, unique=True)   # idempotency key
    # (80 not 36: composite ids like "seq-<uuid36>-<step>" / "wf-<uuid36>-<node>"
    #  exceed 36 chars — Postgres enforces VARCHAR length, SQLite doesn't.)
    to_email = Column(String, nullable=False)
    subject = Column(String)
    body = Column(Text)
    status = Column(String, default="queued")             # queued/sending/sent/failed/blocked
    transport = Column(String, default="dry_run")         # dry_run / smtp / mandrill
    attempts = Column(Integer, default=0)
    detail = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    sent_at = Column(DateTime)


class DeliveryEvent(Base):
    __tablename__ = "delivery_events"
    id = Column(String(36), primary_key=True, default=uid)
    message_id = Column(String(80), nullable=False)   # matches send_requests.message_id
    event_type = Column(String, nullable=False)           # delivered/open/click/bounce/complaint/unsub
    provider = Column(String, default="dry_run")
    provider_event_id = Column(String, unique=True)       # dedup key for webhook replays
    meta = Column(JSON, default=dict)
    occurred_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (Index("idx_dev_msg", "message_id"),)


# ── Module 12 — LinkedIn Automation ──────────────────────────
class LiSeat(Base):
    __tablename__ = "li_seats"
    id = Column(String(36), primary_key=True, default=uid)
    owner = Column(String, nullable=False)
    status = Column(String, default="active")             # active/cooldown/disconnected/banned_suspected
    daily_limit = Column(Integer, default=20)
    actions_today = Column(Integer, default=0)
    last_reset = Column(DateTime, default=datetime.utcnow)


class LiAction(Base):
    __tablename__ = "li_actions"
    id = Column(String(36), primary_key=True, default=uid)
    seat_id = Column(String(36), ForeignKey("li_seats.id"), nullable=False)
    person_id = Column(String(36), ForeignKey("persons.id"), nullable=False)
    action_type = Column(String, default="connect")       # connect/message/inmail/view
    status = Column(String, default="queued")             # queued/sent/accepted/replied/failed/blocked
    detail = Column(Text)
    scheduled_at = Column(DateTime, default=datetime.utcnow)
    executed_at = Column(DateTime)


class CircuitBreaker(Base):
    __tablename__ = "circuit_breakers"
    id = Column(String(36), primary_key=True, default=uid)
    name = Column(String, nullable=False, unique=True)    # e.g. "linkedin"
    healthy = Column(Boolean, default=True)
    reason = Column(String)
    tripped_at = Column(DateTime)


# ── Module 13 — Landing Pages & Forms ────────────────────────
class FormDef(Base):
    __tablename__ = "form_defs"
    id = Column(String(36), primary_key=True, default=uid)
    name = Column(String, nullable=False, unique=True)
    fields = Column(JSON, default=list)                   # [{key,label,required},...]
    consent_required = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class FormSubmission(Base):
    __tablename__ = "form_submissions"
    id = Column(String(36), primary_key=True, default=uid)
    form_id = Column(String(36), ForeignKey("form_defs.id"), nullable=False)
    person_id = Column(String(36), ForeignKey("persons.id"), nullable=True)
    email = Column(String)
    data = Column(JSON, default=dict)
    utm = Column(JSON, default=dict)
    consent_given = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class LandingPage(Base):
    __tablename__ = "landing_pages"
    id = Column(String(36), primary_key=True, default=uid)
    slug = Column(String, nullable=False, unique=True)
    title = Column(String)
    blocks = Column(JSON, default=list)
    status = Column(String, default="draft")              # draft/published/archived
    form_id = Column(String(36), ForeignKey("form_defs.id"), nullable=True)
    asset_id = Column(String(36), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


# ── Module 14 — Asset Library ────────────────────────────────
class Asset(Base):
    __tablename__ = "assets"
    id = Column(String(36), primary_key=True, default=uid)
    name = Column(String, nullable=False)
    asset_type = Column(String, default="pdf")            # whitepaper/case_study/one_pager/deck/pdf/image
    storage_url = Column(String)
    gated = Column(Boolean, default=False)
    tags = Column(JSON, default=list)
    version = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("name", "version"),)


class AssetUsage(Base):
    __tablename__ = "asset_usage"
    id = Column(String(36), primary_key=True, default=uid)
    asset_id = Column(String(36), ForeignKey("assets.id"), nullable=False)
    context_type = Column(String)                         # campaign/landing/email
    context_id = Column(String(36))
    downloads = Column(Integer, default=0)
    last_used_at = Column(DateTime, default=datetime.utcnow)


# ── Module 15 — Rules Engine ─────────────────────────────────
class Rule(Base):
    __tablename__ = "rules"
    id = Column(String(36), primary_key=True, default=uid)
    name = Column(String, nullable=False, unique=True)
    trigger = Column(String, default="event")             # event/manual/schedule
    event_type = Column(String)                           # which bus event fires it
    conditions = Column(JSON, default=list)               # [{field,op,value},...] AND semantics
    actions = Column(JSON, default=list)                  # [{action,params},...] ordered
    priority = Column(Integer, default=100)
    status = Column(String, default="draft")              # draft/active/paused
    version = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)


class RuleFiring(Base):
    __tablename__ = "rule_firings"
    id = Column(String(36), primary_key=True, default=uid)
    rule_id = Column(String(36), ForeignKey("rules.id"), nullable=False)
    subject_type = Column(String)
    subject_id = Column(String(36))
    matched = Column(Boolean, default=False)
    actions_result = Column(JSON, default=list)
    dry_run = Column(Boolean, default=False)
    at = Column(DateTime, default=datetime.utcnow)


# ── Module 16 — Workflow Engine ──────────────────────────────
class WorkflowDef(Base):
    __tablename__ = "workflow_defs"
    id = Column(String(36), primary_key=True, default=uid)
    name = Column(String, nullable=False, unique=True)
    nodes = Column(JSON, default=list)                    # [{id,type,config},...]
    edges = Column(JSON, default=list)                    # [{from,to,when},...]
    status = Column(String, default="draft")
    version = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"
    id = Column(String(36), primary_key=True, default=uid)
    workflow_id = Column(String(36), ForeignKey("workflow_defs.id"), nullable=False)
    status = Column(String, default="running")            # running/waiting/succeeded/failed/cancelled
    ctx = Column(JSON, default=dict)
    cursor = Column(String)                               # current node id (durable resume point)
    wait_until = Column(DateTime)
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime)


class NodeExecution(Base):
    __tablename__ = "node_executions"
    id = Column(String(36), primary_key=True, default=uid)
    run_id = Column(String(36), ForeignKey("workflow_runs.id"), nullable=False)
    node_id = Column(String, nullable=False)
    status = Column(String, default="done")               # done/failed/skipped/waiting
    output = Column(JSON, default=dict)
    at = Column(DateTime, default=datetime.utcnow)


# ── Module 17 — Analytics ────────────────────────────────────
class MetricEvent(Base):
    __tablename__ = "metric_events"
    id = Column(String(36), primary_key=True, default=uid)
    event_type = Column(String, nullable=False)
    subject_type = Column(String)
    subject_id = Column(String(36))
    props = Column(JSON, default=dict)
    occurred_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (Index("idx_me_type", "event_type"),)


# ── Module 20 — Reporting ────────────────────────────────────
class ReportDef(Base):
    __tablename__ = "report_defs"
    id = Column(String(36), primary_key=True, default=uid)
    name = Column(String, nullable=False, unique=True)
    definition = Column(JSON, default=dict)               # {event_type, group_by, since_days}
    viz = Column(String, default="table")
    created_at = Column(DateTime, default=datetime.utcnow)


class ExecBrief(Base):
    __tablename__ = "exec_briefs"
    id = Column(String(36), primary_key=True, default=uid)
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    content = Column(JSON, default=dict)                  # sections: profile/committee/signals/score/next
    generated_at = Column(DateTime, default=datetime.utcnow)


# ── Module 21 — Notification ─────────────────────────────────
class Notification(Base):
    __tablename__ = "notifications"
    id = Column(String(36), primary_key=True, default=uid)
    user = Column(String, nullable=False, default="Puneet")
    kind = Column(String, nullable=False)                 # reply/hot_account/approval/anomaly/digest
    channel = Column(String, default="in_app")
    payload = Column(JSON, default=dict)
    priority = Column(String, default="med")              # low/med/high/urgent
    status = Column(String, default="pending")            # pending/sent/read/failed
    created_at = Column(DateTime, default=datetime.utcnow)
    read_at = Column(DateTime)


class NotifyPref(Base):
    __tablename__ = "notify_prefs"
    id = Column(String(36), primary_key=True, default=uid)
    user = Column(String, nullable=False, unique=True)
    channels = Column(JSON, default=lambda: ["in_app"])
    quiet_hours = Column(JSON, default=dict)              # {start: 22, end: 7}
    digest = Column(String, default="off")


# ── Module 22 — Attribution ──────────────────────────────────
class Touch(Base):
    __tablename__ = "touches"
    id = Column(String(36), primary_key=True, default=uid)
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=True)
    person_id = Column(String(36), ForeignKey("persons.id"), nullable=True)
    channel = Column(String, default="email")             # email/linkedin/event/web/content
    campaign_id = Column(String(36), nullable=True)
    occurred_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (Index("idx_touch_org", "org_id"),)


class AttributionResult(Base):
    __tablename__ = "attribution_results"
    id = Column(String(36), primary_key=True, default=uid)
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    outcome_ref = Column(String)                          # e.g. opportunity id / "meeting"
    model = Column(String, default="linear")              # first/last/linear/time_decay/w_shaped
    credit = Column(JSON, default=dict)                   # {touch_id: fraction}
    computed_at = Column(DateTime, default=datetime.utcnow)


# ── Module 25 — Admin / RBAC ─────────────────────────────────
class AppRole(Base):
    __tablename__ = "app_roles"
    id = Column(String(36), primary_key=True, default=uid)
    name = Column(String, nullable=False, unique=True)
    permissions = Column(JSON, default=list)              # ["crm.read","sequences.manage",...]


class AppUser(Base):
    __tablename__ = "app_users"
    id = Column(String(36), primary_key=True, default=uid)
    email = Column(String, nullable=False, unique=True)
    name = Column(String)
    role_id = Column(String(36), ForeignKey("app_roles.id"), nullable=True)
    status = Column(String, default="active")
    created_at = Column(DateTime, default=datetime.utcnow)


class Quota(Base):
    __tablename__ = "quotas"
    id = Column(String(36), primary_key=True, default=uid)
    kind = Column(String, nullable=False, unique=True)    # ai_credits/emails/enrichment_credits
    limit = Column(Integer, default=1000)
    used = Column(Integer, default=0)
    period = Column(String, default="monthly")


# ── Module 26 — Copilot ──────────────────────────────────────
class CopilotTurn(Base):
    __tablename__ = "copilot_turns"
    id = Column(String(36), primary_key=True, default=uid)
    question = Column(Text, nullable=False)
    intent = Column(String)
    answer = Column(Text)
    citations = Column(JSON, default=list)
    created_at = Column(DateTime, default=datetime.utcnow)


# Ordered list used by the Alembic migration (create in this order, drop reversed)
ALL_TABLES = [
    EnrichmentJob, MergeCandidate,
    Audience, AudienceMember, Suppression, EmailCampaign, EmailMessage,
    AbmCampaign, AbmCampaignMember,
    AiGeneration,
    SendRequest, DeliveryEvent,
    LiSeat, LiAction, CircuitBreaker,
    FormDef, FormSubmission, LandingPage,
    Asset, AssetUsage,
    Rule, RuleFiring,
    WorkflowDef, WorkflowRun, NodeExecution,
    MetricEvent,
    ReportDef, ExecBrief,
    Notification, NotifyPref,
    Touch, AttributionResult,
    AppRole, AppUser, Quota,
    CopilotTurn,
]
