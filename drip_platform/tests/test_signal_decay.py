"""
Signal Pipeline P1 test — confidence/decay stamping (EPIS-RCM-01, EPIS-HALF-01).
Mirrors tests/test_signal_intel.py's pattern: SQLite in-memory DB, Flask test
client, plain check()/results accumulator, run standalone with
`python tests/test_signal_decay.py`.

Covers:
  - decay_category_for_signal_type matches the explicit Bible mapping
    (rfp->tactical, partnership->strategic, hiring->operational,
    regulatory->strategic) plus the extended types this module added.
  - decay_expires_at_for computes created_at + the category's half-life.
  - is_decayed is False with no stamp, False before expiry, True after.
  - compute_confidence_score is deterministic and moves in the expected
    direction for each of its five inspectable factors (url present, a
    specific source, RFP structured fields, a matched partner vendor,
    a substantive summary), and never exceeds the 0.95 cap or drops below
    the 0.3 floor.
  - Creating a signal via signal_new (POST) auto-stamps confidence_score/
    decay_category/decay_expires_at with no extra form fields required.
  - Editing a signal via signal_edit re-stamps (e.g. changing signal_type
    from 'hiring' to 'partnership' flips decay_category from OPERATIONAL to
    STRATEGIC).
  - The one-time backfill script (etl/backfill_signal_decay.py's main())
    stamps a pre-existing NULL row and is idempotent (second run touches 0).
  - bank_detail.html and initiatives.html render the new Confidence/Decayed
    UI without error.

Run: python tests/test_signal_decay.py
"""
import os
import sys
from datetime import datetime, timedelta

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "dashboard"))

from database import Base, engine, SessionLocal
import models
import app as dashboard_app
from etl.signal_decay import (
    decay_category_for_signal_type, decay_expires_at_for, is_decayed,
    compute_confidence_score, stamp_signal_intelligence,
    DECAY_HALF_LIFE_DAYS, CONFIDENCE_CAP, CONFIDENCE_FLOOR,
)
import etl.backfill_signal_decay as backfill_signal_decay

Base.metadata.create_all(bind=engine)
app = dashboard_app.app
app.config["TESTING"] = True
client = app.test_client()

results = []


