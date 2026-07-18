"""
Unification (U1) e2e — global search across entity types, executive dashboard
aggregation, email analytics math (rates from messages+events), GA4 dry-run
honesty, capability registry / parity endpoints, and the unified workspace shell.
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

_DBFILE = os.path.join(tempfile.gettempdir(), "drip_unified.db")
if os.path.exists(_DBFILE):
    os.remove(_DBFILE)
os.environ["DATABASE_URL"] = f"sqlite:///{_DBFILE}"
os.environ["AUTH_ENFORCED"] = "false"
os.environ.pop("GA4_MEASUREMENT_ID", None)

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
    db = SessionLocal()
    # ── seed cross-module data ──
    org = models.Organization(canonical_name="Riyad Unified Bank"); db.add(org); db.commit()
    p = models.Person(current_org_id=org.id, full_name="Unified Contact",
                      primary_email="uc@bank.sa", current_title="CTO", is_active=True)
    opp = models.Opportunity(org_id=org.id, amount_minor=100_000_00, stage="Qualified",
                             next_step="unified demo")
    sig = models.Signal(org_id=org.id, signal_type="tender", title="Unified RFP")
    camp = models_ext.EmailCampaign(name="Unified Launch", subject="hello", status="sent")
    db.add_all([p, opp, sig, camp]); db.commit()
    # email messages + events: 4 sent, 2 unique opens (one double), 1 click, 1 bounce
    msgs = [models_ext.EmailMessage(campaign_id=camp.id, person_id=p.id,
                                    to_email=f"m{i}@bank.sa", status="sent") for i in range(4)]
    db.add_all(msgs); db.commit()
    ev = [("delivered", 0), ("delivered", 1), ("delivered", 2), ("delivered", 3),
          ("open", 0), ("open", 0), ("open", 1), ("click", 1), ("bounce", 3)]
    for et, i in ev:
        db.add(models_ext.DeliveryEvent(message_id=msgs[i].id, event_type=et,
                                        occurred_at=datetime.utcnow()))
    db.commit()

    # ── global search ──
    r = client.get("/search?q=Unified")
    body = r.json()
    check("search 200", r.status_code == 200)
    for kind in ("companies", "contacts", "signals", "campaigns"):
        check(f"search finds {kind}", kind in body["results"])
    check("search finds deals via next_step", "deals" in body["results"])
    check("short query rejected", client.get("/search?q=a").json()["total"] == 0)

    # ── executive dashboard ──
    r = client.get("/dashboard/executive")
    d = r.json()
    check("exec dashboard 200", r.status_code == 200)
    check("exec pipeline = SAR 10,000", d["pipeline_minor"] == 100_000_00)
    check("exec counts accounts+contacts", d["accounts"] == 1 and d["contacts"] == 1)
    check("exec signals this week", d["signals_this_week"] == 1)
    check("exec email block present", "open_rate" in d["email"])

    # ── email analytics ──
    r = client.get("/analytics/email")
    e = r.json()
    t, ra = e["totals"], e["rates"]
    check("email sent=4 delivered=4", t["sent"] == 4 and t["delivered"] == 4)
    check("email unique opens=2 (double dedup)", t["unique_opens"] == 2)
    check("email open_rate=50%", ra["open_rate"] == 50.0)
    check("email unique clicks=1, CTOR=50%", t["unique_clicks"] == 1 and ra["ctor"] == 50.0)
    check("email bounce counted", t["bounces"] == 1 and ra["bounce_rate"] == 25.0)
    check("per-campaign row present", e["per_campaign"] and e["per_campaign"][0]["campaign"] == "Unified Launch")

    # ── GA4 seam (honest dry-run) ──
    r = client.get("/analytics/ga4/status")
    check("GA4 unconfigured -> dry-run", r.json()["mode"] == "dry-run")
    r = client.post("/analytics/ga4/event", json={"client_id": "c1", "name": "lead_created"})
    check("GA4 event dry-run, not faked", r.json()["sent"] is False and r.json()["mode"] == "dry-run")

    # ── capability registry / parity ──
    r = client.get("/platform/capabilities")
    c = r.json()
    check("capabilities 200 + summary", r.status_code == 200 and c["summary"]["total_capabilities"] >= 40)
    check("capabilities grouped by module", "CRM" in c["modules"] and "Compliance" in c["modules"])
    r = client.get("/platform/parity")
    pd = r.json()
    check("parity has competitors", "HubSpot" in pd["competitor_parity"])
    check("parity lists honest gaps", any(g["status"] == "blocked-external" for g in pd["top_gaps"]))
    check("no competitor claimed above 95", all(v <= 95 for v in pd["competitor_parity"].values()))

    # ── unified shell ──
    r = client.get("/app")
    for tab in ("Home", "Search", "Email", "Parity", "Signals", "Compliance"):
        check(f"shell has {tab} tab", f'"{tab}"' in r.text or f">{tab}<" in r.text or tab in r.text)

    passed = sum(1 for _, ok in _results if ok); total = len(_results)
    print(f"\n{passed}/{total} checks passed  [unified platform e2e]")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)


def test_unified():
    assert run()
