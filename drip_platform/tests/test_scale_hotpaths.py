"""
P0-C test — set-based hot paths are equivalent to the naive versions and scale.
Runs on SQLite and PostgreSQL.
"""
import os
import sys
from datetime import datetime, timedelta

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from database import Base, engine, SessionLocal  # noqa: E402
import models, models_ext, models_p10, models_p11, models_p12  # noqa: E402,F401
from sequences import engine as seq_engine  # noqa: E402
from abm_platform.services import scale, marketing  # noqa: E402

_results = []


def check(name, cond):
    _results.append((name, bool(cond))); print(("PASS" if cond else "FAIL"), "-", name)


def run():
    Base.metadata.drop_all(bind=engine); Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    org = models.Organization(canonical_name="Scale Bank")
    org2 = models.Organization(canonical_name="Scale Bank 2")
    db.add_all([org, org2]); db.commit()

    # people across tiers
    people = []
    for i in range(20):
        p = models.Person(full_name=f"Person {i}", current_org_id=org.id,
                          tier=("HOT" if i < 5 else "WARM" if i < 12 else "COLD"),
                          priority_score=100 - i, primary_email=f"p{i}@ex.invalid",
                          consent_status="opted_in")
        people.append(p); db.add(p)
    # a blocked + a denied contact
    dnc = models.Person(full_name="DNC", current_org_id=org.id, do_not_contact=True,
                        primary_email="dnc@ex.invalid")
    den = models.Person(full_name="Denied", current_org_id=org.id, consent_status="denied",
                        primary_email="den@ex.invalid")
    db.add_all([dnc, den]); db.commit()

    # ── get_due_fast == engine.get_due ──
    for p in people + [dnc, den]:
        seq_engine.enroll_person(db, p.id)
    for e in db.query(models.SequenceEnrollment).all():
        e.next_run_at = datetime.utcnow() - timedelta(minutes=1)
    db.commit()
    naive = seq_engine.get_due(db, limit=50, respect_send_window=False)
    fast = scale.get_due_fast(db, limit=50, respect_send_window=False)
    naive_ids = {r["enrollment"].id for r in naive}
    fast_ids = {r["enrollment"].id for r in fast}
    check("GET_DUE fast == naive (same enrollments)", naive_ids == fast_ids)
    check("GET_DUE excludes do_not_contact + denied",
          not any(r["person"].full_name in ("DNC", "Denied") for r in fast))
    # ordering: HOT first
    tiers = [r["person"].tier for r in fast]
    check("GET_DUE ordered HOT>WARM>COLD",
          tiers == sorted(tiers, key=lambda t: {"HOT": 1, "WARM": 2, "COLD": 3}[t]))

    # ── resolve_segment_fast == marketing.resolve_members (dynamic) ──
    aud = marketing.create_audience(db, "hot seg", kind="segment",
                                    definition=[{"field": "tier", "op": "eq", "value": "HOT"}])
    naive_seg = {p.id for p in marketing.resolve_members(db, aud.id)}
    fast_seg = {p.id for p in scale.resolve_segment_fast(db, aud.definition)}
    check("SEGMENT fast == naive", naive_seg == fast_seg and len(fast_seg) == 5)
    # multi-condition
    multi = scale.resolve_segment_fast(db, [{"field": "tier", "op": "eq", "value": "WARM"},
                                            {"field": "priority_score", "op": "gte", "value": 90}])
    check("SEGMENT multi-condition indexed filter", all(p.tier == "WARM" and (p.priority_score or 0) >= 90 for p in multi))
    # junk field is ignored (never full-scan-on-garbage)
    junk = scale.resolve_segment_fast(db, [{"field": "nonexistent", "op": "eq", "value": "x"}])
    check("SEGMENT unknown field fails safe (returns active set)", len(junk) >= 20)

    # ── sendable_person_ids set-based ──
    ids = [p.id for p in people] + [dnc.id, den.id]
    marketing.suppress(db, "p3@ex.invalid", "bounce")
    sendable = scale.sendable_person_ids(db, ids)
    check("SENDABLE excludes suppressed + dnc + denied",
          people[3].id not in sendable and dnc.id not in sendable and den.id not in sendable)
    check("SENDABLE keeps clean contacts", people[0].id in sendable and len(sendable) == 19)

    # ── dedupe blocking-keys ──
    # inject duplicates: same email; same last-name+org; same linkedin
    d1 = models.Person(full_name="Ahmed Ali", current_org_id=org2.id, primary_email="dup@ex.invalid")
    d2 = models.Person(full_name="Ahmed Ali", current_org_id=org2.id, primary_email="dup@ex.invalid")
    d3 = models.Person(full_name="Sara Ali", current_org_id=org2.id, linkedin_url="https://li/x")
    d4 = models.Person(full_name="Other Ali", current_org_id=org2.id, linkedin_url="https://li/x")
    db.add_all([d1, d2, d3, d4]); db.commit()
    cands = scale.dedupe_candidates(db)
    pairset = {tuple(sorted([c["a_id"], c["b_id"]])) for c in cands}
    check("DEDUPE finds exact-email duplicate", tuple(sorted([d1.id, d2.id])) in pairset)
    check("DEDUPE finds exact-linkedin duplicate", tuple(sorted([d3.id, d4.id])) in pairset)
    # blocking keeps comparison count tiny vs N^2
    n = db.query(models.Person).count()
    naive_comparisons = n * (n - 1) // 2
    check("DEDUPE blocking << O(N^2)", len(cands) < naive_comparisons / 5)
    print(f"    (N={n}, naive pairs={naive_comparisons}, blocked candidate pairs={len(cands)})")

    passed = sum(1 for _, ok in _results if ok); total = len(_results)
    is_pg = db.bind.dialect.name == "postgresql"
    print(f"\n{passed}/{total} checks passed  [DB: {'postgresql' if is_pg else 'sqlite'}]")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)


def test_scale_hotpaths():
    assert run()
