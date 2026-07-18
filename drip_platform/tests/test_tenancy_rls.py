"""
P0-A test — multi-tenancy Row-Level Security + auth + webhook signatures.

The RLS half is PostgreSQL-only (RLS doesn't exist in SQLite) and connects as a
NON-superuser role `app_rw`, because superusers bypass RLS. It proves that with
`app.current_tenant` set, a session sees ONLY its tenant's rows — enforced by the
database, not by application WHERE clauses.

The auth + webhook halves are pure-Python and run everywhere.

Run (Postgres): DATABASE_URL=postgresql+psycopg2://postgres:@/postgres?host=/tmp/pgdata \
                python tests/test_tenancy_rls.py
"""
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import sqlalchemy as sa  # noqa: E402
from auth import issue_token, verify_token, Principal  # noqa: E402
from webhook_security import verify_hmac_sha256  # noqa: E402
from fastapi import HTTPException  # noqa: E402

_results = []


def check(name, cond):
    _results.append((name, bool(cond)))
    print(("PASS" if cond else "FAIL"), "-", name)


TA = "11111111-1111-1111-1111-111111111111"
TB = "22222222-2222-2222-2222-222222222222"


def run_rls():
    url = os.environ.get("DATABASE_URL", "")
    if not url.startswith("postgresql"):
        print("… RLS checks skipped (needs PostgreSQL; RLS unavailable on SQLite)")
        return
    admin = sa.create_engine(url)   # postgres = superuser (seeds, bypasses RLS)
    with admin.begin() as c:
        # non-superuser app role
        c.execute(sa.text("""
            DO $$ BEGIN
              IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='app_rw') THEN
                CREATE ROLE app_rw LOGIN NOSUPERUSER;
              END IF;
            END $$;"""))
        c.execute(sa.text("GRANT USAGE ON SCHEMA public TO app_rw"))
        c.execute(sa.text("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_rw"))
        c.execute(sa.text("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_rw"))
        # tenants + two orgs (seed as superuser → RLS bypassed)
        for tid, name in [(TA, "Tenant A"), (TB, "Tenant B")]:
            c.execute(sa.text("INSERT INTO tenants (id,name,slug) VALUES (:i,:n,:n) "
                              "ON CONFLICT (id) DO NOTHING"), {"i": tid, "n": name})
        c.execute(sa.text("DELETE FROM organizations WHERE canonical_name IN "
                          "('RLS Org A','RLS Org B')"))
        c.execute(sa.text("INSERT INTO organizations (id, canonical_name, tenant_id) "
                          "VALUES ('rls-a','RLS Org A', :t)"), {"t": TA})
        c.execute(sa.text("INSERT INTO organizations (id, canonical_name, tenant_id) "
                          "VALUES ('rls-b','RLS Org B', :t)"), {"t": TB})

    # connect as the NON-superuser app role
    tail = url.split("@", 1)[1]
    app_uri = "postgresql+psycopg2://app_rw@" + tail
    app = sa.create_engine(app_uri)

    def visible(tenant):
        # explicit transaction + transaction-LOCAL GUC = exactly the production
        # pattern (set_tenant uses is_local=true); no cross-request leakage.
        with app.begin() as c:
            if tenant:
                c.execute(sa.text("SELECT set_config('app.current_tenant', :t, true)"),
                          {"t": tenant})
            names = [r[0] for r in c.execute(sa.text(
                "SELECT canonical_name FROM organizations "
                "WHERE canonical_name LIKE 'RLS Org%' ORDER BY canonical_name")).fetchall()]
        return names

    a_view = visible(TA)
    b_view = visible(TB)
    unscoped = visible(None)

    check("RLS: tenant A sees only its org", a_view == ["RLS Org A"])
    check("RLS: tenant B sees only its org", b_view == ["RLS Org B"])
    check("RLS: A cannot see B's data (isolation)", "RLS Org B" not in a_view)
    check("RLS: unset GUC is permissive (gradual rollout)", set(unscoped) == {"RLS Org A", "RLS Org B"})

    # app_rw is genuinely non-superuser (so RLS actually applies)
    with app.connect() as c:
        is_super = c.execute(sa.text("SELECT rolsuper FROM pg_roles WHERE rolname='app_rw'")).scalar()
    check("RLS: app role is non-superuser (RLS enforceable)", is_super is False)


def run_auth():
    tok = issue_token("user-1", TA, roles=["ae"], scopes=["crm.read", "sequences.*"])
    p = Principal(verify_token(tok))
    check("AUTH: round-trip carries tenant + scopes", p.tenant_id == TA and p.sub == "user-1")
    check("AUTH: exact scope granted", p.has_scope("crm.read"))
    check("AUTH: wildcard scope granted", p.has_scope("sequences.enroll"))
    check("AUTH: ungranted scope denied", not p.has_scope("admin.full"))

    # tampered signature rejected
    bad = tok[:-4] + ("aaaa" if not tok.endswith("aaaa") else "bbbb")
    try:
        verify_token(bad); check("AUTH: tampered token rejected", False)
    except HTTPException as e:
        check("AUTH: tampered token rejected", e.status_code == 401)
    # expired rejected
    exp = issue_token("u", TA, ttl_seconds=-1)
    try:
        verify_token(exp); check("AUTH: expired token rejected", False)
    except HTTPException as e:
        check("AUTH: expired token rejected", e.status_code == 401)
    # wrong secret rejected
    other = issue_token("u", TA, secret="different-secret")
    try:
        verify_token(other); check("AUTH: wrong-secret token rejected", False)
    except HTTPException as e:
        check("AUTH: wrong-secret token rejected", e.status_code == 401)


def run_webhook():
    body = b'{"event":"hard_bounce","email":"x@y.z"}'
    secret = "wh-secret"
    import base64 as _b, hmac as _h, hashlib as _hh
    good = _b.b64encode(_h.new(secret.encode(), body, _hh.sha256).digest()).decode()
    check("WEBHOOK: valid signature accepted", verify_hmac_sha256(body, good, secret))
    check("WEBHOOK: forged signature rejected", not verify_hmac_sha256(body, "forged", secret))
    check("WEBHOOK: no secret => reject (fail closed)", not verify_hmac_sha256(body, good, ""))


def run():
    # SAFETY GUARD: the RLS half creates roles/policies and writes probe rows.
    # It must ONLY run on a disposable test database, never a production DB.
    # Set DRIP_ALLOW_PG_TESTS=1 explicitly when DATABASE_URL is a scratch PG.
    url = os.environ.get("DATABASE_URL", "")
    if url.startswith("postgresql") and not os.environ.get("DRIP_ALLOW_PG_TESTS"):
        print("SKIP - PG tenancy suite guarded: set DRIP_ALLOW_PG_TESTS=1 on a "
              "DISPOSABLE test database (never your production drip DB).")
        run_auth()
        run_webhook()
        passed = sum(1 for _, ok in _results if ok); total = len(_results)
        print(f"\n{passed}/{total} checks passed  [DB: guarded — auth/webhook only]")
        return passed == total
    run_rls()
    run_auth()
    run_webhook()
    passed = sum(1 for _, ok in _results if ok)
    total = len(_results)
    db = "postgresql" if os.environ.get("DATABASE_URL", "").startswith("postgresql") else "sqlite"
    print(f"\n{passed}/{total} checks passed  [DB: {db}]")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)


def test_tenancy_rls():
    assert run()
