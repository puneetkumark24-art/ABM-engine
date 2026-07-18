"""
models.py — DRIP reconciled entity model (SQLAlchemy ORM).

Reconciles three prior artifacts found during Phase 1 discovery:
  - brip_dashboard's universal `organizations` + `org_type_tags` shape
    (closest fit to the DRIP PRD's Organization Master, Section 6)
  - the ABM Business Logic Bible's `Account` sales-decision fields
    (kept as a 1:1 extension table `account_intelligence`, not baked
    into every organization row — see Phase 1 report Section 6)
  - decimal_abm's live schema_v2.sql (products, product_fit, signals,
    opportunities, buying_committee, drafts, touch/audit logs) — ported
    forward rather than redesigned, per PRD Golden Rule "reuse existing work"

IDs are String(36) UUIDs (generated in Python) so the same models run
unchanged on SQLite (dev) and PostgreSQL (production).
"""
from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Integer, BigInteger, Float, Boolean, Text, DateTime, ForeignKey,
    JSON, UniqueConstraint, Index, LargeBinary
)
from sqlalchemy.orm import relationship
from database import Base


def uid() -> str:
    return str(uuid.uuid4())


# ─────────────────────────────────────────────────────────────
#  ORGANIZATION MASTER  (PRD §6)
# ─────────────────────────────────────────────────────────────
class Organization(Base):
    __tablename__ = "organizations"

    id = Column(String(36), primary_key=True, default=uid)
    canonical_name = Column(String, nullable=False, unique=True)
    name_ar = Column(String)
    aliases = Column(JSON, default=list)               # legal/prior/abbreviated names — entity resolution
    short_name = Column(String, index=True)

    parent_org_id = Column(String(36), ForeignKey("organizations.id"), nullable=True)

    country = Column(String, default="Saudi Arabia")
    region = Column(String)
    website = Column(String)
    headquarters = Column(String)

    # Technology stack (PRD §10)
    core_banking = Column(String)
    crm = Column(String)
    los = Column(String)
    lms = Column(String)
    collections = Column(String)
    treasury = Column(String)
    payments = Column(String)
    risk = Column(String)
    fraud = Column(String)
    aml = Column(String)
    kyc = Column(String)
    cloud = Column(String)
    api_gateway = Column(String)
    ai_initiatives = Column(JSON, default=list)

    annual_revenue_usd = Column(Float)
    employee_count = Column(Integer)
    assets_usd_billions = Column(Float)
    founded = Column(String)

    source = Column(String)                             # provenance
    verification_status = Column(String, default="unverified")  # unverified/verified/stale
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    type_tags = relationship("OrgTypeTag", back_populates="organization", cascade="all, delete-orphan")
    account = relationship("AccountIntelligence", back_populates="organization", uselist=False,
                            cascade="all, delete-orphan")
    persons = relationship("Person", back_populates="organization")


class OrgTypeTag(Base):
    """Multi-classification: a bank subsidiary can be both 'commercial_bank' and 'digital_bank'."""
    __tablename__ = "org_type_tags"
    id = Column(String(36), primary_key=True, default=uid)
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    type_tag = Column(String, nullable=False)  # commercial_bank, islamic_bank, digital_bank, bnpl,
                                                 # vendor, fintech, regulator, consulting, association, etc.
    __table_args__ = (UniqueConstraint("org_id", "type_tag"), Index("idx_orgtag_org", "org_id"))
    organization = relationship("Organization", back_populates="type_tags")


class OrgRelationship(Base):
    """Org <-> Org: parent/subsidiary, vendor, partner, competitor, regulator_of, serves."""
    __tablename__ = "org_relationships"
    id = Column(String(36), primary_key=True, default=uid)
    from_org_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    to_org_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    relationship_type = Column(String, nullable=False)
    strength = Column(String, default="Weak")   # Strong/Medium/Weak
    confidence = Column(Float, default=0.5)
    source = Column(String)
    context = Column(Text)
    start_date = Column(DateTime)
    end_date = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)


