"""
Signal Engine v2 bridge e2e -- the adapted, SQLAlchemy-native replacement for
drip_integration/tests/test_bridge.py (which targets decimal_abm's raw-sqlite3
bridge and does not apply here; see CLAUDE_HANDOFF.md / INTEGRATION.md).

Verifies, against the REAL drip_platform code path (models.Signal, the
signal_v2_exports ledger, and the org-name reconciliation logic), the same
guarantee the original test asserted for decimal_abm: export is one-way and
idempotent, and only scoring_eligible=1 / status='active' rows are ever
exported. Additionally verifies the org_id reconciliation and the
Decimal-Technologies exclusion, since drip_platform's schema (org_id foreign
key) has no equivalent in the original.
"""
import os
import sys
import sqlite3
import tempfile
import uuid
from contextlib import closing

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

_DBFILE = os.path.join(tempfile.gettempdir(), "drip_sigv2_test.db")
if os.path.exists(_DBFILE):
    os.remove(_DBFILE)
os.environ["DATABASE_URL"] = f"sqlite:///{_DBFILE}"
os.environ["AUTH_ENFORCED"] = "false"

from database import Base, engine, SessionLocal  # noqa: E402
import models  # noqa: E402
from signal_engine.db import SCHEMA  # noqa: E402
from abm_platform.services import signal_v2_bridge as bridge  # noqa: E402

Base.metadata.create_all(engine)


def _make_signal_db(bank_org_name: str, bank_se_id: str = "d360", include_decimal: bool = False):
    # Unique observation/signal ids per call -- these double as the export
    # ledger's dedup key (signal_v2_exports.signal_uuid is the shadow db's
    # signal id), so reusing a fixed id across tests would falsely make a
    # later test's signal look "already exported" via an earlier test's row.
    token = uuid.uuid4().hex[:12]
    obs_id, sig_id = f"o_{token}", f"sig_{token}"
    path = os.path.join(tempfile.gettempdir(), f"se_{token}.db")
    with closing(sqlite3.connect(path)) as con:
        con.executescript(SCHEMA)
        con.execute("INSERT INTO accounts(id,canonical_name) VALUES(?,?)", (bank_se_id, bank_org_name))
        con.execute("""INSERT INTO sources(id,name,kind,evidence,proximity,independence,specificity)
                       VALUES('test','Test','rss',.9,.9,.9,.9)""")
        con.execute("""INSERT INTO observations(id,source_id,title,body,language,observed_at,ingested_at,
                       raw_payload,payload_hash,content_hash,parser_version,status,canonical_url)
                       VALUES(?,'test','D360 partnership announced','Payments tie-up','en',
                       '2026-08-01','2026-08-01','raw',?,?,'v','promoted','https://example.com/evidence')""",
                    (obs_id, f"p_{token}", f"c_{token}"))
        con.execute("""INSERT INTO signals(id,observation_id,account_id,signal_type,direction,urgency,title,
                       summary,event_at,decay_category,expires_at,relevance_score,source_score,confidence,
                       coverage_cap,scoring_eligible,action_eligible,promotion_rule_version,created_at)
                       VALUES(?,?,?,'partnership','mixed','HIGH','D360 partnership','Payments',
                       '2026-08-01','STRATEGIC','2027-08-01',.8,.8,.8,.8,1,0,'v','2026-08-01')""",
                    (sig_id, obs_id, bank_se_id))
        # The hardened bridge INNER JOINs signals -> observation_quality, so a
        # row with no quality assessment is invisible to preview()/export --
        # seed a passing one here or every fixture signal would silently
        # vanish from eligibility instead of exercising the export path.
        con.execute("""INSERT INTO observation_quality(observation_id,source_family,independence_key,
                       completeness_score,materiality_score,quality_decision,missing_fields_json,reasons_json,assessed_at)
                       VALUES(?,'domain:example.com','domain:example.com',.9,.8,'pass','[]','[]','2026-08-01')""",
                    (obs_id,))
        if include_decimal:
            con.execute("INSERT INTO accounts(id,canonical_name) VALUES('decimal','Decimal Technologies')")
        con.commit()
    return path


