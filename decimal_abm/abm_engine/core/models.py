"""
abm_engine/core/models.py
─────────────────────────
All data models for the complete ABM intelligence platform.
"""
from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, field_validator


# ─── Enums ────────────────────────────────────────────────────────────────────

class Tier(str, Enum):
    HOT  = "HOT"
    WARM = "WARM"
    COLD = "COLD"

class AccountType(str, Enum):
    BANK      = "BANK"       # licensed bank
    FI        = "FI"         # non-bank financial institution
    VENDOR    = "VENDOR"     # technology vendor (Mambu, Efigence, audax, Ripple)
    SUBSIDIARY = "SUBSIDIARY" # bank subsidiary (ITQAN, Jeel, Riyad Capital)
    CONNECTOR = "CONNECTOR"  # introducer / partner (KPMG, Mastercard, ITC)

class RelationshipType(str, Enum):
    """
    How Decimal relates to this contact.
    Determines outreach tone, cadence, and message angle.
    """
    TARGET    = "TARGET"     # direct sales prospect at a bank/FI
    VENDOR    = "VENDOR"     # peer vendor — partnership / co-sell angle
    CONNECTOR = "CONNECTOR"  # introducer — warm introduction angle
    CHAMPION  = "CHAMPION"   # internal SNB/FI advocate who unlocks C-suite
    INVESTOR  = "INVESTOR"   # VC/fund contact (1957 Ventures etc.)

class Segment(str, Enum):
    ISLAMIC    = "ISLAMIC"
    COMMERCIAL = "COMMERCIAL"
    DIGITAL    = "DIGITAL"
    BNPL       = "BNPL"
    SME        = "SME"
    EMBEDDED   = "EMBEDDED"
    PAYMENTS   = "PAYMENTS"
    OTHER      = "OTHER"

class Persona(str, Enum):
    CTO             = "CTO"
    CDO             = "CDO"
    CEO             = "CEO"
    HEAD_RETAIL     = "HEAD_RETAIL"
    CISO            = "CISO"
    HEAD_PRODUCT    = "HEAD_PRODUCT"
    HEAD_COMPLIANCE = "HEAD_COMPLIANCE"
    HEAD_PARTNERSHIPS = "HEAD_PARTNERSHIPS"
    FOUNDER         = "FOUNDER"
    COO             = "COO"
    CFO             = "CFO"
    OTHER           = "OTHER"

