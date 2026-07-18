"""
Final wave e2e — meetings (schedule/conflict/status/ICS), public preference
center (signed links, categories, unsubscribe-all → suppression), report
builder (filters/group-by/sum), login rate-limiting, and RTL toggle presence.
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

_DBFILE = os.path.join(tempfile.gettempdir(), "drip_final.db")
if os.path.exists(_DBFILE):
    os.remove(_DBFILE)
os.environ["DATABASE_URL"] = f"sqlite:///{_DBFILE}"
os.environ["AUTH_ENFORCED"] = "false"
os.environ["ADMIN_EMAIL"] = "admin@test.sa"
os.environ["ADMIN_PASSWORD"] = "correct-pw"

from fastapi.testclient import TestClient  # noqa: E402
from database import Base, engine, SessionLocal  # noqa: E402
import models, models_ext, models_p10, models_p11, models_p12  # noqa: E402,F401
import models_audit, models_crm2, models_s3, models_s6, models_s8  # noqa: E402,F401
import models_llm, models_collectors, models_segments, models_final  # noqa: E402,F401
from main import app  # noqa: E402
from abm_platform.services import preferences as pf  # noqa: E402

Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)
client = TestClient(app)
_results = []


def check(name, cond):
    _results.append((name, bool(cond))); print(("PASS" if cond else "FAIL"), "-", name)


def run():
    db = SessionLocal()
    org = models.Organization(canonical_name="Meeting Bank"); db.add(org); db.commit()
    p = models.Person(current_org_id=org.id, full_name="Pref Person",
                      primary_email="pp@bank.sa", is_active=True, tier="1")
    db.add(p); db.commit()

    # ══ MEETINGS ══
    t0 = (datetime.utcnow() + timedelta(days=1)).replace(microsecond=0)
    r = client.post("/crm/meetings", json={"title": "Discovery with CTO",
        "starts_at": t0.isoformat(), "duration_minutes": 45, "org_id": org.id,
        "owner": "puneet", "location": "Riyadh HQ", "agenda": "Vahana demo"})
    check("meeting scheduled 201", r.status_code == 201)
    mid = r.json()["id"]

    r = client.post("/crm/meetings", json={"title": "Overlap", "owner": "puneet",
        "starts_at": (t0 + timedelta(minutes=20)).isoformat()})
    check("owner conflict -> 409", r.status_code == 409)

    r = client.post("/crm/meetings", json={"title": "Other rep ok", "owner": "sara",
        "starts_at": (t0 + timedelta(minutes=20)).isoformat()})
    check("no conflict for other owner", r.status_code == 201)

    r = client.get("/crm/meetings/upcoming?owner=puneet")
    check("upcoming lists the meeting", len(r.json()) == 1 and r.json()[0]["id"] == mid)

    r = client.get(f"/crm/meetings/{mid}/ics")
    check("ICS export valid", r.status_code == 200 and "BEGIN:VCALENDAR" in r.text
          and "SUMMARY:Discovery with CTO" in r.text)

    r = client.post(f"/crm/meetings/{mid}/status",
                    json={"status": "completed", "outcome_notes": "went well"})
    check("meeting completed", r.json()["status"] == "completed")
    check("bad status 422", client.post(f"/crm/meetings/{mid}/status",
                                        json={"status": "teleported"}).status_code == 422)

    # ══ PREFERENCE CENTER (public, signed) ══
    link = client.get(f"/crm/persons/{p.id}/pref-link").json()["path"]
    check("pref link generated", link.startswith("/p/prefs/"))
    r = client.get(link)
    check("pref page renders publicly", r.status_code == 200 and "Communication preferences" in r.text)
    check("forged token 403", client.get(f"/p/prefs/{p.id}/deadbeef").status_code == 403)

    r = client.post(link, data={"action": "save", "insights": "on"})
    check("save categories works", r.status_code == 200 and "saved" in r.text.lower())
    check("category persisted (only insights on)",
          pf.get_profile(db, p.id)["categories"] == {"product_updates": False,
              "insights": True, "events": False, "partnership": False})
    check("may_send respects category", pf.may_send(db, p.id, "insights") is True
          and pf.may_send(db, p.id, "events") is False)

    r = client.post(link, data={"action": "unsubscribe_all"})
    check("unsubscribe-all works", "unsubscribed" in r.text.lower())
    db.expire_all()
    check("unsub suppresses email", db.query(models_ext.Suppression)
          .filter_by(email="pp@bank.sa").count() == 1)
    check("unsub sets do_not_contact", db.get(models.Person, p.id).do_not_contact is True)
    check("may_send false after unsub", pf.may_send(db, p.id, "insights") is False)

    # ══ REPORT BUILDER ══
    db.add_all([models.Opportunity(org_id=org.id, stage="Qualified", amount_minor=100_00),
                models.Opportunity(org_id=org.id, stage="Qualified", amount_minor=250_00),
                models.Opportunity(org_id=org.id, stage="Won", amount_minor=500_00)])
    db.commit()
    r = client.post("/reports/run", json={"entity": "opportunities",
        "group_by": "stage", "metric": "sum", "metric_field": "amount_minor"})
    data = {d["group"]: d["value"] for d in r.json()["data"]}
    check("report sums by group", data.get("Qualified") == 350_00 and data.get("Won") == 500_00)

    r = client.post("/reports/run", json={"entity": "opportunities",
        "filters": [{"field": "stage", "op": "eq", "value": "Won"}], "metric": "count"})
    check("report filters + counts", r.json()["data"][0]["value"] == 1)
    check("bad entity 422", client.post("/reports/run",
                                        json={"entity": "unicorns"}).status_code == 422)

    r = client.post("/reports", json={"name": "Pipeline by stage",
        "entity": "opportunities", "group_by": "stage", "metric": "count"})
    rid = r.json()["id"]
    r = client.get(f"/reports/{rid}/run")
    check("saved report runs", r.status_code == 200 and r.json()["report"] == "Pipeline by stage")

    # ══ LOGIN RATE LIMIT ══
    for _ in range(5):
        client.post("/auth/login", json={"email": "admin@test.sa", "password": "wrong"})
    r = client.post("/auth/login", json={"email": "admin@test.sa", "password": "correct-pw"})
    check("6th attempt throttled 429 even w/ right pw", r.status_code == 429)
    r = client.post("/auth/login", json={"email": "other@test.sa", "password": "x"})
    check("other identity not throttled", r.status_code == 401)

    # ══ RTL toggle present in shell ══
    r = client.get("/app")
    check("RTL toggle shipped", "toggleRTL" in r.text and "drip_rtl" in r.text)

    passed = sum(1 for _, ok in _results if ok); total = len(_results)
    print(f"\n{passed}/{total} checks passed  [final wave e2e]")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)


def test_final_wave():
    assert run()