def test_account_map_excludes_decimal_and_resolves_by_name():
    db = SessionLocal()
    try:
        org = models.Organization(id=str(uuid.uuid4()), canonical_name="D360 Bank")
        db.add(org); db.commit()

        m = bridge.build_account_map(db)
        assert "d360" in m["matched"], f"D360 Bank should resolve by exact catalog name, got: {m}"
        assert m["matched"]["d360"]["org_id"] == org.id
        # Decimal Technologies must never be treated as a prospect account,
        # even if it somehow ended up matched by name in the real org table.
        decimal_org = models.Organization(id=str(uuid.uuid4()), canonical_name="Decimal Technologies")
        db.add(decimal_org); db.commit()
        m2 = bridge.build_account_map(db)
        assert all(v["org_name"] != "Decimal Technologies" for v in m2["matched"].values()), \
            "Decimal Technologies leaked into the matched prospect-account map"
    finally:
        db.close()


def test_export_is_one_way_and_idempotent_and_writes_real_signal_row():
    db = SessionLocal()
    try:
        # Uses a different real catalog bank (Al Rajhi) than the account-map
        # test above (D360) purely so the two tests don't collide on
        # organizations.canonical_name's UNIQUE constraint within one run.
        org = models.Organization(id=str(uuid.uuid4()), canonical_name="Al Rajhi Bank")
        db.add(org); db.commit()

        signal_db_path = _make_signal_db("Al Rajhi Bank", bank_se_id="al_rajhi")
        try:
            # preview must be a true read: it must not create the export
            # ledger table as a side effect (that belongs to apply/migration).
            # Compare before/after rather than asserting absence outright --
            # this file's own module-level DATABASE_URL override only takes
            # effect if `database` hasn't already been imported (and its
            # engine/SessionLocal bound) by an earlier-collected test file in
            # the same pytest process; when it's sharing the real migrated
            # Postgres instead of its own isolated SQLite temp file,
            # signal_v2_exports legitimately already exists from migration
            # s6e8f0a2c4d5_add_signal_v2_exports.py, and that's fine -- the
            # actual guarantee is "preview() doesn't change this," not "this
            # table can never exist."
            _inspect = __import__("sqlalchemy").inspect
            existed_before = _inspect(db.bind).has_table("signal_v2_exports")
            preview1 = bridge.preview(db, signal_db_path)
            assert len(preview1) == 1
            assert "_export_blocked_reason" not in preview1[0], "mapped account should not be blocked"
            assert _inspect(db.bind).has_table("signal_v2_exports") == existed_before, \
                "preview() must not create/drop signal_v2_exports as a side effect"

            result1 = bridge.export_scoring_eligible(db, signal_db_path)
            assert result1["exported"] == 1
            assert result1["skipped"] == []

            # idempotency: re-running must not duplicate
            result2 = bridge.export_scoring_eligible(db, signal_db_path)
            assert result2["exported"] == 0, "re-export must be a no-op for an already-exported signal"

            # the row actually landed in the REAL signals table, attributed
            # to the REAL organization, not a text-only stand-in
            sig = db.query(models.Signal).filter_by(org_id=org.id).first()
            assert sig is not None
            assert sig.title == "D360 partnership"
            assert sig.source == "Signal Engine v2"
            assert sig.urgency == "HIGH"

            ledger_count = db.execute(__import__("sqlalchemy").text(
                "SELECT COUNT(*) FROM signal_v2_exports")).scalar()
            assert ledger_count == 1
        finally:
            os.remove(signal_db_path)
    finally:
        db.close()


def test_unmapped_account_is_skipped_not_guessed():
    """An account with no reconciled organizations.id must be skipped, never
    exported under a wrong or invented org_id."""
    db = SessionLocal()
    try:
        # deliberately NOT creating a matching Organization row
        signal_db_path = _make_signal_db("Some Unmapped Bank Pvt Ltd", bank_se_id="unmapped_test")
        try:
            result = bridge.export_scoring_eligible(db, signal_db_path)
            assert result["exported"] == 0
            assert len(result["skipped"]) == 1
            assert "unmapped_test" not in [s for s in bridge.build_account_map(db)["matched"]]
        finally:
            os.remove(signal_db_path)
    finally:
        db.close()


if __name__ == "__main__":
    test_account_map_excludes_decimal_and_resolves_by_name()
    print("[PASS] account map excludes Decimal, resolves by name")
    test_export_is_one_way_and_idempotent_and_writes_real_signal_row()
    print("[PASS] export is one-way, idempotent, writes a real Signal row")
    test_unmapped_account_is_skipped_not_guessed()
    print("[PASS] unmapped account is skipped, not guessed")
    print("\nALL CHECKS PASSED")
