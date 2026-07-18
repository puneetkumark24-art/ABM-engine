"""
models_crm2.py — Sprint 2 Enterprise CRM extensions.

Closes audit CRM gaps:
  - Custom OBJECTS (not just custom properties) — dynamic object types + records
  - Money done right — quotes/products use amount_minor (bigint) + currency
  - Quotes / Products / Price Books / Line Items (CPQ foundation)

Additive only. JSONB-friendly (JSON portable to SQLite). tenant_id is added by
the tenancy migration + defaults from the session GUC (Sprint 1).
"""
from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Integer, BigInteger, Boolean, Text, DateTime, ForeignKey,
    JSON, UniqueConstraint, Index
)
from database import Base


def uid() -> str:
    return str(uuid.uuid4())


# ── Custom Objects (dynamic object types) ────────────────────
class CustomObjectDef(Base):
    """A tenant-defined object type (HubSpot custom objects). `schema` is the
    field definition list: [{key,label,type,required,options}]."""
    __tablename__ = "custom_object_defs"
    id = Column(String(36), primary_key=True, default=uid)
    key = Column(String, nullable=False)              # snake_case, unique per tenant
    label = Column(String, nullable=False)
    plural_label = Column(String)
    schema = Column(JSON, default=list)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("key"),)       # per-tenant via RLS


class CustomObjectRecord(Base):
    """An instance of a custom object type. `data` holds the field values
    (validated against the def's schema on write)."""
    __tablename__ = "custom_object_records"
    id = Column(String(36), primary_key=True, default=uid)
    object_key = Column(String, nullable=False)
    data = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (Index("idx_cor_objkey", "object_key"),)


# ── Products / Price Books / Quotes (CPQ, money-correct) ─────
class Product(Base):
    __tablename__ = "crm_products"
    id = Column(String(36), primary_key=True, default=uid)
    sku = Column(String)
    name = Column(String, nullable=False)
    description = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class PriceBook(Base):
    __tablename__ = "price_books"
    id = Column(String(36), primary_key=True, default=uid)
    name = Column(String, nullable=False)
    currency = Column(String(3), default="SAR")
    is_default = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class PriceBookEntry(Base):
    __tablename__ = "price_book_entries"
    id = Column(String(36), primary_key=True, default=uid)
    price_book_id = Column(String(36), ForeignKey("price_books.id"), nullable=False)
    product_id = Column(String(36), ForeignKey("crm_products.id"), nullable=False)
    unit_amount_minor = Column(BigInteger, nullable=False)   # e.g. cents/halalas
    currency = Column(String(3), default="SAR")
    __table_args__ = (UniqueConstraint("price_book_id", "product_id"),)


class Quote(Base):
    __tablename__ = "quotes"
    id = Column(String(36), primary_key=True, default=uid)
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=True)
    opportunity_id = Column(String(36), ForeignKey("opportunities.id"), nullable=True)
    name = Column(String, nullable=False)
    status = Column(String, default="draft")          # draft/sent/accepted/rejected/expired
    currency = Column(String(3), default="SAR")
    subtotal_minor = Column(BigInteger, default=0)
    discount_minor = Column(BigInteger, default=0)
    tax_minor = Column(BigInteger, default=0)
    total_minor = Column(BigInteger, default=0)
    valid_until = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class QuoteLineItem(Base):
    __tablename__ = "quote_line_items"
    id = Column(String(36), primary_key=True, default=uid)
    quote_id = Column(String(36), ForeignKey("quotes.id"), nullable=False)
    product_id = Column(String(36), ForeignKey("crm_products.id"), nullable=True)
    description = Column(String)
    quantity = Column(Integer, default=1)
    unit_amount_minor = Column(BigInteger, default=0)
    line_total_minor = Column(BigInteger, default=0)
    __table_args__ = (Index("idx_qli_quote", "quote_id"),)


CRM2_TABLES = [CustomObjectDef, CustomObjectRecord, Product, PriceBook,
               PriceBookEntry, Quote, QuoteLineItem]
