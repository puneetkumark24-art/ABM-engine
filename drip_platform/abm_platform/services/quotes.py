"""
quotes.py — Sprint 2: Products, Price Books, Quotes (CPQ), money-correct.

All amounts are integer minor units (halalas/cents) — never floats, never free
text — fixing the audit's money-as-text finding. Quote totals are recomputed
from line items on every mutation.
"""
from __future__ import annotations
import re
from sqlalchemy.orm import Session
import models
import models_crm2 as m2

_NUM = re.compile(r"[\d.]+")


def to_minor(text_or_num, default_multiplier: int = 100) -> int:
    """Parse 'SAR 2.5M' / '500k' / 1000000 / 25.50 into integer minor units."""
    if isinstance(text_or_num, (int, float)):
        return int(round(float(text_or_num) * default_multiplier))
    t = str(text_or_num or "").lower().replace(",", "")
    m = _NUM.search(t)
    if not m:
        return 0
    val = float(m.group())
    if "m" in t or "million" in t:
        val *= 1_000_000
    elif "k" in t:
        val *= 1_000
    return int(round(val * default_multiplier))


def format_minor(minor: int, currency: str = "SAR") -> str:
    return f"{currency} {minor / 100:,.2f}"


# ── catalog ──────────────────────────────────────────────────
def create_product(db: Session, name: str, sku: str | None = None,
                   description: str = "") -> m2.Product:
    p = m2.Product(name=name, sku=sku, description=description)
    db.add(p); db.commit()
    return p


def create_price_book(db: Session, name: str, currency: str = "SAR",
                     is_default: bool = False) -> m2.PriceBook:
    pb = m2.PriceBook(name=name, currency=currency, is_default=is_default)
    db.add(pb); db.commit()
    return pb


def set_price(db: Session, price_book_id: str, product_id: str,
              unit_amount_minor: int, currency: str = "SAR") -> m2.PriceBookEntry:
    e = (db.query(m2.PriceBookEntry)
         .filter_by(price_book_id=price_book_id, product_id=product_id).first())
    if e is None:
        e = m2.PriceBookEntry(price_book_id=price_book_id, product_id=product_id,
                              unit_amount_minor=unit_amount_minor, currency=currency)
        db.add(e)
    else:
        e.unit_amount_minor = unit_amount_minor
    db.commit()
    return e


# ── quotes ───────────────────────────────────────────────────
def create_quote(db: Session, name: str, org_id: str | None = None,
                 opportunity_id: str | None = None, currency: str = "SAR") -> m2.Quote:
    q = m2.Quote(name=name, org_id=org_id, opportunity_id=opportunity_id, currency=currency)
    db.add(q); db.commit()
    return q


def add_line(db: Session, quote_id: str, description: str, quantity: int,
             unit_amount_minor: int, product_id: str | None = None) -> m2.QuoteLineItem:
    li = m2.QuoteLineItem(quote_id=quote_id, product_id=product_id, description=description,
                          quantity=quantity, unit_amount_minor=unit_amount_minor,
                          line_total_minor=quantity * unit_amount_minor)
    db.add(li); db.flush()
    _recompute(db, quote_id)
    db.commit()
    return li


def add_product_line(db: Session, quote_id: str, product_id: str, quantity: int,
                     price_book_id: str) -> m2.QuoteLineItem:
    """Add a line pulling the unit price from a price book."""
    entry = (db.query(m2.PriceBookEntry)
             .filter_by(price_book_id=price_book_id, product_id=product_id).first())
    if entry is None:
        raise ValueError("product not in price book")
    prod = db.get(m2.Product, product_id)
    return add_line(db, quote_id, prod.name if prod else "item", quantity,
                    entry.unit_amount_minor, product_id=product_id)


def set_discount_tax(db: Session, quote_id: str, discount_minor: int = 0,
                     tax_minor: int = 0) -> m2.Quote:
    q = db.get(m2.Quote, quote_id)
    q.discount_minor = discount_minor
    q.tax_minor = tax_minor
    _recompute(db, quote_id)
    db.commit()
    return q


def _recompute(db: Session, quote_id: str) -> None:
    q = db.get(m2.Quote, quote_id)
    lines = db.query(m2.QuoteLineItem).filter_by(quote_id=quote_id).all()
    subtotal = sum(li.line_total_minor or 0 for li in lines)
    q.subtotal_minor = subtotal
    q.total_minor = subtotal - (q.discount_minor or 0) + (q.tax_minor or 0)


def quote_summary(db: Session, quote_id: str) -> dict:
    q = db.get(m2.Quote, quote_id)
    lines = db.query(m2.QuoteLineItem).filter_by(quote_id=quote_id).all()
    return {"quote": q.name, "status": q.status, "currency": q.currency,
            "lines": len(lines), "subtotal": format_minor(q.subtotal_minor, q.currency),
            "discount": format_minor(q.discount_minor, q.currency),
            "tax": format_minor(q.tax_minor, q.currency),
            "total": format_minor(q.total_minor, q.currency),
            "total_minor": q.total_minor}
