"""
DRIP OS shell e2e — ONE application at "/": full IA in one nav, hash routing,
shared account context, command palette, notifications, no external launches.
Verifies the shell structure + that every screen's API binding answers.
"""
import os
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

_DBFILE = os.path.join(tempfile.gettempdir(), "drip_os.db")
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
    # ── ONE app at root ──
    r = client.get("/")
    html = r.text
    check("OS serves at /", r.status_code == 200 and "DRIP" in html and "OS" in html)
    check("/app redirects into the OS", client.get("/app", follow_redirects=False).status_code == 307)

    # one nav containing the whole IA
    for item in ["Dashboard", "Accounts", "Contacts", "Signals", "Buying Committee",
                 "Journeys", "Segments", "Email Analytics", "Pipeline", "Meetings",
                 "Tasks", "Sequences", "Quotes", "Custom Objects", "Workflow",
                 "Prompts", "Agents", "Reports", "Feature Parity", "Developer",
                 "Compliance", "Health", "Settings"]:
        check(f"nav has {item}", item in html)

    # single-app requirements
    check("hash router present", "hashchange" in html and "SCREENS" in html)
    check("shared account context", "setAccount" in html and "drip_account" in html)
    check("command palette (Ctrl+K)", "openPalette" in html and "'k'" in html.lower())
    check("notification center", "openNotifs" in html)
    check("one login inside the shell", "sLogin" in html and "/auth/login" in html)
    check("RTL support inside shell", "toggleRTL" in html)
    check("no Lovable launch in OS", "lovable.app" not in html)
    check("no port-5050 launch in OS", "5050" not in html)

    # legacy preserved during transition, off the main path
    check("legacy console still reachable", client.get("/legacy").status_code == 200)

    # ── every screen's primary API binding answers ──
    db = SessionLocal()
    org = models.Organization(canonical_name="OS Bank"); db.add(org); db.commit()
    db.add(models.Person(current_org_id=org.id, full_name="OS CTO",
                         current_title="CTO", is_active=True)); db.commit()

    bindings = [
        ("dashboard", "GET", "/dashboard/executive"),
        ("accounts", "GET", "/organizations"),
        ("account-360 contacts", "GET", f"/organizations/{org.id}/persons"),
        ("account-360 signals", "GET", f"/organizations/{org.id}/signals"),
        ("account-360 committee", "GET", f"/abm/committee/{org.id}/coverage"),
        ("contacts", "GET", "/persons"),
        ("hot leads", "GET", "/sales/hot-leads"),
        ("signals", "GET", "/signals"),
        ("collectors", "GET", "/abm/collectors"),
        ("email analytics", "GET", "/analytics/email"),
        ("pipeline", "GET", "/opportunities"),
        ("meetings", "GET", "/crm/meetings/upcoming"),
        ("sequences", "GET", "/sequences"),
        ("custom objects", "GET", "/crm/objects"),
        ("workflow", "GET", "/workflow/dead-letters"),
        ("ai prompts", "GET", "/ai/prompts"),
        ("ai analytics", "GET", "/ai/analytics"),
        ("parity", "GET", "/platform/parity"),
        ("api keys", "GET", "/dev/api-keys"),
        ("health", "GET", "/health/ready"),
    ]
    for name, method, path in bindings:
        resp = client.request(method, path)
        check(f"binding {name}", resp.status_code == 200)

    passed = sum(1 for _, ok in _results if ok); total = len(_results)
    print(f"\n{passed}/{total} checks passed  [DRIP OS shell e2e]")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)


def test_os_shell():
    assert run()