class SignalPriority(str, Enum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"

class SignalType(str, Enum):
    NEW_LICENSE        = "NEW_LICENSE"
    LEADERSHIP_HIRE    = "LEADERSHIP_HIRE"
    DIGITAL_INITIATIVE = "DIGITAL_INITIATIVE"
    SAMA_DEADLINE      = "SAMA_DEADLINE"
    FUNDING_ROUND      = "FUNDING_ROUND"
    VISION_2030        = "VISION_2030"
    PARTNERSHIP        = "PARTNERSHIP"
    PRODUCT_LAUNCH     = "PRODUCT_LAUNCH"
    INTERNAL_UPDATE    = "INTERNAL_UPDATE"   # from HubSpot CRM
    NEWS               = "NEWS"

class TouchType(str, Enum):
    EMAIL    = "EMAIL"
    LINKEDIN = "LINKEDIN"

class TouchStatus(str, Enum):
    DRAFT    = "DRAFT"    # generated, awaiting human approval
    APPROVED = "APPROVED" # human approved, ready to send
    REJECTED = "REJECTED" # human rejected, needs rewrite
    SENT     = "SENT"
    OPENED   = "OPENED"
    REPLIED  = "REPLIED"
    BOUNCED  = "BOUNCED"
    SKIPPED  = "SKIPPED"

class Language(str, Enum):
    EN = "EN"
    AR = "AR"

class NewsCategory(str, Enum):
    BANK_FI    = "BANK_FI"       # target bank/FI news
    VENDOR     = "VENDOR"        # vendor ecosystem news
    LINKEDIN   = "LINKEDIN"      # contact LinkedIn activity
    LEADERSHIP = "LEADERSHIP"    # job changes / hires
    SAMA       = "SAMA"          # regulatory
    INTERNAL   = "INTERNAL"      # HubSpot CRM updates


# ─── Account ──────────────────────────────────────────────────────────────────

class Account(BaseModel):
    id:               Optional[int]    = None
    name:             str
    account_type:     AccountType
    segment:          Segment
    country:          str              = "Saudi Arabia"
    website:          Optional[str]    = None
    description:      Optional[str]    = None  # what this org does / why relevant

    # Scoring inputs
    has_warm_contact:  bool            = False
    sama_pressure:     int             = 0
    is_greenfield:     bool            = False

    composite_score:   int             = 0
    tier:              Tier            = Tier.COLD
    score_updated_at:  Optional[datetime] = None

    is_active:         bool            = True
    hubspot_company_id: Optional[str]  = None

    created_at:  datetime = datetime.utcnow()
    updated_at:  datetime = datetime.utcnow()

    class Config:
        use_enum_values = True


# ─── Contact ──────────────────────────────────────────────────────────────────

class Contact(BaseModel):
    id:               Optional[int]    = None
    account_id:       Optional[int]    = None

    # Identity
    full_name:        str
    role:             str
    persona:          Persona          = Persona.OTHER
    seniority:        str              = "VP"
    is_ksa_national:  bool             = False

    # Relationship type — determines outreach approach
    relationship_type: RelationshipType = RelationshipType.TARGET

    # Organisation
    institution:      str
    country:          str              = "Saudi Arabia"
    institution_type: str              = "Bank"
    segment:          str              = "COMMERCIAL"

    # Contact details
    email:            Optional[str]    = None
    email_confidence: Optional[str]    = None
    linkedin_url:     Optional[str]    = None
    whatsapp:         Optional[str]    = None   # from the phone directory PDFs
    phone:            Optional[str]    = None
    phone_status:     Optional[str]    = None   # ✓✓ / ✓ / ~✓ / ~ / ✗

    # Intelligence
    key_signal:       str              = ""
    outreach_angle:   str              = ""
    product_fit:      str              = ""
    warmness:         str              = "Cold"
    has_warm_relationship: bool        = False
    background_notes: Optional[str]    = None   # key intel from PDFs
    pitch_notes:      Optional[str]    = None   # recommended pitch angle
    connection_paths: Optional[str]    = None   # e.g. "via KPMG → George Harrak"

    # Scoring
    priority_score:   int              = 0
    tier:             Tier             = Tier.COLD

    # State
    hubspot_contact_id: Optional[str]  = None
    current_touch:    int              = 0
    is_active:        bool             = True
    replied:          bool             = False
    reply_handled:    bool             = False

    created_at:    datetime            = datetime.utcnow()
    updated_at:    datetime            = datetime.utcnow()
    last_touch_at: Optional[datetime]  = None

    @property
    def display_name(self) -> str:
        return self.full_name.split()[0]

    @property
    def next_touch(self) -> Optional[int]:
        if self.replied or self.current_touch >= 5:
            return None
        return self.current_touch + 1

    @property
    def needs_arabic(self) -> bool:
        return self.is_ksa_national and self.seniority in ("C-Suite", "VP", "Head of")

    class Config:
        use_enum_values = True


# ─── Draft Message (awaiting approval) ───────────────────────────────────────

class DraftMessage(BaseModel):
    """
    A generated message waiting for human approval in the dashboard.
    Nothing gets sent until status = APPROVED.
    """
    id:             Optional[int]  = None
    contact_id:     int
    touch_number:   int
    touch_type:     TouchType
    language:       Language       = Language.EN

    subject:        Optional[str]  = None
    body_en:        str            = ""
    body_ar:        Optional[str]  = None     # Arabic version if KSA national
    hook_used:      str            = ""

    status:         TouchStatus    = TouchStatus.DRAFT
    rejection_reason: Optional[str] = None   # if human rejects, why

    # Delivery IDs (populated after send)
    mailchimp_id:   Optional[str]  = None
    sendgrid_id:    Optional[str]  = None
    heyreach_id:    Optional[str]  = None
    hubspot_id:     Optional[str]  = None

    generated_at:   datetime       = datetime.utcnow()
    reviewed_at:    Optional[datetime] = None
    sent_at:        Optional[datetime] = None

    class Config:
        use_enum_values = True


# ─── Touch Record ─────────────────────────────────────────────────────────────

class TouchRecord(BaseModel):
    id:             Optional[int]  = None
    contact_id:     int
    draft_id:       Optional[int]  = None
    touch_number:   int
    touch_type:     TouchType
    language:       Language       = Language.EN
    status:         TouchStatus    = TouchStatus.DRAFT

    subject:        Optional[str]  = None
    body:           str            = ""
    body_ar:        Optional[str]  = None
    signal_used:    Optional[str]  = None

    sendgrid_id:    Optional[str]  = None
    mailchimp_id:   Optional[str]  = None
    heyreach_id:    Optional[str]  = None
    hubspot_id:     Optional[str]  = None

    scheduled_at:   Optional[datetime] = None
    sent_at:        Optional[datetime] = None
    opened_at:      Optional[datetime] = None
    replied_at:     Optional[datetime] = None
    error:          Optional[str]  = None

    class Config:
        use_enum_values = True


# ─── Signal ───────────────────────────────────────────────────────────────────

class Signal(BaseModel):
    id:             Optional[int]  = None
    institution:    str
    signal_type:    SignalType
    priority:       SignalPriority
    headline:       str
    detail:         str
    source_url:     Optional[str]  = None
    source_name:    str            = ""
    score_impact:   int            = 0
    detected_at:    datetime       = datetime.utcnow()
    used_in_touch:  bool           = False

    class Config:
        use_enum_values = True


# ─── News Item ────────────────────────────────────────────────────────────────

class NewsItem(BaseModel):
    """
    Intelligence feed item — news, LinkedIn activity, leadership change,
    SAMA announcement, or internal HubSpot update.
    Shown in the dashboard intelligence feed.
    """
    id:             Optional[int]  = None
    category:       NewsCategory
    institution:    str            = ""
    contact_name:   Optional[str]  = None
    headline:       str
    summary:        str
    source_url:     Optional[str]  = None
    source_name:    str            = ""
    relevance_score: int           = 0        # 0–10 how relevant to Decimal
    detected_at:    datetime       = datetime.utcnow()
    is_read:        bool           = False

    class Config:
        use_enum_values = True


# ─── Score Breakdown ──────────────────────────────────────────────────────────

class ScoreBreakdown(BaseModel):
    contact_id:            int
    institution:           str
    signal_strength:       int
    regulatory_pressure:   int
    persona_reachability:  int
    existing_relationship: int
    composite_score:       int
    tier:                  Tier
    scored_at:             datetime = datetime.utcnow()

    class Config:
        use_enum_values = True


# ─── Engagement Event ─────────────────────────────────────────────────────────

class EngagementEvent(BaseModel):
    id:           Optional[int] = None
    contact_id:   int
    touch_id:     Optional[int] = None
    event_type:   str
    raw_content:  Optional[str] = None
    received_at:  datetime      = datetime.utcnow()
    notified:     bool          = False


# ─── Research Result ──────────────────────────────────────────────────────────

class ResearchResult(BaseModel):
    contact_id:       int
    contact_name:     str
    institution:      str
    fresh_signals:    list[str]
    recommended_hook: str
    context_summary:  str
    researched_at:    datetime = datetime.utcnow()


# ─── Generated Message ────────────────────────────────────────────────────────

class GeneratedMessage(BaseModel):
    contact_id:    int
    touch_number:  int
    touch_type:    TouchType
    language:      Language      = Language.EN
    subject:       Optional[str] = None
    body:          str
    hook_used:     str
    word_count:    int
    model:         str           = "claude-sonnet-4-6"
    generated_at:  datetime      = datetime.utcnow()

    @field_validator("body")
    @classmethod
    def body_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Generated body cannot be empty")
        return v.strip()

    class Config:
        use_enum_values = True


# ─── KPI Snapshot ─────────────────────────────────────────────────────────────

class KPISnapshot(BaseModel):
    id:                     Optional[int] = None
    week_start:             str
    touches_sent:           int   = 0
    emails_sent:            int   = 0
    linkedin_sent:          int   = 0
    emails_opened:          int   = 0
    replies_received:       int   = 0
    linkedin_accepts:       int   = 0
    meetings_booked:        int   = 0
    pipeline_value_usd:     int   = 0
    open_rate_pct:          float = 0.0
    reply_rate_pct:         float = 0.0
    engagement_rate_pct:    float = 0.0
    hot_replies:            int   = 0
    warm_replies:           int   = 0
    cold_replies:           int   = 0
    computed_at:            datetime = datetime.utcnow()
