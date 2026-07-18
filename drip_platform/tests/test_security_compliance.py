"""
Sprint 9 test — Security & Compliance: real Fernet field encryption (+ tamper
detection), RBAC/ABAC access checks, PDPL export + erasure (with suppression),
consent, and retention purge. SQLite + PostgreSQL.
"""
import os
import sys
from datetime import datetime, timedelta

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from database import Base, engine, SessionLocal  # noqa: E402
import models, models_ext, models_p10, models_p11, models_p12  # noqa: E402,F401
from abm_platform.services import security_compliance as sc  # noqa: E402

_results = []


def check(name, cond):
    _results.append((name, bool(cond))); print(("PASS" if cond else "FAIL"), "-", name)


def run():
    Base.metadata.drop_all(bind=engine); Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    # ── field encryption ──
    ct = sc.encrypt_field("+966500000000")
    check("ciphertext differs from plaintext", ct != "+966500000000")
    check("round-trip decrypts", sc.decrypt_field(ct) == "+966500000000")
    check("None passes through", sc.encrypt_field(None) is None)
    tampered = ct[:-2] + ("aa" if not ct.endswith("aa") else "bb")
    try:
        sc.decrypt_field(tampered)
        check("tamper detected", False)
    except ValueError:
        check("tamper detected", True)

    # ── RBAC / ABAC ──
    check("RBAC wildcard grants", sc.permits(["crm.*"], "crm.read") is True)
    check("RBAC deny unrelated", sc.permits(["crm.*"], "admin.full") is False)
    admin = {"sub": "u1", "tenant_id": "t1", "permissions": ["*"]}
    ok, _ = sc.check_access(admin, "crm.delete", {"tenant_id": "t1"})
    check("admin allowed same tenant", ok)
    ok2, why2 = sc.check_access(admin, "crm.read", {"tenant_id": "t2"})
    check("cross-tenant denied by ABAC", ok2 is False and "cross-tenant" in why2)
    rep = {"sub": "rep1", "tenant_id": "t1", "permissions": ["deal.edit"]}
    ok3, _ = sc.check_access(rep, "deal.edit:own", {"owner": "rep1"})
    ok4, why4 = sc.check_access(rep, "deal.edit:own", {"owner": "rep2"})
    check("owner can edit own", ok3)
    check("non-owner denied by ABAC", ok4 is False and "owner" in why4)

    # ── PDPL export + erasure ──
    p = models.Person(full_name="Data Subject", primary_email="ds@bank.sa",
                      phone="+96650", mobile="+96651", consent_status="granted",
                      is_active=True)
    db.add(p); db.commit()

    exp = sc.export_subject(db, p.id)
    check("export returns PII", exp["pii"]["primary_email"] == "ds@bank.sa")
    check("export includes consent", exp["consent"]["status"] == "granted")

    res = sc.erase_subject(db, p.id)
    db.refresh(p)
    check("erasure scrubbed email", p.primary_email is None)
    check("erasure scrubbed phone+mobile", p.phone is None and p.mobile is None)
    check("erasure marks do_not_contact", p.do_not_contact is True)
    check("erasure withdraws consent", p.consent_status == "withdrawn")
    check("erasure suppresses email", db.query(models_ext.Suppression).filter_by(email="ds@bank.sa").count() == 1)
    check("erasure deactivates", p.is_active is False)

    # ── consent ──
    p2 = models.Person(full_name="Consenter", primary_email="c@bank.sa", is_active=True)
    db.add(p2); db.commit()
    sc.set_consent(db, p2.id, "granted")
    check("has_consent true after grant", sc.has_consent(db, p2.id) is True)
    sc.set_consent(db, p2.id, "withdrawn")
    check("has_consent false after withdraw", sc.has_consent(db, p2.id) is False)

    # ── retention ──
    old = models.Signal(org_id=None, signal_type="news", title="old",
                        created_at=datetime.utcnow() - timedelta(days=400))
    new = models.Signal(org_id=None, signal_type="news", title="new",
                        created_at=datetime.utcnow())
    db.add_all([old, new]); db.commit()
    n = sc.purge_expired(db, models.Signal, "created_at", older_than_days=365)
    check("retention purged 1 old row", n == 1)
    check("retention kept the fresh row", db.query(models.Signal).count() == 1)

    passed = sum(1 for _, ok in _results if ok); total = len(_results)
    is_pg = db.bind.dialect.name == "postgresql"
    print(f"\n{passed}/{total} checks passed  [DB: {'postgresql' if is_pg else 'sqlite'}]")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)


def test_security_compliance():
    assert run()
