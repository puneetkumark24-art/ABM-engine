"""
Master-data e2e — org/person PATCH + soft-delete + restore, bulk CSV-style
import with dedup, CSV export, vendors ecosystem endpoint, and the OS screens'
search/CRUD/import markers.
"""
import os
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

_DBFILE = os.path.join(tempfile.gettempdir(), "drip_md.db")
if os.path.exists(_DBFILE):
    os.remove(_DBFILE)
os.environ["DATABASE_URL"] = f"sqlite:///{_DBFILE}"
os.environ["AUTH_ENFORCED"] = "false"

from fastapi.testclient import TestClient  # noqa: E402
from database import Base, engine, SessionLocal  # noqa: E402
import models, models_ext, models_p10, models_p11, models_p12  # noqa: E402,F401
import models_audit, models_crm2, models_s3, models_s6, models_s8  # noqa: E402,F401
import models_llm, models_collectors, models_segments, models_final  # noqa: E402,F401
from main import app  # noqa: E402

Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)
client = TestClient(app)
_results = []


def check(name, cond):
    _results.append((name, bool(cond))); print(("PASS" if cond else "FAIL"), "-", name)


def run():
    db = SessionLocal()

    # ── org CRUD ──
    r = client.post("/organizations", json={"canonical_name": "Edit Bank", "country": "SA"})
    oid = r.json()["id"]
    r = client.patch(f"/organizations/{oid}", json={"fields": {"website": "https://editbank.sa",
                                                              "core_banking": "T24"}})
    check("org PATCH updates fields", r.status_code == 200 and "website" in r.json()["updated"])
    check("org PATCH rejects unknown field",
          client.patch(f"/organizations/{oid}", json={"fields": {"id": "hack"}}).status_code == 422)
    r = client.delete(f"/organizations/{oid}")
    check("org soft delete", r.json()["deleted"] == "soft")
    db.expire_all()
    check("org still in DB (soft)", db.get(models.Organization, oid).is_active is False)
    r = client.patch(f"/organizations/{oid}", json={"fields": {"is_active": True}})
    check("org restore via PATCH", r.status_code == 200)

    # ── org bulk import + dedup + export ──
    r = client.post("/import/organizations", json={"rows": [
        {"canonical_name": "Bulk Bank A", "country": "SA"},
        {"canonical_name": "Bulk Bank B", "country": "AE"},
        {"canonical_name": "Edit Bank"},          # duplicate
        {"country": "SA"}]})                       # missing name
    d = r.json()
    check("org import creates 2, skips dup, flags error",
          d["created"] == 2 and d["skipped_duplicates"] == 1 and d["errors"] == 1)
    r = client.get("/export/organizations")
    check("org CSV export", r.status_code == 200 and "Bulk Bank A" in r.text
          and r.text.startswith("id,canonical_name"))

    # ── person CRUD + import ──
    r = client.post("/import/persons", json={"org_name": "Edit Bank", "rows": [
        {"full_name": "Import CTO", "current_title": "CTO", "email": "cto@editbank.sa"},
        {"full_name": "Import CTO", "email": "cto@editbank.sa"},   # dup by email
        {"name": "Import CFO", "title_ignored": "x"}]})
    d = r.json()
    check("person import creates 2, dedups 1", d["created"] == 2 and d["skipped_duplicates"] == 1)
    p = db.query(models.Person).filter_by(primary_email="cto@editbank.sa").first()
    check("imported person linked to org", p is not None and p.current_org_id == oid)

    r = client.patch(f"/persons/{p.id}", json={"fields": {"tier": "1", "next_step": "call Sunday"}})
    check("person PATCH", r.status_code == 200)
    r = client.delete(f"/persons/{p.id}")
    check("person soft delete", r.json()["deleted"] == "soft")
    r = client.get("/export/persons")
    check("person CSV export", "Import CFO" in r.text)

    # audit trail captured the edits (version history requirement)
    hist = client.get(f"/crm/records/persons/{p.id}/history").json()
    check("edit history in audit trail", any("tier" in (h.get("changed") or []) for h in hist))

    # ── vendors ecosystem ──
    bank = db.query(models.Organization).filter_by(canonical_name="Bulk Bank A").first()
    vend = models.Organization(canonical_name="Vendor Corp"); db.add(vend); db.commit()
    db.add(models.OrgRelationship(from_org_id=vend.id, to_org_id=bank.id,
                                  relationship_type="vendor_of", confidence=0.9))
    db.add(models.VendorIntelligence(org_id=vend.id, products="Core banking middleware"))
    db.commit()
    r = client.get("/abm/vendors")
    v = r.json()
    check("vendors endpoint lists vendor", any(x["name"] == "Vendor Corp" for x in v))
    vc = next(x for x in v if x["name"] == "Vendor Corp")
    check("vendor edge to bank", vc["edges"][0]["to"] == "Bulk Bank A")
    check("vendor intelligence attached", "Core banking" in str(vc.get("intelligence", {})))

    # ── OS screens carry search + CRUD + import ──
    html = client.get("/").text
    for marker in ["Search banks", "Search people", "Search vendors", "+ New organization",
                   "+ New contact", "Import CSV", "Export CSV", "csvUp", "aEdit(",
                   "pEdit(", "aDel(", "pDel(", "Vendors"]:
        check(f"OS has {marker}", marker in html)

    passed = sum(1 for _, ok in _results if ok); total = len(_results)
    print(f"\n{passed}/{total} checks passed  [master data e2e]")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)


def test_master_data():
    assert run()