# ─────────────────────────────────────────────────────────────
#  ACCOUNT INTELLIGENCE  — Bible Tier-1 Account, as an extension
#  (only organizations Decimal actually sells to carry this)
# ─────────────────────────────────────────────────────────────
class AccountIntelligence(Base):
    __tablename__ = "account_intelligence"
    org_id = Column(String(36), ForeignKey("organizations.id"), primary_key=True)

    segment = Column(String)          # Commercial Bank, Digital Bank, BNPL, SME Lending...
    sub_segment = Column(String)
    digital_maturity = Column(Integer, default=5)
    open_banking = Column(String, default="Unknown")

    tier = Column(String, default="Tier 3")            # Tier 1/2/3 — static sales segmentation
    priority = Column(String, default="COLD")          # HOT/WARM/COLD  (Bible: current_state.tier) — computed by scoring.py
    lifecycle_status = Column(String, default="Prospect")  # Prospect/Engaged/Pilot/Customer/Dormant/Disqualified
    score = Column(Integer, default=0)                 # composite 0-100 (legacy int mirror of effective_opportunity)
    readiness = Column(Integer, default=0)

    # Live Bible scoring — scoring.py's exact formula, computed from these inputs rather than
    # a hardcoded tier. scoring_inputs holds the raw form values so the score edit page can be
    # re-opened and adjusted rather than starting from scratch each time.
    effective_opportunity = Column(Float)
    decision_score = Column(Float)
    scoring_inputs = Column(JSON)
    scored_at = Column(DateTime)

    owner = Column(String, default="Puneet")
    last_signal_at = Column(DateTime)
    last_touch_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    organization = relationship("Organization", back_populates="account")


class AccountScore(Base):
    """Daily scoring history — Bible's Three_Score_Record / decimal_abm's account_scores."""
    __tablename__ = "account_scores"
    id = Column(String(36), primary_key=True, default=uid)
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    score_date = Column(DateTime, default=datetime.utcnow)
    signal_score = Column(Integer, default=0)          # 0-35
    regulatory_score = Column(Integer, default=0)       # 0-30
    reachability_score = Column(Integer, default=0)     # 0-20
    relationship_score = Column(Integer, default=0)     # 0-15
    total_score = Column(Integer, default=0)
    tier = Column(String)
    notes = Column(Text)
    __table_args__ = (Index("idx_scores_org", "org_id"),)


# ─────────────────────────────────────────────────────────────
#  PEOPLE INTELLIGENCE  (PRD §7) — persists across job changes
# ─────────────────────────────────────────────────────────────
class Person(Base):
    __tablename__ = "persons"
    id = Column(String(36), primary_key=True, default=uid)

    full_name = Column(String, nullable=False)
    full_name_ar = Column(String)

    current_org_id = Column(String(36), ForeignKey("organizations.id"), index=True)
    current_title = Column(String)
    department = Column(String)
    business_unit = Column(String)
    function = Column(String)
    seniority_level = Column(String)      # c_suite, svp_evp, vp, director, manager
    persona = Column(String)              # Decision Maker, Influencer, Champion, Blocker, User
    decision_weight = Column(Integer, default=5)

    is_decision_maker = Column(Boolean, default=False)
    is_influencer = Column(Boolean, default=False)
    is_connector = Column(Boolean, default=False)

    primary_email = Column(String)
    secondary_email = Column(String)
    email_confidence = Column(String, default="Unknown")
    phone = Column(String)
    mobile = Column(String)
    whatsapp = Column(String)
    linkedin_url = Column(String)
    linkedin_public_id = Column(String)

    country = Column(String)
    city = Column(String)
    is_ksa_national = Column(Boolean, default=False)

    past_companies = Column(JSON, default=list)
    education = Column(JSON, default=list)
    skills = Column(JSON, default=list)
    certifications = Column(JSON, default=list)
    languages = Column(JSON, default=list)

    reporting_manager_id = Column(String(36), ForeignKey("persons.id"), nullable=True)
    warmness = Column(String, default="Cold")
    priority_score = Column(Integer, default=0)
    tier = Column(String, default="COLD")             # internal outreach warmth: COLD/WARM/HOT
    priority_tier = Column(String)                     # source-list priority: "Tier 1"/"Tier 2"/"Tier 3"
    is_indian_origin = Column(Boolean, default=False)   # from "Indians at X" / "India-located" source sheets
    last_activity_summary = Column(String)              # auto-generated from the outreach fields below, shown in the dashboard table
    next_step = Column(String)                          # sales-team notes on what to do next, editable from the dashboard

    outreach_connection_sent = Column(Boolean, default=False)
    outreach_connection_sent_date = Column(DateTime)
    outreach_connection_accepted = Column(Boolean, default=False)
    outreach_messaged = Column(Boolean, default=False)
    outreach_response_notes = Column(Text)               # what they said back, in their own words
    outreach_updated_by = Column(String)                 # free-text name of whoever logged the update (no login system yet)
    outreach_updated_at = Column(DateTime)

    # BD ecosystem/flow-diagram placement — set at import time from BD dossiers (SNB-style
    # connection architecture docs), separate from priority_tier (which comes from LinkedIn
    # source sheets) and from persona/is_influencer (which are general-purpose, not campaign-specific).
    bd_flow_column = Column(String)   # connector / champion / decision_maker / c_suite
    bd_priority = Column(String)      # raw label from the dossier: P1/P2/P3/Critical/Strategic/Connector/etc.

    interaction_lineage = Column(JSON, default=list)     # Bible CONTACT-MEMORY-001
    background_notes = Column(Text)
    pitch_notes = Column(Text)
    connection_paths = Column(Text)

    consent_status = Column(String, default="none")      # none/opted_in/denied
    consent_date = Column(DateTime)
    consent_source = Column(String)
    do_not_contact = Column(Boolean, default=False)
    data_source = Column(String)                          # Apollo, LinkedIn, Manual, prior BD research
    is_active = Column(Boolean, default=True)
    replied = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    organization = relationship("Organization", back_populates="persons", foreign_keys=[current_org_id])


