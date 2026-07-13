"""
End-to-end test for SIG-TENDER (manual RFP/tender field capture) and SIG-PARTNER
(partnership classification layer) — OPEN-GAP-SIG-02 and OPEN-GAP-SIG-06 in the
ABM Business Logic Bible's Signal Source Coverage Gaps doc.

Covers:
  - Creating an RFP signal persists deadline/estimated_value/scope_description/
    contact_person/source_of_knowledge, and defaults urgency to CRITICAL when left
    unset.
  - Creating a partnership signal mentioning a known competitor (Backbase) auto-
    classifies as COMPETITIVE_CLOSURE with matched_vendor="backbase", and defaults
    urgency to CRITICAL (competitive closure is the one partnership case that's
    CRITICAL by default).
  - Creating a partnership signal mentioning a known complementary vendor
    (Tarabut) auto-classifies as INTEGRATION_OPPORTUNITY, and does NOT default to
    CRITICAL urgency (falls back to MEDIUM, the generic default).
  - A partnership signal mentioning a regulator (SAMA) auto-classifies as
    COMPLIANCE_ALIGNMENT.
  - A partnership signal naming nothing in any registry stays unclassified
    (classification=None) without erroring.
  - An explicit urgency in the form always wins over the computed default.
  - An override on partner_classification always wins over auto-detection, and
    clears the matched_vendor (since it's now a human decision, not a text match).
  - Editing a signal via signal_edit re-applies the same logic (not just
    signal_new).
  - The initiatives list and bank_detail page both render the new urgency/tender/
    partnership fields without error for a live example of each type.
  - Full regression sweep: existing pages still load fine.

Run: python tests/test_signal_intel.py   (or point sys.path at your own checkout)
"""
import os
import sys

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "dashboard"))

from database import Base, engine, SessionLocal
import models
import app as dashboard_app

Base.metadata.create_all(bind=engine)
app = dashboard_app.app
app.config["TESTING"] = True
client = app.test_client()

results = []


