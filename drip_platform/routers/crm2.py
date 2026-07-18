"""
routers/crm2.py — Sprint 2 remediation: the REST surface for the CRM2 services
(custom objects, quotes/CPQ, property history) that previously existed only as
un-mounted service functions (Review Board blocker #1).

Mounted under /crm/* so it inherits the existing route-level authorization
(SCOPE_POLICY: /crm -> crm.read) and the tenant GUC set by get_db. Every handler
translates domain ValueError -> 422 and missing entities -> 404, matching the
house style in routers/crm_marketing_ext.py.
"""
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from abm_platform.services import custom_objects as co, quotes as q, property_history as ph

router = APIRouter(prefix="/crm", tags=["crm2"])


# ══════════════════════ CUSTOM OBJECTS ══════════════════════
class FieldDef(BaseModel):
    key: str
    type: str
    required: bool = False
    options: Optional[list] = None


class ObjectDefReq(BaseModel):
    key: str
    label: str
    schema_: list[FieldDef] = Field(alias="schema")
    plural_label: Optional[str] = None

    model_config = {"populate_by_name": True}


@router.post("/objects", status_code=201)
def define_object(req: ObjectDefReq, db: Session = Depends(get_db)):
    schema = [f.model_dump(exclude_none=True) for f in req.schema_]
    try:
        obj = co.define_object(db, req.key, req.label, schema, req.plural_label)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"key": obj.key, "label": obj.label, "plural_label": obj.plural_label,
            "schema": obj.schema}


@router.get("/objects")
def list_objects(db: Session = Depends(get_db)):
    import models_crm2 as m2
    return [{"key": o.key, "label": o.label, "schema": o.schema}
            for o in db.query(m2.CustomObjectDef).all()]


class RecordReq(BaseModel):
    data: dict


@router.post("/objects/{object_key}/records", status_code=201)
def create_record(object_key: str, req: RecordReq, db: Session = Depends(get_db)):
    try:
        rec = co.create_record(db, object_key, req.data)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"id": rec.id, "object_key": rec.object_key, "data": rec.data}


@router.get("/objects/{object_key}/records")
def list_records(object_key: str, limit: int = 100, db: Session = Depends(get_db)):
    return [{"id": r.id, "data": r.data}
            for r in co.list_records(db, object_key, limit)]


@router.patch("/records/{record_id}")
def update_record(record_id: str, req: RecordReq, db: Session = Depends(get_db)):
    try:
        rec = co.update_record(db, record_id, req.data)
    except ValueError as e:
        code = 404 if "not found" in str(e) else 422
        raise HTTPException(status_code=code, detail=str(e))
    return {"id": rec.id, "data": rec.data}


@router.delete("/records/{record_id}")
def delete_record(record_id: str, db: Session = Depends(get_db)):
    if not co.delete_record(db, record_id):
        raise HTTPException(status_code=404, detail="record not found")
    return {"deleted": True, "id": record_id}


# ══════════════════════ PRODUCTS / PRICE BOOKS ══════════════════════
class ProductReq(BaseModel):
    name: str
    sku: Optional[str] = None
    description: str = ""


@router.post("/products", status_code=201)
def create_product(req: ProductReq, db: Session = Depends(get_db)):
    p = q.create_product(db, req.name, sku=req.sku, description=req.description)
    return {"id": p.id, "name": p.name, "sku": p.sku}


class PriceBookReq(BaseModel):
    name: str
    currency: str = "SAR"
    is_default: bool = False


@router.post("/price-books", status_code=201)
def create_price_book(req: PriceBookReq, db: Session = Depends(get_db)):
    pb = q.create_price_book(db, req.name, currency=req.currency, is_default=req.is_default)
    return {"id": pb.id, "name": pb.name, "currency": pb.currency}


class PriceReq(BaseModel):
    product_id: str
    unit_amount_minor: int = Field(ge=0)
    currency: str = "SAR"


@router.post("/price-books/{price_book_id}/prices")
def set_price(price_book_id: str, req: PriceReq, db: Session = Depends(get_db)):
    e = q.set_price(db, price_book_id, req.product_id, req.unit_amount_minor, req.currency)
    return {"price_book_id": price_book_id, "product_id": req.product_id,
            "unit_amount_minor": e.unit_amount_minor}


# ══════════════════════ QUOTES (CPQ) ══════════════════════
class QuoteReq(BaseModel):
    name: str
    org_id: Optional[str] = None
    opportunity_id: Optional[str] = None
    currency: str = "SAR"


@router.post("/quotes", status_code=201)
def create_quote(req: QuoteReq, db: Session = Depends(get_db)):
    quote = q.create_quote(db, req.name, org_id=req.org_id,
                           opportunity_id=req.opportunity_id, currency=req.currency)
    return {"id": quote.id, "name": quote.name, "status": quote.status}


class LineReq(BaseModel):
    description: str
    quantity: int = Field(ge=1)
    unit_amount_minor: int = Field(ge=0)
    product_id: Optional[str] = None


@router.post("/quotes/{quote_id}/lines", status_code=201)
def add_line(quote_id: str, req: LineReq, db: Session = Depends(get_db)):
    if db.get(_Quote(), quote_id) is None:
        raise HTTPException(status_code=404, detail="quote not found")
    li = q.add_line(db, quote_id, req.description, req.quantity,
                    req.unit_amount_minor, product_id=req.product_id)
    return {"line_id": li.id, "line_total_minor": li.line_total_minor}


class ProductLineReq(BaseModel):
    product_id: str
    quantity: int = Field(ge=1)
    price_book_id: str


@router.post("/quotes/{quote_id}/product-lines", status_code=201)
def add_product_line(quote_id: str, req: ProductLineReq, db: Session = Depends(get_db)):
    if db.get(_Quote(), quote_id) is None:
        raise HTTPException(status_code=404, detail="quote not found")
    try:
        li = q.add_product_line(db, quote_id, req.product_id, req.quantity, req.price_book_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"line_id": li.id, "line_total_minor": li.line_total_minor}


class DiscountTaxReq(BaseModel):
    discount_minor: int = Field(default=0, ge=0)
    tax_minor: int = Field(default=0, ge=0)


@router.post("/quotes/{quote_id}/discount-tax")
def set_discount_tax(quote_id: str, req: DiscountTaxReq, db: Session = Depends(get_db)):
    if db.get(_Quote(), quote_id) is None:
        raise HTTPException(status_code=404, detail="quote not found")
    q.set_discount_tax(db, quote_id, req.discount_minor, req.tax_minor)
    return q.quote_summary(db, quote_id)


@router.get("/quotes/{quote_id}")
def get_quote(quote_id: str, db: Session = Depends(get_db)):
    if db.get(_Quote(), quote_id) is None:
        raise HTTPException(status_code=404, detail="quote not found")
    return q.quote_summary(db, quote_id)


# ══════════════════════ PROPERTY / FIELD HISTORY ══════════════════════
@router.get("/records/{table_name}/{row_id}/history")
def record_history(table_name: str, row_id: str, limit: int = 200,
                   db: Session = Depends(get_db)):
    return ph.record_history(db, table_name, row_id, limit)


@router.get("/records/{table_name}/{row_id}/history/{field}")
def field_history(table_name: str, row_id: str, field: str,
                  db: Session = Depends(get_db)):
    return ph.field_history(db, table_name, row_id, field)


def _Quote():
    import models_crm2 as m2
    return m2.Quote
