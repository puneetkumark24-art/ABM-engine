"""
Operator console e2e — serves /app and exercises every API flow the console's
buttons call, through the real FastAPI app: signal ingest+score, committee
infer+coverage, journey create/enroll/tick, reply handling, hot leads, step A/B,
analytics, API keys, webhooks, PDPL export/consent/erase.
"""
import os
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

_DBFILE = os.path.join(tempfile.gettempdir(), "drip_console.db")
if os.path.exists(_DBFILE):
    os.remove(_DBFILE)
os.environ["DATABASE_URL"] = f"sqlite:///{_DBFILE}"
os.environ["AUTH_ENFORCED"] = "false"

from fastapi.testclient import TestClient  # noqa: E402
from database import Base, engine, SessionLocal  # noqa: E402
import models, models_ext, models_p10, models_p11, models_p12  # noqa: E402,F401
import models_audit, models_crm2, models_s3, models_s6, models_s8  # noqa: E402,F401
from main import app  # noqa: E402

Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)
client = TestClient(app)
_results = []


def check(name, cond):
    _results.append((name, bool(cond))); print(("PASS" if cond else "FAIL"), "-", name)


def run():
    # console page serves (moved to /legacy after the DRIP OS shell took "/")
    r = client.get("/legacy")
    check("GET /legacy serves console", r.status_code == 200 and "Operator Console" in r.text)
    for marker in ["Signals", "Committee", "Journeys", "Engagement", "Analytics",
                   "Admin", "Compliance"]:
        check(f"console has {marker} tab", marker in r.text)

    # seed an org + people through the DB (console assumes existing CRM data)
    db = SessionLocal()
    org = models.Organization(canonical_name="Console Bank"); db.add(org); db.commit()
    p1 = models.Person(current_org_id=org.id, full_name="CFO", current_title="CFO",
                       primary_email="cfo@bank.sa", is_active=True, replied=True)
    p2 = models.Person(current_org_id=org.id, full_name="CTO", current_title="Group CTO",
                       primary_email="cto@bank.sa", is_active=True)
    db.add_all([p1, p2]); db.commit()

    # signals flow
    r = client.post("/abm/signals/ingest", json={"org_id": org.id, "signal_type": "tender",
        "source": "SAMA", "title": "Core RFP"})
    check("signal ingest via API", r.status_code == 200 and r.json()["created"] is True)
    r2 = client.post("/abm/signals/ingest", json={"org_id": org.id, "signal_type": "tender",
        "source": "SAMA", "title": "Core RFP"})
    check("signal dedup via API", r2.json()["deduped"] is True)
    r = client.post(f"/abm/accounts/{org.id}/score")
    check("account score via API", r.status_code == 200 and "tier" in r.json())

    # committee flow
    client.post(f"/abm/committee/{org.id}/infer")
    r = client.get(f"/abm/committee/{org.id}/coverage")
    cov = r.json()
    check("committee coverage via API", r.status_code == 200 and cov["members"] == 2)

    # journeys flow
    nodes = [{"id": "n1", "type": "send", "next": "n2"},
             {"id": "n2", "type": "exit"}]
    r = client.post("/mkt/journeys", json={"name": "console-j", "nodes": nodes})
    jid = r.json()["id"]
    check("journey create via API", r.status_code == 201)
    r = client.post(f"/mkt/journeys/{jid}/enroll", json={"person_id": p1.id})
    check("journey enroll via API", r.status_code == 201)
    r = client.post("/mkt/journeys/tick")
    check("journey tick via API", r.status_code == 200 and r.json()["sends"] >= 1)
    r = client.get(f"/mkt/journeys/{jid}/enrollments")
    check("enrollments listed", len(r.json()) == 1)

    # engagement flow
    r = client.post("/sales/replies", json={"person_id": p2.id, "text": "not interested, unsubscribe"})
    check("reply handled via API", r.json()["action"] == "suppressed")
    client.post("/sales/steps/console-step/variants",
                json={"variants": [{"key": "A"}, {"key": "B"}]})
    r = client.get("/sales/steps/console-step/pick")
    check("step A/B pick via API", r.json()["variant_key"] in ("A", "B"))
    r = client.get("/sales/hot-leads")
    check("hot leads via API", r.status_code == 200)

    # analytics flow
    r = client.get("/analytics/timeseries?event_type=signup&since_days=7")
    check("timeseries via API", r.status_code == 200 and isinstance(r.json(), list))
    r = client.get("/analytics/cohort-retention?cohort_event=signup&return_event=active")
    check("cohorts via API", r.status_code == 200 and "cohorts" in r.json())

    # admin flow
    r = client.post("/dev/api-keys", json={"name": "console", "scopes": []})
    check("api key via API", r.status_code == 201 and r.json()["api_key"].startswith("dk_"))
    r = client.post("/dev/webhooks", json={"url": "https://x.invalid/h", "event_types": []})
    check("webhook sub via API", r.status_code == 201)

    # compliance flow
    r = client.get(f"/compliance/subjects/{p1.id}/export")
    check("PDPL export via API", r.status_code == 200 and r.json()["pii"]["primary_email"] == "cfo@bank.sa")
    r = client.post(f"/compliance/subjects/{p1.id}/consent", json={"status": "granted"})
    check("consent via API", r.status_code == 200)
    r = client.post(f"/compliance/subjects/{p1.id}/erase")
    check("PDPL erase via API", r.status_code == 200 and "primary_email" in r.json()["fields_scrubbed"])

    passed = sum(1 for _, ok in _results if ok); total = len(_results)
    print(f"\n{passed}/{total} checks passed  [operator console e2e]")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)


def test_operator_console():
    assert run()
