"""schemas.py — Pydantic API schemas (subset covering the routers actually exposed)."""
from __future__ import annotations
from datetime import datetime
from typing import Optional, List, Any
from pydantic import BaseModel, ConfigDict


class OrgTypeTagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    type_tag: str


class OrganizationBase(BaseModel):
    canonical_name: str
    name_ar: Optional[str] = None
    short_name: Optional[str] = None
    country: Optional[str] = "Saudi Arabia"
    website: Optional[str] = None
    core_banking: Optional[str] = None
    parent_org_id: Optional[str] = None


class OrganizationCreate(OrganizationBase):
    type_tags: List[str] = []


class OrganizationOut(OrganizationBase):
    model_config = ConfigDict(from_attributes=True)
    id: str
    is_active: bool
    created_at: datetime
    type_tags: List[OrgTypeTagOut] = []


class AccountIntelligenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    org_id: str
    tier: str
    priority: str
    lifecycle_status: str
    score: int


class PersonBase(BaseModel):
    full_name: str
    current_org_id: Optional[str] = None
    current_title: Optional[str] = None
    seniority_level: Optional[str] = None
    persona: Optional[str] = None
    primary_email: Optional[str] = None
    linkedin_url: Optional[str] = None


class PersonCreate(PersonBase):
    pass


class PersonOut(PersonBase):
    model_config = ConfigDict(from_attributes=True)
    id: str
    tier: str
    is_active: bool
    created_at: datetime


class SignalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    org_id: Optional[str]
    signal_type: Optional[str]
    title: Optional[str]
    urgency: str
    created_at: datetime


class OpportunityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    org_id: str
    product_id: Optional[str]
    stage: str
    probability: int
    estimated_value: Optional[str]
