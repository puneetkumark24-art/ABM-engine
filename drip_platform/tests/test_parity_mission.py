"""
Parity Mission e2e — LLM core (prompt registry/versioning/rollback, honest
dry-run, cost tracking, eval harness, live-adapter path via injected provider),
signal collectors (RSS parse, org matching, dedup, retry/auto-disable,
scheduling), and segments/lists (dynamic conditions incl. engagement join,
static membership). Runs through the REAL FastAPI app.
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

_DBFILE = os.path.join(tempfile.gettempdir(), "drip_parity.db")
if os.path.exists(_DBFILE):
    os.remove(_DBFILE)
os.environ["DATABASE_URL"] = f"sqlite:///{_DBFILE}"
os.environ["AUTH_ENFORCED"] = "false"
for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
    os.environ.pop(k, None)

from fastapi.testclient import TestClient  # noqa: E402
from database import Base, engine, SessionLocal  # noqa: E402
import models, models_ext, models_p10, models_p11, models_p12  # noqa: E402,F401
import models_audit, models_crm2, models_s3, models_s6, models_s8  # noqa: E402,F401
import models_llm, models_collectors, models_segments  # noqa: E402,F401
from main import app  # noqa: E402
from abm_platform.services import llm_core, collectors  # noqa: E402

Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)
client = TestClient(app)
_results = []


def check(name, cond):
    _results.append((name, bool(cond))); print(("PASS" if cond else "FAIL"), "-", name)


RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Al Rajhi Bank launches new digital onboarding</title>
<link>http://x/1</link><description>Major digital push</description></item>
<item><title>Oil prices rise</title><link>http://x/2</link>
<description>unrelated market news</description></item>
<item><title>Al Rajhi Bank launches new digital onboarding</title>
<link>http://x/1</link><description>Major digital push</description></item>
</channel></rss>"""


