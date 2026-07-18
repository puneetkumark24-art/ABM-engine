"""
Sprint 2 remediation — INTEGRATION tests for the CRM2 REST API through the real
FastAPI app + TenantMiddleware (not just service unit calls). File-based SQLite
so TestClient's worker thread shares the DB. Verifies status codes, validation
(422), not-found (404), and money-correct quote math end to end over HTTP.
"""
import os
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

_DBFILE = os.path.join(tempfile.gettempdir(), "drip_crm2_api.db")
if os.path.exists(_DBFILE):
    os.remove(_DBFILE)
os.environ["DATABASE_URL"] = f"sqlite:///{_DBFILE}"
os.environ["AUTH_ENFORCED"] = "false"  # authz proven separately in test_sprint1_platform

from fastapi.testclient import TestClient  # noqa: E402
from database import Base, engine  # noqa: E402
import models, models_ext, models_p10, models_p11, models_p12, models_audit, models_crm2  # noqa: E402,F401
import audit_trail  # noqa: E402
from main import app  # noqa: E402

Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)
audit_trail.register()
client = TestClient(app)

_results = []


def check(name, cond):
    _results.append((name, bool(cond))); print(("PASS" if cond else "FAIL"), "-", name)


def run():
    # ── custom objects ──
    r = client.post("/crm/objects", json={"key": "regulatory_case", "label": "Regulatory Case",
        "schema": [{"key": "case_no", "type": "text", "required": True},
                   {"key": "severity", "type": "enum", "options": ["low", "high"]}]})
    check("POST /crm/objects -> 201", r.status_code == 201)
    check("object echoes schema", r.json()["schema"][0]["key"] == "case_no")

    r = client.get("/crm/objects")
    check("GET /crm/objects lists 1", len(r.json()) == 1)

    r = client.post("/crm/objects/regulatory_case/records",
                    json={"data": {"case_no": "RC-1", "severity": "high"}})
    check("POST record -> 201", r.status_code == 201)
    rec_id = r.json()["id"]

    r = client.post("/crm/objects/regulatory_case/records",
                    json={"data": {"severity": "high"}})  # missing required
    check("missing required -> 422", r.status_code == 422)

    r = client.post("/crm/objects/regulatory_case/records",
                    json={"data": {"case_no": "x", "severity": "extreme"}})  # bad enum
    check("bad enum -> 422", r.status_code == 422)

    r = client.patch(f"/crm/records/{rec_id}", json={"data": {"severity": "low"}})
    check("PATCH record -> 200 + updated", r.status_code == 200 and r.json()["data"]["severity"] == "low")

    r = client.patch("/crm/records/does-not-exist", json={"data": {"severity": "low"}})
    check("PATCH missing record -> 404", r.status_code == 404)

    r = client.get("/crm/objects/regulatory_case/records")
    check("GET records lists 1", len(r.json()) == 1)

    # ── products / price book / quote (money-correct over HTTP) ──
    pid = client.post("/crm/products", json={"name": "Vahana License", "sku": "VHN-1"}).json()["id"]
    pbid = client.post("/crm/price-books", json={"name": "KSA List", "currency": "SAR", "is_default": True}).json()["id"]
    r = client.post(f"/crm/price-books/{pbid}/prices",
                    json={"product_id": pid, "unit_amount_minor": 100_000_00})
    check("set price -> 200", r.status_code == 200)

    qid = client.post("/crm/quotes", json={"name": "Q-1"}).json()["id"]
    r = client.post(f"/crm/quotes/{qid}/product-lines",
                    json={"product_id": pid, "quantity": 3, "price_book_id": pbid})
    check("add product line -> 201", r.status_code == 201)
    client.post(f"/crm/quotes/{qid}/lines",
                json={"description": "Onboarding", "quantity": 1, "unit_amount_minor": 50_000_00})
    r = client.post(f"/crm/quotes/{qid}/discount-tax", json={"discount_minor": 10_000_00})
    body = r.json()
    check("quote subtotal SAR 350,000.00", body["subtotal"] == "SAR 350,000.00")
    check("quote total SAR 340,000.00 after discount", body["total"] == "SAR 340,000.00")

    r = client.get(f"/crm/quotes/{qid}")
    check("GET quote summary -> 200", r.status_code == 200 and r.json()["lines"] == 2)

    r = client.post(f"/crm/quotes/{qid}/product-lines",
                    json={"product_id": pid, "quantity": 1, "price_book_id": "no-book"})
    check("product not in book -> 422", r.status_code == 422)

    r = client.get("/crm/quotes/nope")
    check("GET missing quote -> 404", r.status_code == 404)

    # ── property history over HTTP (audit-backed) ──
    org_id = client.post("/organizations", json={"canonical_name": "Quote Bank"}).json().get("id") \
        if client.post("/organizations", json={"canonical_name": "probe"}).status_code in (200, 201) else None
    # history endpoint should always respond 200 with a list (may be empty depending on org route)
    r = client.get("/crm/records/organizations/whatever/history")
    check("history endpoint -> 200 list", r.status_code == 200 and isinstance(r.json(), list))

    # ── OpenAPI advertises the new routes ──
    spec = client.get("/openapi.json").json()
    paths = spec["paths"]
    for p in ["/crm/objects", "/crm/quotes/{quote_id}", "/crm/records/{record_id}"]:
        check(f"OpenAPI documents {p}", p in paths)

    passed = sum(1 for _, ok in _results if ok); total = len(_results)
    print(f"\n{passed}/{total} checks passed  [CRM2 REST API integration]")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)


def test_crm2_api():
    assert run()