class OutreachChannel(Base):
    """Per-channel outreach tracking — one row per (person, channel). Split out from Person
    because outreach isn't one thing: a contact can be mid-conversation on LinkedIn, cold on
    email, and never called at all, all at once. 'stage' is deliberately a free-text field, not
    an enum — sales teams describe progress in their own words ('sent a voice note', 'forwarded
    to his assistant') and a fixed dropdown would just get fought with 'Other: ...' entries.
    The dashboard suggests common stages via a datalist but never restricts input to them.
    """
    __tablename__ = "outreach_channels"
    id = Column(String(36), primary_key=True, default=uid)
    person_id = Column(String(36), ForeignKey("persons.id"), nullable=False)
    channel = Column(String, nullable=False)   # linkedin / email / phone / whatsapp
    stage = Column(String)                     # free text: "Connection sent", "Replied", whatever fits
    notes = Column(Text)                       # their response / call notes / details, in your own words
    next_step = Column(String)                 # what to do next on this specific channel
    updated_by = Column(String)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (UniqueConstraint("person_id", "channel"), Index("idx_outreach_person", "person_id"))


class PersonRelationship(Base):
    """Person <-> Person: knows, introduced_by, met_at, referred_by, worked_with, reports_to."""
    __tablename__ = "person_relationships"
    id = Column(String(36), primary_key=True, default=uid)
    from_person_id = Column(String(36), ForeignKey("persons.id"), nullable=True)
    from_name = Column(String)          # free-text when the "from" side isn't a Person record yet
    from_type = Column(String, default="contact")  # decimal, vendor, partner, investor, consultant, contact
    to_person_id = Column(String(36), ForeignKey("persons.id"), nullable=False)
    relationship_type = Column(String, nullable=False)
    strength = Column(String, default="Weak")
    context = Column(Text)
    last_interaction = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)


# ─────────────────────────────────────────────────────────────
#  PRODUCTS + FIT + BUYING COMMITTEE + OPPORTUNITIES
# ─────────────────────────────────────────────────────────────
class Product(Base):
    __tablename__ = "products"
    id = Column(String(36), primary_key=True, default=uid)
    name = Column(String, nullable=False, unique=True)
    category = Column(String)
    description = Column(Text)
    target_segments = Column(JSON, default=list)
    key_benefits = Column(Text)
    competitors = Column(JSON, default=list)


class ProductFit(Base):
    __tablename__ = "product_fit"
    id = Column(String(36), primary_key=True, default=uid)
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    product_id = Column(String(36), ForeignKey("products.id"), nullable=False)
    fit_score = Column(Integer, default=50)
    fit_reason = Column(Text)
    pitch_angle = Column(Text)
    objection_notes = Column(Text)
    __table_args__ = (UniqueConstraint("org_id", "product_id"),)


class BuyingCommitteeMember(Base):
    __tablename__ = "buying_committee_members"
    id = Column(String(36), primary_key=True, default=uid)
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    person_id = Column(String(36), ForeignKey("persons.id"), nullable=False)
    product_id = Column(String(36), ForeignKey("products.id"), nullable=True)
    committee_role = Column(String)     # Decision Maker, Influencer, Champion, Blocker, User, Approver
    engagement = Column(String, default="Unknown")
    notes = Column(Text)
    __table_args__ = (UniqueConstraint("org_id", "person_id", "product_id"),)


