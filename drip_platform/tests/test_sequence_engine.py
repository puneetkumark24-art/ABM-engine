"""
Sequence / Journey Engine test (Blueprint Module 08).

Mirrors tests/test_signal_decay.py's pattern: in-memory SQLite, a plain
check()/results accumulator, runnable standalone with
`python tests/test_sequence_engine.py` (also pytest-discoverable).

Covers:
  - ensure_default_sequence is idempotent and builds 5 steps / 3-day / final-on-5.
  - Compliance gate (is_contactable): inactive, do_not_contact, consent denied,
    already-replied are all blocked; a clean contact passes.
  - enroll_person blocks uncontactable people and is idempotent per (person,seq).
  - next_run_at is computed from the step cadence; get_due only returns
    enrollments whose next_run_at has elapsed, honoring compliance.
  - advance walks step 1..5, marks COMPLETED on the final step, and writes an
    audit event trail.
  - get_due send-window gate returns [] when the window is closed (skip, not error).
  - pause_on_reply enforces ACC-001: pauses the replier AND every other ACTIVE
    enrollment at the same organization, and flips person.replied.

Run: python tests/test_sequence_engine.py
"""
import os
import sys
from datetime import datetime, timedelta

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from database import Base, engine, SessionLocal  # noqa: E402
import models  # noqa: E402
try:
    import models_ext, models_p10, models_p11, models_p12  # noqa: E402,F401  (complete metadata for Postgres drop/create)
except ImportError:
    pass
from sequences import engine as seq  # noqa: E402
from sequences import send_window  # noqa: E402

_results = []


def check(name, cond):
    _results.append((name, bool(cond)))
    print(("PASS" if cond else "FAIL"), "-", name)


def fresh_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    return SessionLocal()


def mk_org(db, name):
    o = models.Organization(canonical_name=name)
    db.add(o); db.commit(); return o


def mk_person(db, org, name, **kw):
    p = models.Person(full_name=name, current_org_id=org.id, is_active=True, **kw)
    db.add(p); db.commit(); return p


def run():
    # ---- default sequence shape + idempotency ----
    db = fresh_db()
    s1 = seq.ensure_default_sequence(db)
    s2 = seq.ensure_default_sequence(db)
    steps = db.query(models.SequenceStep).filter_by(sequence_id=s1.id).order_by(models.SequenceStep.step_number).all()
    check("ensure_default idempotent (same id)", s1.id == s2.id)
    check("default has exactly 5 steps", len(steps) == 5)
    check("steps are 3-day cadence", all(st.wait_days_after_previous == 3 for st in steps))
    check("only step 5 is final", [st.is_final for st in steps] == [False, False, False, False, True])

    # ---- compliance gate ----
    org = mk_org(db, "Test Bank")
    clean = mk_person(db, org, "Clean Contact")
    inactive = mk_person(db, org, "Inactive"); inactive.is_active = False; db.commit()
    dnc = mk_person(db, org, "DoNotContact", do_not_contact=True)
    denied = mk_person(db, org, "Denied", consent_status="denied")
    replied = mk_person(db, org, "Replied", replied=True)

    check("clean contact is contactable", seq.is_contactable(clean)[0] is True)
    check("inactive blocked", seq.is_contactable(inactive)[0] is False)
    check("do_not_contact blocked", seq.is_contactable(dnc)[0] is False)
    check("consent denied blocked", seq.is_contactable(denied)[0] is False)
    check("already replied blocked", seq.is_contactable(replied)[0] is False)

    # ---- enroll: blocks uncontactable, idempotent for clean ----
    enr, reason = seq.enroll_person(db, clean.id)
    check("clean enrolls", enr is not None and reason == "enrolled")
    enr_again, reason2 = seq.enroll_person(db, clean.id)
    check("enroll idempotent", enr_again.id == enr.id and reason2 == "already_enrolled")
    blocked, breason = seq.enroll_person(db, dnc.id)
    check("uncontactable not enrolled", blocked is None and breason == "do_not_contact")

    # ---- next_run_at computed; step 1 due after 3 days ----
    check("next_run_at set on enroll", enr.next_run_at is not None)
    # not due yet (3 days out)
    due_now = seq.get_due(db, respect_send_window=False, now=datetime.utcnow())
    check("not due immediately", all(r["enrollment"].id != enr.id for r in due_now))
    # simulate 3 days passing
    enr.next_run_at = datetime.utcnow() - timedelta(minutes=1); db.commit()
    due_later = seq.get_due(db, respect_send_window=False, now=datetime.utcnow())
    check("due after cadence elapsed", any(r["enrollment"].id == enr.id for r in due_later))

    # ---- advance walks 1..5 then COMPLETED ----
    for expected_step in range(1, 6):
        seq.advance(db, enr.id, now=datetime.utcnow())
        db.refresh(enr)
        check(f"advanced to step {expected_step}", enr.current_step == expected_step)
    check("completed after final step", enr.status == "COMPLETED")
    events = db.query(models.SequenceEnrollmentEvent).filter_by(enrollment_id=enr.id).all()
    check("audit trail written", any(e.event_type == "completed" for e in events)
          and sum(1 for e in events if e.event_type == "step_executed") == 5)

    # ---- send-window gate: closed => [] ----
    # force a closed window via env (blackout every weekday)
    os.environ["SEND_BLACKOUT_WEEKDAYS"] = "0,1,2,3,4,5,6"
    allowed, _ = send_window.is_within_send_window()
    check("window forced closed", allowed is False)
    # make something due, confirm get_due skips when respecting window
    c2 = mk_person(db, org, "Due Person")
    e2, _ = seq.enroll_person(db, c2.id)
    e2.next_run_at = datetime.utcnow() - timedelta(minutes=1); db.commit()
    check("get_due skips when window closed", seq.get_due(db, respect_send_window=True) == [])
    check("get_due returns when window ignored", len(seq.get_due(db, respect_send_window=False)) >= 1)
    os.environ.pop("SEND_BLACKOUT_WEEKDAYS", None)

    # ---- ACC-001: pause_on_reply cascades to the whole org ----
    db2 = fresh_db()
    orgA = mk_org(db2, "Al Rajhi")
    orgB = mk_org(db2, "SNB")
    a1 = mk_person(db2, orgA, "A1"); a2 = mk_person(db2, orgA, "A2"); a3 = mk_person(db2, orgA, "A3")
    b1 = mk_person(db2, orgB, "B1")
    for p in (a1, a2, a3, b1):
        seq.enroll_person(db2, p.id)
    res = seq.pause_on_reply(db2, a1.id, reason="reply")
    db2.refresh(a1)
    check("replier flagged replied", a1.replied is True)
    check("replier's own enrollment paused", res["paused_person"] == 1)
    check("account-centric paused the other 2 at org", res["paused_account"] == 2)
    # other org untouched
    b1_enr = db2.query(models.SequenceEnrollment).filter_by(person_id=b1.id).first()
    check("other org NOT paused", b1_enr.status == "ACTIVE")
    # all Al Rajhi enrollments now paused
    orgA_active = db2.query(models.SequenceEnrollment).filter_by(org_id=orgA.id, status="ACTIVE").count()
    check("no active enrollments remain at replied org", orgA_active == 0)

    # ---- summary ----
    passed = sum(1 for _, ok in _results if ok)
    total = len(_results)
    print(f"\n{passed}/{total} checks passed")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)


def test_sequence_engine():
    """pytest entry point."""
    assert run()