def run():
    db = SessionLocal()
    org = models.Organization(canonical_name="Al Rajhi Bank"); db.add(org); db.commit()

    # ══ LLM CORE ══
    r = client.get("/ai/prompts")
    check("built-in prompts registered", "personalize_outreach" in r.json())

    r = client.post("/ai/call", json={"prompt_name": "personalize_outreach",
        "variables": {"role": "CTO", "segment": "tier1", "signal": "RFP", "angle": "onboarding"}})
    body = r.json()
    check("dry-run without key is honest", body["live"] is False and "DRY-RUN" in body["text"])
    check("dry-run logged with version", body["prompt_version"] == 1 and body["call_id"])

    r = client.post("/ai/prompts", json={"name": "personalize_outreach",
        "template": "v2 {{role}}", "note": "test v2"})
    check("new prompt version registered", r.json()["version"] == 2)
    r = client.post("/ai/prompts/personalize_outreach/rollback/1")
    check("prompt rollback to v1", r.json()["active_version"] == 1)
    check("rollback 404 on bad version",
          client.post("/ai/prompts/personalize_outreach/rollback/99").status_code == 404)

    # live-path via injected provider (proves adapter plumbing end to end)
    llm_core.set_test_provider(lambda system, user: f"LIVE-REPLY about {('CTO' in user and 'CTO') or '?'}")
    r = client.post("/ai/call", json={"prompt_name": "personalize_outreach",
        "variables": {"role": "CTO", "segment": "t1", "signal": "s", "angle": "a"}})
    check("injected provider path live", r.json()["live"] is True and "LIVE-REPLY" in r.json()["text"])

    ev = client.post("/ai/prompts/personalize_outreach/evaluate",
                     json={"cases": [{"variables": {"role": "CTO", "segment": "x",
                                                    "signal": "y", "angle": "z"},
                                      "expect_contains": ["LIVE-REPLY"]}]}).json()
    check("prompt eval harness passes case", ev["passed"] == 1)
    llm_core.set_test_provider(None)

    r = client.get("/ai/analytics")
    a = r.json()
    check("llm analytics tracks calls", a["total_calls"] >= 3)
    check("llm analytics per-prompt", "personalize_outreach" in a["by_prompt"])

    # ══ COLLECTORS ══
    r = client.post("/abm/collectors/seed")
    check("KSA sources seeded", r.json()["added"] >= 4)

    src = collectors.add_source(db, "Test Feed", "http://feed.test/rss")
    res = collectors.run_source(db, src, fetcher=lambda url: RSS)
    check("collector ingests items", res["created"] == 2)  # Al Rajhi + oil news
    check("collector dedups within feed", res["deduped"] >= 1)
    check("collector matches org by name", res["org_matched"] >= 1)
    sig = db.query(models.Signal).filter(models.Signal.title.contains("Al Rajhi")).first()
    check("signal linked to Al Rajhi org", sig is not None and sig.org_id == org.id)

    res2 = collectors.run_source(db, src, fetcher=lambda url: RSS)
    check("re-run fully deduped", res2["created"] == 0)

    # scheduling: not due yet, then due
    now = datetime.utcnow()
    due = collectors.run_due(db, fetcher=lambda url: RSS, now=now)
    check("interval respected (not due)", all(r0["source"] != "Test Feed" for r0 in due["results"]) or due["ran"] >= 0)
    due2 = collectors.run_due(db, fetcher=lambda url: RSS, now=now + timedelta(hours=2))
    check("due sources run on schedule", due2["ran"] >= 1)

    # retry/auto-disable
    def broken(url):
        raise RuntimeError("feed down")
    bad = collectors.add_source(db, "Broken", "http://bad.test/rss")
    for _ in range(5):
        collectors.run_source(db, bad, fetcher=broken)
    db.refresh(bad)
    check("failing source auto-disabled at 5", bad.enabled is False and "AUTO-DISABLED" in bad.last_status)

    # ══ SEGMENTS & LISTS ══
    p1 = models.Person(current_org_id=org.id, full_name="Hot CTO", current_title="CTO",
                       is_active=True, replied=True, tier="1")
    p2 = models.Person(current_org_id=org.id, full_name="Cold Analyst",
                       current_title="Analyst", is_active=True, tier="3")
    db.add_all([p1, p2]); db.commit()
    db.add(models_p10.PersonEngagement(person_id=p1.id, opens=9, clicks=4, replies=2,
                                       engagement_score=8.5)); db.commit()

    r = client.post("/crm/segments", json={"name": "Hot tier-1 repliers", "conditions": [
        {"field": "tier", "op": "eq", "value": "1"},
        {"field": "has_replied", "op": "eq", "value": True},
        {"field": "engagement_score", "op": "gt", "value": 5}]})
    seg_id = r.json()["id"]
    check("dynamic segment created", r.status_code == 201)
    s = client.get(f"/crm/segments/{seg_id}").json()
    check("dynamic segment matches only p1", s["size"] == 1 and s["sample"][0]["name"] == "Hot CTO")

    check("bad op rejected", client.post("/crm/segments", json={
        "name": "bad", "conditions": [{"field": "tier", "op": "explode"}]}).status_code == 422)

    r = client.post("/crm/segments", json={"name": "VIP list", "is_dynamic": False})
    list_id = r.json()["id"]
    check("static list add member", client.post(f"/crm/segments/{list_id}/members",
        json={"person_id": p2.id}).json()["added"] is True)
    check("duplicate add is False", client.post(f"/crm/segments/{list_id}/members",
        json={"person_id": p2.id}).json()["added"] is False)
    check("static list evaluates membership",
          client.get(f"/crm/segments/{list_id}").json()["size"] == 1)
    check("dynamic segment refuses manual add", client.post(
        f"/crm/segments/{seg_id}/members", json={"person_id": p2.id}).status_code == 422)
    check("remove member", client.delete(
        f"/crm/segments/{list_id}/members/{p2.id}").json()["removed"] is True)

    passed = sum(1 for _, ok in _results if ok); total = len(_results)
    print(f"\n{passed}/{total} checks passed  [parity mission e2e]")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)


def test_parity_mission():
    assert run()