class Opportunity(Base):
    __tablename__ = "opportunities"
    id = Column(String(36), primary_key=True, default=uid)
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    product_id = Column(String(36), ForeignKey("products.id"), nullable=True)
    stage = Column(String, default="Identified")  # Identified..Won/Lost
    probability = Column(Integer, default=10)
    estimated_value = Column(String)               # legacy free text (kept)
    amount_minor = Column(BigInteger)              # Sprint 2: money-correct value (minor units)
    currency = Column(String, default="SAR")
    champion_id = Column(String(36), ForeignKey("persons.id"), nullable=True)
    next_step = Column(Text)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    closed_at = Column(DateTime)


# ─────────────────────────────────────────────────────────────
#  VENDOR INTELLIGENCE  (PRD §9, Bible Vendor_Intelligence)
# ─────────────────────────────────────────────────────────────
class VendorIntelligence(Base):
    __tablename__ = "vendor_intelligence"
    id = Column(String(36), primary_key=True, default=uid)
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=False, unique=True)
    products = Column(JSON, default=list)
    capabilities = Column(JSON, default=list)
    clients = Column(JSON, default=list)              # org_ids or names of known clients
    countries = Column(JSON, default=list)
    technologies = Column(JSON, default=list)
    implementation_partners = Column(JSON, default=list)
    case_studies = Column(JSON, default=list)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ─────────────────────────────────────────────────────────────
#  SIGNALS  (event-driven intelligence)
# ─────────────────────────────────────────────────────────────
class Signal(Base):
    __tablename__ = "signals"
    id = Column(String(36), primary_key=True, default=uid)
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=True)  # NULL = unattributed
    signal_type = Column(String)      # leadership_change, regulatory, product_launch, hiring, funding, partnership, rfp, expansion, earnings, other
    source = Column(String)
    title = Column(Text)
    summary = Column(Text)
    url = Column(String, unique=True)
    urgency = Column(String, default="LOW")   # CRITICAL/HIGH/MEDIUM/LOW
    product_match = Column(String)
    is_read = Column(Boolean, default=False)
    is_actioned = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # SIG-TENDER fields (ABM Business Logic Bible, OPEN-GAP-SIG-02) — populated when
    # signal_type='rfp'. Per the Bible's recommended P1 path, this starts as manual BD-team
    # input (someone hears about a tender through network intelligence and logs it here)
    # rather than automated Etimad scraping, which is a P2 follow-on.
    deadline = Column(DateTime)                # tender/RFP response deadline
    estimated_value = Column(String)           # free text — currency varies (SAR, USD), often a range
    scope_description = Column(Text)           # what's actually being procured
    contact_person = Column(String)            # who at the bank to reach re: this tender
    source_of_knowledge = Column(String)       # "who told us" — distinct from `source`, which is often just "Manual"

    # SIG-PARTNER fields (OPEN-GAP-SIG-06) — populated when signal_type='partnership'.
    # Per the Bible, this is a classification LAYER on news/signal text, not a new source:
    # is the named partner a Decimal competitor (closing a deal = urgent/negative) or
    # complementary (integration opportunity = positive)? See etl/signal_intel.py.
    partner_classification = Column(String)     # COMPETITIVE_CLOSURE / INTEGRATION_OPPORTUNITY / COMPLIANCE_ALIGNMENT / NEUTRAL
    partner_classification_matched_vendor = Column(String)  # which registry entry triggered the classification, for a human to sanity-check

    # Signal Pipeline P1 (EPIS-RCM-01, EPIS-HALF-01) — see etl/signal_decay.py and
    # docs/Signal_Pipeline_Architecture.md §4.1. Stamped automatically on every save;
    # source_reliability stays NULL until P2 (source_registry) exists.
    confidence_score = Column(Float, nullable=True)       # 0-1, deterministic v1 heuristic
    decay_category = Column(String, nullable=True)        # OPERATIONAL / TACTICAL / STRATEGIC / STRUCTURAL
    decay_expires_at = Column(DateTime, nullable=True)     # created_at + decay_category's half-life
    source_reliability = Column(Float, nullable=True)      # P2: populated from source_registry at capture time
    content_hash = Column(String(64), nullable=True)       # S4: dedup key for idempotent collectors

    __table_args__ = (Index("idx_signals_org", "org_id"), Index("idx_signals_type", "signal_type"),
                      Index("idx_signals_hash", "content_hash"))


