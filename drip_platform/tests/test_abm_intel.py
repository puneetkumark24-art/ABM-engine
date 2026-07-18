"""
Sprint 4 test — ABM Intelligence: title→role inference, committee materialization
+ coverage gaps, content-hash signal dedup, and account scoring. SQLite + PG.
"""
import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from database import Base, engine, SessionLocal  # noqa: E402
import models, models_ext, models_p10, models_p11, models_p12  # noqa: E402,F401
from abm_platform.services import abm_intel as ai  # noqa: E402

_results = []


def check(name, cond):
    _results.append((name, bool(cond))); print(("PASS" if cond else "FAIL"), "-", name)


def run():
    Base.metadata.drop_all(bind=engine); Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    # ── role inference ──
    check("CFO -> economic_buyer", ai.infer_role("Chief Financial Officer") == "economic_buyer")
    check("CTO -> technical_buyer", ai.infer_role("Group CTO") == "technical_buyer")
    check("CEO -> executive_sponsor", ai.infer_role("Chief Executive Officer") == "executive_sponsor")
    check("Head of Digital -> champion", ai.infer_role("Head of Digital Transformation") == "champion")
    check("Analyst -> user", ai.infer_role("Operations Analyst") == "user")
    check("unknown -> user fallback", ai.infer_role("Wizard") == "user")

    # ── committee materialization + coverage ──
    org = models.Organization(canonical_name="Target Bank"); db.add(org); db.commit()
    titles = [("CFO", True), ("Group CTO", False), ("Head of Digital Transformation", False),
              ("Operations Analyst", False)]
    for t, replied in titles:
        db.add(models.Person(current_org_id=org.id, full_name=t, current_title=t,
                             is_active=True, replied=replied))
    db.commit()

    res = ai.infer_committee(db, org.id)
    check("committee inferred for 4 people", res["people"] == 4 and res["created"] == 4)
    check("idempotent re-run updates not duplicates",
          ai.infer_committee(db, org.id)["created"] == 0)

    cov = ai.committee_coverage(db, org.id)
    check("coverage finds economic_buyer+technical_buyer+champion+user",
          set(cov["roles_covered"]) == {"economic_buyer", "technical_buyer", "champion", "user"})
    check("coverage flags missing executive_sponsor", cov["roles_missing"] == ["executive_sponsor"])
    check("coverage_pct = 80", cov["coverage_pct"] == 80.0)
    check("engaged member counted (CFO replied)", cov["engaged_members"] == 1)
    check("not single-threaded", cov["single_threaded"] is False)

    # ── signal dedup ──
    s1, c1 = ai.ingest_signal(db, org.id, "tender", "SAMA", "New core-banking RFP",
                              url="http://x/rfp1")
    check("first ingest creates", c1 is True)
    s2, c2 = ai.ingest_signal(db, org.id, "tender", "SAMA", "New core-banking RFP",
                              url="http://x/rfp1")
    check("duplicate ingest deduped", c2 is False and s2.id == s1.id)
    s3, c3 = ai.ingest_signal(db, org.id, "news", "Argaam", "Bank posts Q2 profit",
                              url="http://x/news1")
    check("different content creates new", c3 is True and s3.id != s1.id)
    check("only 2 signals stored", db.query(models.Signal).filter_by(org_id=org.id).count() == 2)

    # ── account scoring ──
    row = ai.score_account(db, org.id)
    check("account scored with tier", row.total_score > 0 and row.tier in ("A", "B", "C"))
    check("relationship_score reflects 80% coverage", row.relationship_score == 80)

    passed = sum(1 for _, ok in _results if ok); total = len(_results)
    is_pg = db.bind.dialect.name == "postgresql"
    print(f"\n{passed}/{total} checks passed  [DB: {'postgresql' if is_pg else 'sqlite'}]")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)


def test_abm_intel():
    assert run()
