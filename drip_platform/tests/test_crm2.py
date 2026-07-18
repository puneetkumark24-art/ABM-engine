"""
Sprint 2 test — custom objects, money-correct quotes/CPQ, forecast on
amount_minor, and property history over the audit trail. SQLite + PostgreSQL.
"""
import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from database import Base, engine, SessionLocal  # noqa: E402
import models, models_ext, models_p10, models_p11, models_p12, models_audit, models_crm2 as m2  # noqa: E402,F401
import audit_trail  # noqa: E402
from abm_platform.services import custom_objects as co, quotes, property_history, pipeline  # noqa: E402

_results = []


def check(name, cond):
    _results.append((name, bool(cond))); print(("PASS" if cond else "FAIL"), "-", name)


def run():
    Base.metadata.drop_all(bind=engine); Base.metadata.create_all(bind=engine)
    audit_trail.register()
    db = SessionLocal()

    # ── CUSTOM OBJECTS ──
    co.define_object(db, "regulatory_case", "Regulatory Case",
                     schema=[{"key": "case_no", "type": "text", "required": True},
                             {"key": "severity", "type": "enum", "options": ["low", "high"]},
                             {"key": "open_since", "type": "date"},
                             {"key": "fine_amount", "type": "number"}])
    check("CO object type defined", db.query(m2.CustomObjectDef).filter_by(key="regulatory_case").count() == 1)
    rec = co.create_record(db, "regulatory_case",
                           {"case_no": "RC-1", "severity": "high", "fine_amount": 50000})
    check("CO record created + validated", rec.data["case_no"] == "RC-1" and rec.data["fine_amount"] == 50000.0)
    try:
        co.create_record(db, "regulatory_case", {"severity": "high"})  # missing required
        check("CO required field enforced", False)
    except ValueError:
        check("CO required field enforced", True)
    try:
        co.create_record(db, "regulatory_case", {"case_no": "x", "severity": "extreme"})  # bad enum
        check("CO enum validation", False)
    except ValueError:
        check("CO enum validation", True)
    try:
        co.create_record(db, "regulatory_case", {"case_no": "x", "unknown_field": 1})
        check("CO unknown field rejected", False)
    except ValueError:
        check("CO unknown field rejected", True)
    co.update_record(db, rec.id, {"severity": "low"})
    check("CO record update (partial)", db.get(m2.CustomObjectRecord, rec.id).data["severity"] == "low")
    check("CO list records", len(co.list_records(db, "regulatory_case")) == 1)

    # ── MONEY / QUOTES / CPQ ──
    check("MONEY parse 2.5M", quotes.to_minor("SAR 2.5M") == 250_000_000)
    check("MONEY parse 500k", quotes.to_minor("500k") == 50_000_000)
    check("MONEY parse decimal", quotes.to_minor(25.50) == 2550)
    check("MONEY format", quotes.format_minor(250_000_000, "SAR") == "SAR 2,500,000.00")

    prod = quotes.create_product(db, "Vahana License", sku="VHN-1")
    pb = quotes.create_price_book(db, "KSA List", currency="SAR", is_default=True)
    quotes.set_price(db, pb.id, prod.id, unit_amount_minor=100_000_00)  # SAR 100,000.00
    org = models.Organization(canonical_name="Quote Bank"); db.add(org); db.commit()
    q = quotes.create_quote(db, "Q-1", org_id=org.id)
    quotes.add_product_line(db, q.id, prod.id, quantity=3, price_book_id=pb.id)  # 3 x 100k
    quotes.add_line(db, q.id, "Onboarding", quantity=1, unit_amount_minor=50_000_00)
    quotes.set_discount_tax(db, q.id, discount_minor=10_000_00, tax_minor=0)
    s = quotes.quote_summary(db, q.id)
    check("QUOTE subtotal = 3x100k + 50k", s["subtotal"] == "SAR 350,000.00")
    check("QUOTE total = subtotal - discount", s["total"] == "SAR 340,000.00")
    check("QUOTE line count", s["lines"] == 2)

    # ── FORECAST uses amount_minor (money-correct) ──
    pl = pipeline.create_pipeline(db, "P", is_default=True)
    opp = models.Opportunity(org_id=org.id, amount_minor=250_000_000)  # SAR 2.5M
    db.add(opp); db.commit()
    pipeline.assign_deal(db, opp.id, pl.id, "Qualified")  # prob 0.25
    fc = pipeline.forecast(db, pl.id)
    check("FORECAST uses amount_minor (best case 2.5M)", abs(fc["best_case"] - 2_500_000) < 1)
    check("FORECAST weighted = 2.5M x 0.25", abs(fc["weighted"] - 625_000) < 1)
    # legacy free-text still works when amount_minor unset
    opp2 = models.Opportunity(org_id=org.id, estimated_value="1M")
    db.add(opp2); db.commit()
    pipeline.assign_deal(db, opp2.id, pl.id)
    fc2 = pipeline.forecast(db, pl.id)
    check("FORECAST falls back to legacy text", abs(fc2["best_case"] - 3_500_000) < 1)

    # ── PROPERTY HISTORY (over audit trail) ──
    org.canonical_name = "Quote Bank v2"; db.commit()
    org.website = "https://x.invalid"; db.commit()
    hist = property_history.record_history(db, "organizations", org.id)
    check("HISTORY records multiple changes", len(hist) >= 2)
    fh = property_history.field_history(db, "organizations", org.id, "canonical_name")
    check("HISTORY field timeline: insert + rename",
          any(h.get("value") == "Quote Bank" for h in fh)
          and any(h.get("from") == "Quote Bank" and h.get("value") == "Quote Bank v2" for h in fh))

    passed = sum(1 for _, ok in _results if ok); total = len(_results)
    is_pg = db.bind.dialect.name == "postgresql"
    print(f"\n{passed}/{total} checks passed  [DB: {'postgresql' if is_pg else 'sqlite'}]")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)


def test_crm2():
    assert run()