# ─────────────────────────────────────────────────────────────
#  UNIVERSAL ACTIVITY ENGINE  (PRD §12) + DRAFTS/TEMPLATES
# ─────────────────────────────────────────────────────────────
class Draft(Base):
    __tablename__ = "drafts"
    id = Column(String(36), primary_key=True, default=uid)
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=True)
    person_id = Column(String(36), ForeignKey("persons.id"), nullable=True)
    channel = Column(String, default="email")
    subject = Column(String)
    body = Column(Text)
    status = Column(String, default="pending")  # pending/approved/rejected/sent
    source = Column(String, default="ai")
    signal_id = Column(String(36), ForeignKey("signals.id"), nullable=True)
    product_id = Column(String(36), ForeignKey("products.id"), nullable=True)
    sequence_step = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)
    reviewed_at = Column(DateTime)
    sent_at = Column(DateTime)
    reviewer_notes = Column(Text)


class ActivityLog(Base):
    """Universal Activity Engine — every touch, of any type, against any entity."""
    __tablename__ = "activity_log"
    id = Column(String(36), primary_key=True, default=uid)
    activity_type = Column(String, nullable=False)   # email, linkedin, phone, whatsapp, meeting, proposal, demo, rfp, poc...
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=True)
    person_id = Column(String(36), ForeignKey("persons.id"), nullable=True)
    opportunity_id = Column(String(36), ForeignKey("opportunities.id"), nullable=True)
    owner = Column(String)
    outcome = Column(String)
    duration_minutes = Column(Integer)
    priority = Column(String)
    notes = Column(Text)
    next_action = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (Index("idx_activity_org", "org_id"), Index("idx_activity_person", "person_id"))


class Template(Base):
    __tablename__ = "templates"
    id = Column(String(36), primary_key=True, default=uid)
    name = Column(String, nullable=False)
    channel = Column(String, default="email")
    subject = Column(String)
    body = Column(Text)
    product_id = Column(String(36), ForeignKey("products.id"), nullable=True)
    persona_target = Column(String)
    sequence_step = Column(Integer, default=1)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id = Column(String(36), primary_key=True, default=uid)
    action = Column(String)
    details = Column(Text)
    actor = Column(String, default="system")
    timestamp = Column(DateTime, default=datetime.utcnow)


# ─────────────────────────────────────────────────────────────
#  INTELLIGENCE UPLOADS  — raw dossiers uploaded from the dashboard,
#  stored in Postgres (not on the local filesystem) and queued for
#  extraction. Nothing here auto-creates Organizations/Persons — a
#  human (or Claude, given the file) reviews and extracts it, same
#  discipline as the manual SNB import, so nothing gets fabricated.
# ─────────────────────────────────────────────────────────────
class DocumentUpload(Base):
    __tablename__ = "document_uploads"
    id = Column(String(36), primary_key=True, default=uid)
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=True)   # set once linked to a real bank
    org_name_hint = Column(String)         # what the uploader typed/selected, even before org exists
    import_kind = Column(String, default="contacts")   # contacts / ecosystem — which one-click importer to run
    filename = Column(String, nullable=False)
    content_type = Column(String)
    file_size = Column(Integer)
    file_data = Column(LargeBinary, nullable=False)   # raw bytes, lives in Postgres — not on disk
    uploaded_by = Column(String)
    notes = Column(Text)                    # uploader's own note on what this is / why
    status = Column(String, default="pending")   # pending / processing / processed / failed
    processing_notes = Column(Text)          # what was extracted, or why it failed
    processed_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Populated immediately on upload for PDFs/images by etl/document_reader.py — rule-based
    # (no AI/API key), so a bank's page and connection map update right away instead of sitting
    # in a "Pending — share with Claude" queue. extracted_text is capped at 20k chars (full text
    # for anything reasonably sized; long dossiers get truncated rather than blowing up storage).
    extracted_text = Column(Text)
    extracted_summary = Column(Text)
    detected_entities = Column(JSON, default=list)   # [{name, count, relationship_type, context}, ...]

    __table_args__ = (Index("idx_uploads_org", "org_id"), Index("idx_uploads_status", "status"))


class Unsubscribe(Base):
    __tablename__ = "unsubscribes"
    id = Column(String(36), primary_key=True, default=uid)
    email = Column(String, unique=True)
    token = Column(String)
    unsubscribed_at = Column(DateTime, default=datetime.utcnow)