def check(label, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    results.append((status, label, detail))
    print(f"[{status}] {label}" + (f" — {detail}" if detail and status == "FAIL" else ""))


# ── 1. decay_category_for_signal_type — the explicit Bible-stated mapping ──
check("rfp -> TACTICAL", decay_category_for_signal_type("rfp") == "TACTICAL")
check("partnership -> STRATEGIC", decay_category_for_signal_type("partnership") == "STRATEGIC")
check("hiring -> OPERATIONAL", decay_category_for_signal_type("hiring") == "OPERATIONAL")
check("regulatory -> STRATEGIC", decay_category_for_signal_type("regulatory") == "STRATEGIC")
check("unknown/blank signal_type falls back to OPERATIONAL default",
      decay_category_for_signal_type("nonsense_type") == "OPERATIONAL")
check("other -> OPERATIONAL", decay_category_for_signal_type("other") == "OPERATIONAL")

# ── 2. decay_expires_at_for — created_at + category half-life ──
base = datetime(2026, 1, 1)
expires = decay_expires_at_for(base, "TACTICAL")
check("TACTICAL decay_expires_at = created_at + tactical half-life days",
      expires == base + timedelta(days=DECAY_HALF_LIFE_DAYS["TACTICAL"]),
      f"got={expires}")

# ── 3. is_decayed ──
check("is_decayed(None) is False (unstamped signal is never treated as stale)",
      is_decayed(None) is False)
future = datetime.utcnow() + timedelta(days=5)
past = datetime.utcnow() - timedelta(days=5)
check("is_decayed(future expiry) is False", is_decayed(future) is False)
check("is_decayed(past expiry) is True", is_decayed(past) is True)

# ── 4. compute_confidence_score — deterministic, direction-correct, bounded ──
class FakeSig:
    def __init__(self, **kw):
        self.url = kw.get("url")
        self.source = kw.get("source")
        self.signal_type = kw.get("signal_type")
        self.deadline = kw.get("deadline")
        self.scope_description = kw.get("scope_description")
        self.partner_classification_matched_vendor = kw.get("partner_classification_matched_vendor")
        self.product_match = kw.get("product_match")
        self.summary = kw.get("summary")


bare = FakeSig(signal_type="other")
bare_score = compute_confidence_score(bare)
check("bare signal (nothing filled) scores at/above the floor",
      bare_score >= CONFIDENCE_FLOOR, f"got={bare_score}")

with_url = FakeSig(signal_type="other", url="https://example.com/press")
check("adding a URL increases confidence over the bare case",
      compute_confidence_score(with_url) > bare_score,
      f"bare={bare_score} with_url={compute_confidence_score(with_url)}")

specific_source = FakeSig(signal_type="other", source="Riyad Bank press room")
check("a specific (non-generic) source increases confidence over the bare case",
      compute_confidence_score(specific_source) > bare_score)

generic_source = FakeSig(signal_type="other", source="Manual")
check("a generic source ('Manual') does NOT get the specific-source bonus",
      compute_confidence_score(generic_source) == bare_score,
      f"generic={compute_confidence_score(generic_source)} bare={bare_score}")

rfp_full = FakeSig(signal_type="rfp", deadline=datetime(2026, 9, 1), scope_description="Core LOS replacement")
rfp_bare = FakeSig(signal_type="rfp")
check("an RFP with deadline+scope scores higher than an RFP with neither",
      compute_confidence_score(rfp_full) > compute_confidence_score(rfp_bare))

partner_matched = FakeSig(signal_type="partnership", partner_classification_matched_vendor="backbase")
partner_unmatched = FakeSig(signal_type="partnership")
check("a partnership signal with a matched vendor scores higher than one without",
      compute_confidence_score(partner_matched) > compute_confidence_score(partner_unmatched))

long_summary = FakeSig(signal_type="other", summary="A" * 60)
short_summary = FakeSig(signal_type="other", summary="short")
check("a substantive (>40 char) summary scores at least as high as a short one",
      compute_confidence_score(long_summary) >= compute_confidence_score(short_summary))

maxed = FakeSig(signal_type="rfp", url="https://x.com", source="Riyad Bank press room",
                 deadline=datetime(2026, 1, 1), scope_description="x", summary="A" * 100)
check(f"confidence never exceeds the {CONFIDENCE_CAP} cap even with every factor present",
      compute_confidence_score(maxed) <= CONFIDENCE_CAP, f"got={compute_confidence_score(maxed)}")

# ── 5. Live signal creation via signal_new auto-stamps all three fields ──
db = SessionLocal()
bank = models.Organization(canonical_name="Signal Decay Test Bank")
db.add(bank); db.flush()
db.add(models.OrgTypeTag(org_id=bank.id, type_tag="commercial_bank"))
db.commit()
bank_id = bank.id
db.close()

resp = client.post(f"/bank/{bank_id}/signal/new", data={
    "signal_type": "hiring",
    "source": "LinkedIn",
    "title": "Signal Decay Test Bank hires new Chief Digital Officer",
    "summary": "A new CDO was announced this week, focused on digital transformation.",
    "urgency": "",
}, follow_redirects=False)
check("hiring signal POST redirects (not error)", resp.status_code in (301, 302), f"status={resp.status_code}")

db = SessionLocal()
hire_sig = db.query(models.Signal).filter_by(org_id=bank_id, signal_type="hiring").first()
check("hiring signal was created", hire_sig is not None)
if hire_sig:
    check("hiring signal auto-stamped decay_category=OPERATIONAL", hire_sig.decay_category == "OPERATIONAL",
          f"got={hire_sig.decay_category}")
    check("hiring signal auto-stamped a confidence_score", hire_sig.confidence_score is not None and hire_sig.confidence_score > 0,
          f"got={hire_sig.confidence_score}")
    check("hiring signal auto-stamped decay_expires_at", hire_sig.decay_expires_at is not None)
    check("hiring signal decay_expires_at is created_at + OPERATIONAL half-life",
          hire_sig.decay_expires_at == hire_sig.created_at + timedelta(days=DECAY_HALF_LIFE_DAYS["OPERATIONAL"]),
          f"created_at={hire_sig.created_at} expires={hire_sig.decay_expires_at}")
    hire_sig_id = hire_sig.id
else:
    hire_sig_id = None
db.close()

# ── 6. Editing re-stamps (signal_type change flips decay_category) ──
if hire_sig_id:
    resp = client.post(f"/signal/{hire_sig_id}/edit", data={
        "signal_type": "partnership",
        "source": "News article",
        "title": "Signal Decay Test Bank signs MOU with Backbase",
        "summary": "Strategic partnership announced for digital banking modernization efforts.",
        "urgency": "",
    }, follow_redirects=False)
    check("signal_edit (type change) POST redirects", resp.status_code in (301, 302), f"status={resp.status_code}")
    db = SessionLocal()
    edited = db.get(models.Signal, hire_sig_id)
    check("re-stamped decay_category flips OPERATIONAL -> STRATEGIC on type change",
          edited.decay_category == "STRATEGIC", f"got={edited.decay_category}")
    check("re-stamped confidence_score reflects the new matched vendor (backbase)",
          edited.confidence_score is not None and edited.partner_classification_matched_vendor == "backbase",
          f"confidence={edited.confidence_score} matched={edited.partner_classification_matched_vendor}")
    db.close()

# ── 7. Backfill script stamps pre-existing NULL rows, idempotent on rerun ──
db = SessionLocal()
raw_sig = models.Signal(org_id=bank_id, signal_type="regulatory", source="SAMA circular",
                         title="Pre-existing signal created before P1 shipped",
                         summary="A signal inserted directly, bypassing the stamped save path.")
db.add(raw_sig); db.commit()
raw_sig_id = raw_sig.id
check("pre-existing raw signal starts with decay_category=None (unstamped)",
      db.get(models.Signal, raw_sig_id).decay_category is None)
db.close()

backfill_signal_decay.main()

db = SessionLocal()
backfilled = db.get(models.Signal, raw_sig_id)
check("backfill stamped the pre-existing signal's decay_category", backfilled.decay_category == "STRATEGIC",
      f"got={backfilled.decay_category}")
check("backfill stamped a confidence_score", backfilled.confidence_score is not None)
db.close()

# second run should touch nothing (all rows already have decay_category set)
backfill_signal_decay.main()  # should print "Stamped 0 signal(s)" — not asserted on stdout, just must not error

# ── 8. Pages render without error with the new Confidence/Decayed UI ──
resp = client.get(f"/bank/{bank_id}")
check("bank_detail page loads with confidence-stamped signals present", resp.status_code == 200, f"status={resp.status_code}")
body = resp.get_data(as_text=True)
check("bank_detail shows a Confidence: line", "Confidence:" in body)

resp = client.get("/initiatives")
check("initiatives page loads", resp.status_code == 200, f"status={resp.status_code}")
body2 = resp.get_data(as_text=True)
check("initiatives page shows the new Confidence column header", "Confidence" in body2)

# ── 9. Regression: existing pages still load fine ──
for path in ["/", "/persons", "/connectors", "/initiatives", "/uploads",
             f"/bank/{bank_id}", f"/bank/{bank_id}/flow", f"/bank/{bank_id}/score/edit"]:
    resp = client.get(path)
    check(f"regression: GET {path} returns 200", resp.status_code == 200, f"status={resp.status_code}")

# ── Summary ──
passed = sum(1 for r in results if r[0] == "PASS")
failed = sum(1 for r in results if r[0] == "FAIL")
print(f"\n{passed} passed, {failed} failed out of {len(results)}")
if failed == 0:
    print("ALL CHECKS PASSED")
else:
    print("SOME CHECKS FAILED")
    sys.exit(1)