def check(label, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    results.append((status, label, detail))
    print(f"[{status}] {label}" + (f" — {detail}" if detail and status == "FAIL" else ""))


db = SessionLocal()

bank = models.Organization(canonical_name="Signal Intel Test Bank")
db.add(bank); db.flush()
db.add(models.OrgTypeTag(org_id=bank.id, type_tag="commercial_bank"))
db.commit()
bank_id = bank.id
db.close()

# ── 1. RFP signal via signal_new POST, no urgency set ──
resp = client.post(f"/bank/{bank_id}/signal/new", data={
    "signal_type": "rfp",
    "source": "Contact call",
    "title": "Signal Intel Test Bank issues digital lending RFP",
    "summary": "Bank is running a formal RFP for a new digital lending platform.",
    "deadline": "2026-09-01",
    "estimated_value": "SAR 8-12M",
    "scope_description": "Core LOS replacement across retail + SME lending.",
    "contact_person": "Fahad Al-Otaibi, Head of Digital",
    "source_of_knowledge": "Heard from a vendor contact at a conference",
    "urgency": "",
}, follow_redirects=False)
check("RFP signal POST redirects (not error)", resp.status_code in (301, 302), f"status={resp.status_code}")

db = SessionLocal()
rfp_sig = db.query(models.Signal).filter_by(org_id=bank_id, signal_type="rfp").first()
check("RFP signal was created", rfp_sig is not None)
if rfp_sig:
    check("RFP deadline persisted", rfp_sig.deadline is not None and rfp_sig.deadline.strftime("%Y-%m-%d") == "2026-09-01",
          f"deadline={rfp_sig.deadline}")
    check("RFP estimated_value persisted", rfp_sig.estimated_value == "SAR 8-12M", f"got={rfp_sig.estimated_value}")
    check("RFP scope_description persisted", "LOS replacement" in (rfp_sig.scope_description or ""))
    check("RFP contact_person persisted", rfp_sig.contact_person == "Fahad Al-Otaibi, Head of Digital")
    check("RFP source_of_knowledge persisted", "conference" in (rfp_sig.source_of_knowledge or ""))
    check("RFP urgency defaults to CRITICAL when left unset", rfp_sig.urgency == "CRITICAL", f"got={rfp_sig.urgency}")
    check("RFP partner_classification stays None (not a partnership)", rfp_sig.partner_classification is None)
    rfp_sig_id = rfp_sig.id
else:
    rfp_sig_id = None
db.close()

# ── 2. Partnership signal mentioning a competitor (Backbase) ──
resp = client.post(f"/bank/{bank_id}/signal/new", data={
    "signal_type": "partnership",
    "source": "News article",
    "title": "Signal Intel Test Bank signs MOU with Backbase",
    "summary": "Bank announced a strategic partnership with Backbase for digital banking.",
    "urgency": "",
}, follow_redirects=False)
check("Partnership(Backbase) signal POST redirects", resp.status_code in (301, 302), f"status={resp.status_code}")

db = SessionLocal()
backbase_sig = db.query(models.Signal).filter_by(org_id=bank_id, signal_type="partnership") \
    .filter(models.Signal.title.like("%Backbase%")).first()
check("Backbase partnership signal was created", backbase_sig is not None)
if backbase_sig:
    check("Backbase partnership classified COMPETITIVE_CLOSURE", backbase_sig.partner_classification == "COMPETITIVE_CLOSURE",
          f"got={backbase_sig.partner_classification}")
    check("Backbase partnership matched_vendor == 'backbase'", backbase_sig.partner_classification_matched_vendor == "backbase",
          f"got={backbase_sig.partner_classification_matched_vendor}")
    check("Competitive-closure partnership defaults urgency to CRITICAL", backbase_sig.urgency == "CRITICAL",
          f"got={backbase_sig.urgency}")
db.close()

# ── 3. Partnership signal mentioning a complementary vendor (Tarabut) ──
resp = client.post(f"/bank/{bank_id}/signal/new", data={
    "signal_type": "partnership",
    "source": "News article",
    "title": "Signal Intel Test Bank integrates Tarabut open banking APIs",
    "summary": "Bank partners with Tarabut Gateway to enable open banking connectivity.",
    "urgency": "",
}, follow_redirects=False)
check("Partnership(Tarabut) signal POST redirects", resp.status_code in (301, 302), f"status={resp.status_code}")

db = SessionLocal()
tarabut_sig = db.query(models.Signal).filter_by(org_id=bank_id, signal_type="partnership") \
    .filter(models.Signal.title.like("%Tarabut%")).first()
check("Tarabut partnership signal was created", tarabut_sig is not None)
if tarabut_sig:
    check("Tarabut partnership classified INTEGRATION_OPPORTUNITY", tarabut_sig.partner_classification == "INTEGRATION_OPPORTUNITY",
          f"got={tarabut_sig.partner_classification}")
    check("Tarabut partnership matched_vendor == 'tarabut'", tarabut_sig.partner_classification_matched_vendor == "tarabut",
          f"got={tarabut_sig.partner_classification_matched_vendor}")
    check("Non-competitive partnership does NOT default to CRITICAL", tarabut_sig.urgency != "CRITICAL",
          f"got={tarabut_sig.urgency}")
    check("Non-competitive partnership defaults to MEDIUM", tarabut_sig.urgency == "MEDIUM", f"got={tarabut_sig.urgency}")
db.close()

# ── 4. Partnership signal mentioning a regulator (SAMA) ──
resp = client.post(f"/bank/{bank_id}/signal/new", data={
    "signal_type": "partnership",
    "source": "Regulatory filing",
    "title": "Signal Intel Test Bank joins SAMA open banking sandbox",
    "summary": "Bank signs onboarding agreement with SAMA for the open banking framework.",
    "urgency": "",
}, follow_redirects=False)
db = SessionLocal()
sama_sig = db.query(models.Signal).filter_by(org_id=bank_id, signal_type="partnership") \
    .filter(models.Signal.title.like("%SAMA%")).first()
check("SAMA partnership signal was created", sama_sig is not None)
if sama_sig:
    check("SAMA partnership classified COMPLIANCE_ALIGNMENT", sama_sig.partner_classification == "COMPLIANCE_ALIGNMENT",
          f"got={sama_sig.partner_classification}")
db.close()

# ── 5. Partnership signal with nothing in any registry ──
resp = client.post(f"/bank/{bank_id}/signal/new", data={
    "signal_type": "partnership",
    "source": "News article",
    "title": "Signal Intel Test Bank partners with local logistics firm",
    "summary": "A minor operational partnership announcement with no vendor named.",
    "urgency": "",
}, follow_redirects=False)
db = SessionLocal()
unclassified_sig = db.query(models.Signal).filter_by(org_id=bank_id, signal_type="partnership") \
    .filter(models.Signal.title.like("%logistics%")).first()
check("Unclassifiable partnership signal was created without erroring", unclassified_sig is not None)
if unclassified_sig:
    check("Unclassifiable partnership stays classification=None", unclassified_sig.partner_classification is None,
          f"got={unclassified_sig.partner_classification}")
    check("Unclassifiable partnership still gets a non-CRITICAL default urgency", unclassified_sig.urgency == "MEDIUM",
          f"got={unclassified_sig.urgency}")
db.close()

# ── 6. Explicit urgency always wins over computed default ──
resp = client.post(f"/bank/{bank_id}/signal/new", data={
    "signal_type": "partnership",
    "source": "News article",
    "title": "Signal Intel Test Bank partners with Backbase again",
    "summary": "Another Backbase mention, but this time urgency is explicitly downgraded.",
    "urgency": "LOW",
}, follow_redirects=False)
db = SessionLocal()
explicit_urgency_sig = db.query(models.Signal).filter_by(org_id=bank_id, signal_type="partnership") \
    .filter(models.Signal.title.like("%Backbase again%")).first()
check("Explicit urgency overrides computed CRITICAL default", explicit_urgency_sig is not None and explicit_urgency_sig.urgency == "LOW",
      f"got={explicit_urgency_sig.urgency if explicit_urgency_sig else None}")
db.close()

# ── 7. Manual classification override wins over auto-detect, clears matched_vendor ──
if backbase_sig:
    resp = client.post(f"/signal/{backbase_sig.id}/edit", data={
        "signal_type": "partnership",
        "source": backbase_sig.source or "",
        "title": backbase_sig.title or "",
        "summary": backbase_sig.summary or "",
        "urgency": "",
        "partner_classification": "NEUTRAL",
    }, follow_redirects=False)
    check("Signal edit with manual override redirects", resp.status_code in (301, 302), f"status={resp.status_code}")
    db = SessionLocal()
    edited = db.get(models.Signal, backbase_sig.id)
    check("Manual override (NEUTRAL) applied over auto-detected COMPETITIVE_CLOSURE", edited.partner_classification == "NEUTRAL",
          f"got={edited.partner_classification}")
    check("Manual override clears matched_vendor", edited.partner_classification_matched_vendor is None,
          f"got={edited.partner_classification_matched_vendor}")
    db.close()

# ── 8. Re-editing with override cleared (blank) falls back to auto-detect again ──
if backbase_sig:
    resp = client.post(f"/signal/{backbase_sig.id}/edit", data={
        "signal_type": "partnership",
        "source": backbase_sig.source or "",
        "title": backbase_sig.title or "",
        "summary": backbase_sig.summary or "",
        "urgency": "",
        "partner_classification": "",
    }, follow_redirects=False)
    db = SessionLocal()
    edited2 = db.get(models.Signal, backbase_sig.id)
    check("Clearing override re-triggers auto-detect back to COMPETITIVE_CLOSURE", edited2.partner_classification == "COMPETITIVE_CLOSURE",
          f"got={edited2.partner_classification}")
    db.close()

# ── 9. Editing an RFP signal's tender fields persists changes ──
if rfp_sig_id:
    resp = client.post(f"/signal/{rfp_sig_id}/edit", data={
        "signal_type": "rfp",
        "source": "Contact call",
        "title": "Signal Intel Test Bank issues digital lending RFP",
        "summary": "Updated: deadline pushed back.",
        "deadline": "2026-10-15",
        "estimated_value": "SAR 8-12M",
        "scope_description": "Core LOS replacement across retail + SME lending.",
        "contact_person": "Fahad Al-Otaibi, Head of Digital",
        "source_of_knowledge": "Heard from a vendor contact at a conference",
        "urgency": "",
    }, follow_redirects=False)
    db = SessionLocal()
    edited_rfp = db.get(models.Signal, rfp_sig_id)
    check("Editing RFP deadline persists the update", edited_rfp.deadline.strftime("%Y-%m-%d") == "2026-10-15",
          f"got={edited_rfp.deadline}")
    check("Re-saved RFP still defaults urgency to CRITICAL", edited_rfp.urgency == "CRITICAL", f"got={edited_rfp.urgency}")
    db.close()

# ── 11. Pages render without error for a live tender + partnership example ──
resp = client.get(f"/bank/{bank_id}")
check("bank_detail page loads with tender+partnership signals present", resp.status_code == 200, f"status={resp.status_code}")
body = resp.get_data(as_text=True)
check("bank_detail shows CRITICAL badge (not falling into gray default)", "CRITICAL" in body)
check("bank_detail shows a partner classification badge", "Integration Opportunity" in body or "Compliance Alignment" in body or "Competitive Closure" in body,
      "expected at least one classification label rendered")
check("bank_detail shows tender deadline block", "Deadline:" in body)

resp = client.get("/initiatives")
check("initiatives page loads", resp.status_code == 200, f"status={resp.status_code}")
body2 = resp.get_data(as_text=True)
check("initiatives page shows Urgency column header", "Urgency" in body2)
check("initiatives page shows a CRITICAL badge", "CRITICAL" in body2)

resp = client.get(f"/signal/{tarabut_sig.id}/edit" if tarabut_sig else f"/bank/{bank_id}/signal/new")
check("signal_edit page loads for a partnership signal", resp.status_code == 200, f"status={resp.status_code}")
body3 = resp.get_data(as_text=True)
check("signal_edit page shows partnership classification section", "Partnership classification" in body3)
check("signal_edit page shows tender fields section", "Tender / RFP details" in body3)

# ── 10. Switching a signal's type away from rfp clears tender-only fields ──
# (run after the page-render checks above, since this mutates the only RFP signal)
if rfp_sig_id:
    resp = client.post(f"/signal/{rfp_sig_id}/edit", data={
        "signal_type": "other",
        "source": "Contact call",
        "title": "Signal Intel Test Bank issues digital lending RFP",
        "summary": "No longer an RFP for test purposes.",
        "urgency": "",
    }, follow_redirects=False)
    db = SessionLocal()
    switched = db.get(models.Signal, rfp_sig_id)
    check("Switching signal_type away from rfp clears deadline", switched.deadline is None, f"got={switched.deadline}")
    check("Switching signal_type away from rfp clears estimated_value", switched.estimated_value is None)
    db.close()

# ── 12. Regression: existing pages still load fine ──
for path in ["/", "/persons", "/connectors", "/initiatives", "/uploads", "/uploads/new",
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