# ─────────────────────────────────────────────────────────────
#  SEQUENCE / JOURNEY ENGINE  (Enterprise Blueprint Module 08 —
#  "the core of subsuming the drip", MASTER_CONSOLIDATION_PLAN §5)
#
#  Ports decimal_abm/abm_engine/workflow/ (Phase 1 sequencing) onto
#  DRIP's ORM Person/Organization model. ADDITIVE ONLY — four new
#  tables, no change to any existing column. Reproduces the proven
#  default cadence (5 touches / 3-day gaps) as explicit, editable
#  data instead of a hardcoded constant, and enforces the same
#  compliance gates (do_not_contact / consent / replied / active)
#  plus the account-centric pause rule (ACC-001: one reply pauses
#  every enrollment at that organization).
# ─────────────────────────────────────────────────────────────
class SequenceDefinition(Base):
    """A named multi-touch cadence. relationship_type=NULL is the default
    sequence; a non-NULL value lets a specific OrgTypeTag / PersonRelationship
    type (e.g. 'vendor', 'connector') have its own cadence, exactly as
    decimal_abm's sequence_for_relationship_type() selected."""
    __tablename__ = "sequence_definitions"
    id = Column(String(36), primary_key=True, default=uid)
    name = Column(String, nullable=False, unique=True)
    relationship_type = Column(String, nullable=True)   # NULL = default cadence
    description = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    steps = relationship("SequenceStep", back_populates="sequence",
                         cascade="all, delete-orphan", order_by="SequenceStep.step_number")


class SequenceStep(Base):
    """One touch in a sequence. channel is free-ish: email / linkedin / both /
    whatsapp / phone. wait_days_after_previous is the cooldown before this step
    fires relative to the previous step's execution (step 1 fires relative to
    enrolment)."""
    __tablename__ = "sequence_steps"
    id = Column(String(36), primary_key=True, default=uid)
    sequence_id = Column(String(36), ForeignKey("sequence_definitions.id"), nullable=False)
    step_number = Column(Integer, nullable=False)         # 1-based
    channel = Column(String, default="email")
    wait_days_after_previous = Column(Integer, default=3)
    template_id = Column(String(36), ForeignKey("templates.id"), nullable=True)
    is_final = Column(Boolean, default=False)
    __table_args__ = (
        UniqueConstraint("sequence_id", "step_number"),
        Index("idx_seqstep_seq", "sequence_id"),
    )
    sequence = relationship("SequenceDefinition", back_populates="steps")


class SequenceEnrollment(Base):
    """A person moving through a sequence. current_step is the last COMPLETED
    step (0 = enrolled but nothing sent yet); the next step to fire is
    current_step + 1. org_id is denormalized from the person at enrol time so
    the account-centric pause (ACC-001) can pause every enrollment at an org in
    one query without joining through persons."""
    __tablename__ = "sequence_enrollments"
    id = Column(String(36), primary_key=True, default=uid)
    sequence_id = Column(String(36), ForeignKey("sequence_definitions.id"), nullable=False)
    person_id = Column(String(36), ForeignKey("persons.id"), nullable=False)
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=True)

    current_step = Column(Integer, default=0)
    status = Column(String, default="ACTIVE")     # ACTIVE / PAUSED / COMPLETED / EXITED
    pause_reason = Column(String)

    enrolled_at = Column(DateTime, default=datetime.utcnow)
    last_step_at = Column(DateTime)               # when the current_step was executed
    next_run_at = Column(DateTime)                # computed: when step current_step+1 is due
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("person_id", "sequence_id"),
        Index("idx_enroll_status", "status"),
        Index("idx_enroll_org", "org_id"),
        Index("idx_enroll_person", "person_id"),
    )


class SequenceEnrollmentEvent(Base):
    """Append-only audit of what happened to an enrollment — enrolled,
    step_executed, advanced, paused, resumed, completed, exited. Mirrors the
    universal-activity discipline so a person's sequence history is fully
    reconstructable (Blueprint Module 08 journey_event)."""
    __tablename__ = "sequence_enrollment_events"
    id = Column(String(36), primary_key=True, default=uid)
    enrollment_id = Column(String(36), ForeignKey("sequence_enrollments.id"), nullable=False)
    step_number = Column(Integer)
    event_type = Column(String, nullable=False)   # enrolled/step_executed/advanced/paused/resumed/completed/exited/blocked
    detail = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (Index("idx_seqevent_enroll", "enrollment_id"),)
