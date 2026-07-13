"""
test_sequence_engine.py
────────────────────────
Standalone verification for the Phase 1 drip-engine changes (workflow/).

Runs ONLY against a temp copy of abm_engine.db — never opens or writes the
live database. Safe to run repeatedly; the temp copy is discarded at the end
(or left in the OS temp dir on failure, for inspection).

Usage (from decimal_abm/, same place you'd run `python -m abm_engine ...`):
    python test_sequence_engine.py
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent
LIVE_DB = REPO_ROOT / "abm_engine.db"

if not LIVE_DB.exists():
    print(f"FAIL: {LIVE_DB} not found — run this from the decimal_abm/ directory.")
    sys.exit(1)

tmp_dir = Path(tempfile.mkdtemp(prefix="abm_seq_test_"))
tmp_db = tmp_dir / "abm_engine.db"
shutil.copy2(LIVE_DB, tmp_db)
print(f"Testing against a COPY: {tmp_db}  (live db untouched: {LIVE_DB})")

sys.path.insert(0, str(REPO_ROOT))

from abm_engine.database import db as db_module  # noqa: E402
db_module.DB_PATH = tmp_db  # redirect every get_conn() call in this process to the copy

from abm_engine.workflow import sequence_engine, sequence_db as sdb  # noqa: E402
from abm_engine.workflow.send_window import is_within_send_window  # noqa: E402

passed = failed = 0


def check(label: str, condition: bool, detail: str = ""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}  {detail}")


# ── 1. Schema + backfill ──────────────────────────────────────────────────────
print("\n[1] ensure_default_sequence + backfill_enrollments")
seq_id = sequence_engine.ensure_default_sequence()
steps = sdb.get_steps(seq_id)
check("default sequence has 5 steps", len(steps) == 5, f"got {len(steps)}")
check("step 5 is final", steps[-1]["is_final"] == 1)
check("step wait is 3 days", all(s["wait_days_after_previous"] == 3 for s in steps))

result = sequence_engine.backfill_enrollments()
print(f"       backfill result: {result}")
conn = db_module.get_conn()
total_contacts = conn.execute("SELECT COUNT(*) FROM contacts WHERE is_active=1").fetchone()[0]
total_enrolled = sdb.get_enrollment_counts().get("total", 0)
check("every active contact is enrolled", total_enrolled >= total_contacts,
      f"contacts={total_contacts} enrollments={total_enrolled}")

# ── 2. Compliance gate: do_not_contact / consent_status / replied ────────────
print("\n[2] Compliance gates")
row = conn.execute("""
    SELECT id FROM contacts
    WHERE is_active=1 AND COALESCE(do_not_contact,0)=0 AND replied=0
    LIMIT 1
""").fetchone()
if row:
    test_contact_id = row[0]
    before = {r["id"] for r in sequence_engine.get_contacts_due(limit=10000)}
    with conn:
        conn.execute("UPDATE contacts SET do_not_contact=1 WHERE id=?", (test_contact_id,))
        conn.execute("""
            UPDATE sequence_enrollments SET updated_at=datetime('now','-10 days'),
            enrolled_at=datetime('now','-10 days') WHERE contact_id=?
        """, (test_contact_id,))
    after = {r["id"] for r in sequence_engine.get_contacts_due(limit=10000)}
    check("do_not_contact=1 excludes the contact from get_contacts_due",
          test_contact_id not in after, f"contact {test_contact_id} still present")
    with conn:  # restore
        conn.execute("UPDATE contacts SET do_not_contact=0 WHERE id=?", (test_contact_id,))
else:
    print("  SKIP  no eligible contact found to test compliance gate on")

# ── 3. Cadence: a contact who was just advanced isn't due again immediately ──
print("\n[3] Cadence respected")
row = conn.execute("""
    SELECT c.id FROM contacts c
    JOIN sequence_enrollments e ON e.contact_id=c.id AND e.status='ACTIVE'
    WHERE c.is_active=1 AND c.replied=0 AND COALESCE(c.do_not_contact,0)=0
    LIMIT 1
""").fetchone()
if row:
    cid = row[0]
    with conn:
        conn.execute("""
            UPDATE sequence_enrollments SET current_step=1, updated_at=datetime('now')
            WHERE contact_id=?
        """, (cid,))
    due_now = {r["id"] for r in sequence_engine.get_contacts_due(limit=10000)}
    check("contact just touched today is NOT due again same day", cid not in due_now)

    with conn:
        conn.execute("""
            UPDATE sequence_enrollments SET updated_at=datetime('now','-4 days')
            WHERE contact_id=?
        """, (cid,))
    due_later = {r["id"] for r in sequence_engine.get_contacts_due(limit=10000)}
    check("same contact IS due after wait_days_after_previous elapses", cid in due_later)
else:
    print("  SKIP  no active enrollment found to test cadence on")

# ── 4. advance() / pause() state transitions ─────────────────────────────────
print("\n[4] advance() / pause()")
row = conn.execute("SELECT id FROM contacts WHERE is_active=1 LIMIT 1").fetchone()
test_cid = row[0]
seq = sdb.sequence_for_relationship_type(None) or {"id": seq_id}
sdb.pause_all_for_contact(test_cid, "test-reset")
conn.execute("DELETE FROM sequence_enrollments WHERE contact_id=?", (test_cid,))
conn.commit()
eid = sdb.enroll(test_cid, seq_id, current_step=0)
for i in range(4):
    sequence_engine.advance(test_cid)
enrollment = sdb.get_enrollment(test_cid, seq_id)
check("after 4 advances, current_step==4 and still ACTIVE",
      enrollment["current_step"] == 4 and enrollment["status"] == "ACTIVE", str(enrollment))
sequence_engine.advance(test_cid)  # 5th advance -> final step
enrollment = sdb.get_enrollment(test_cid, seq_id)
check("after 5th (final) advance, status==COMPLETED",
      enrollment["status"] == "COMPLETED", str(enrollment))

eid2 = sdb.enroll(test_cid + 1 if test_cid > 1 else test_cid, seq_id, current_step=0) if False else None
sequence_engine.pause(test_cid, "unit-test-pause")
# re-enroll fresh + pause to test pause path independent of completion
conn.execute("DELETE FROM sequence_enrollments WHERE contact_id=?", (test_cid,))
conn.commit()
sdb.enroll(test_cid, seq_id, current_step=0)
sequence_engine.pause(test_cid, "replied")
enrollment = sdb.get_enrollment(test_cid, seq_id)
check("pause() sets status=PAUSED with reason recorded",
      enrollment["status"] == "PAUSED" and enrollment["pause_reason"] == "replied", str(enrollment))

# ── 5. KSA send window ────────────────────────────────────────────────────────
print("\n[5] KSA send window (T-TIME-2)")
riyadh = ZoneInfo("Asia/Riyadh")
friday_noon = datetime(2026, 7, 17, 12, 0, tzinfo=riyadh)   # 2026-07-17 is a Friday
sunday_10am = datetime(2026, 7, 19, 10, 0, tzinfo=riyadh)   # 2026-07-19 is a Sunday
sunday_11pm = datetime(2026, 7, 19, 23, 0, tzinfo=riyadh)

allowed, reason = is_within_send_window(friday_noon)
check("Friday noon is blocked", not allowed, reason)
allowed, reason = is_within_send_window(sunday_10am)
check("Sunday 10am is allowed", allowed, reason)
allowed, reason = is_within_send_window(sunday_11pm)
check("Sunday 11pm (outside business hours) is blocked", not allowed, reason)

# ── Cleanup ────────────────────────────────────────────────────────────────────
shutil.rmtree(tmp_dir, ignore_errors=True)

print(f"\n{'='*60}\n{passed} passed, {failed} failed\n{'='*60}")
sys.exit(1 if failed else 0)
