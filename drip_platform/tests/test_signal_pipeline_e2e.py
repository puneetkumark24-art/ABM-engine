"""ABM signal pipeline, end to end: capture → CRM signal → account rescore.

Every earlier suite tested a stage in isolation, which is how the break this
file now guards against survived: capture, attribution, classification, decay,
the quality gate and the export ledger were each individually correct, and
signals for any account registered at RUN TIME still never reached the CRM.
`build_account_map()` iterated only the static 11-bank catalog, so
`Pipeline.add_account()` — which the API and collectors both use — produced
signals that were captured, scored, gated, and then dropped at the last step
with a skip reason blaming a "name mismatch".

So this drives the whole chain with real RSS bytes through the real code.
"""
import json
import os
import sqlite3
import sys
import tempfile

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from database import Base, engine, SessionLocal  # noqa: E402
import models  # noqa: E402
import models_ai, models_audit, models_collectors, models_crm2  # noqa: E402,F401
import models_ext, models_final, models_intel, models_jobs, models_llm  # noqa: E402,F401
import models_p10, models_p11, models_p12, models_s3, models_s6, models_s8  # noqa: E402,F401
import models_segments, models_tenant  # noqa: E402,F401
from signal_engine import db as sedb, pipeline as sepipe, capture as secap  # noqa: E402
from abm_platform.services import signal_v2_bridge as bridge, engagement  # noqa: E402

_results = []

FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
 <item>
  <title>Gulf Union Bank issues RFP for core banking modernisation</title>
  <link>https://example.invalid/news/gub-core-rfp</link>
  <description>Gulf Union Bank has issued a request for proposal covering core
   banking modernisation and digital onboarding across its retail network.</description>
  <pubDate>Mon, 28 Jul 2026 09:00:00 GMT</pubDate>
 </item>
 <item>
  <title>Unrelated football result</title>
  <link>https://example.invalid/news/sport</link>
  <description>A match ended two nil.</description>
  <pubDate>Tue, 29 Jul 2026 10:00:00 GMT</pubDate>
 </item>
</channel></rss>"""


def check(name, cond, detail=""):
    _results.append((name, bool(cond)))
    print(("PASS" if cond else "FAIL"), "-", name, ("| " + str(detail)) if detail else "")


def _signal_db() -> str:
    """A real signal_engine database on disk, with a RUNTIME-registered bank
    (deliberately not one of the catalog's 11)."""
    path = tempfile.mktemp(suffix=".signals.db")
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    sedb.initialize(con)
    secap.initialize_capture(con)
    p = sepipe.Pipeline(con)
    p.add_account("acc-gulf-union", "Gulf Union Bank",
                  aliases=["Gulf Union", "GUB"], domains=["gulfunion.invalid"])
    p.add_source("src-news", "KSA Banking News", "rss", "en",
                 "https://example.invalid/feed.xml",
                 evidence=0.8, proximity=0.6, independence=0.8, specificity=0.7)
    ing = p.ingest_feed("src-news", FEED)
    con.commit()
    return path, con, ing


def run():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    sig_path, con, ing = _signal_db()

    # ── capture ────────────────────────────────────────────────────────
    check("capture accepts the banking item and rejects the noise",
          ing["accepted"] >= 1 and ing["rejected"] >= 1, ing)
    rows = list(con.execute("SELECT * FROM signals"))
    check("exactly one signal was written", len(rows) == 1, f"{len(rows)} rows")
    sig = rows[0]
    check("it is attributed to the runtime-registered bank",
          sig["account_id"] == "acc-gulf-union", sig["account_id"])
    check("attribution carries a confidence", sig["confidence"] is not None,
          sig["confidence"])
    check("it is classified and given an urgency",
          bool(sig["signal_type"]) and bool(sig["urgency"]),
          f"{sig['signal_type']}/{sig['urgency']}")
    check("decay is set so the signal can go stale",
          bool(sig["decay_category"]) and sig["expires_at"] is not None,
          f"{sig['decay_category']} until {sig['expires_at']}")
    check("eligibility is decided, not left null",
          sig["scoring_eligible"] is not None and sig["action_eligible"] is not None,
          f"scoring={sig['scoring_eligible']} action={sig['action_eligible']}")
    check("action_eligible is 0 — shadow mode holds at the engine level",
          not sig["action_eligible"], sig["action_eligible"])

    # ── dedupe ─────────────────────────────────────────────────────────
    p2 = sepipe.Pipeline(con)
    p2.ingest_feed("src-news", FEED)
    check("re-ingesting the same feed adds nothing",
          con.execute("SELECT count(*) c FROM signals").fetchone()["c"] == 1)

    # ── the regression: a runtime account must be mappable ─────────────
    org = models.Organization(canonical_name="Gulf Union Bank")
    db.add(org); db.commit()

    catalog_only = bridge.build_account_map(db)
    check("the catalog-only map does NOT know the runtime account "
          "(this is what used to silently drop it)",
          "acc-gulf-union" not in catalog_only["matched"])

    full = bridge.build_account_map(db, sig_path)
    check("passing the signal database resolves the runtime account",
          "acc-gulf-union" in full["matched"], list(full["matched"])[:5])
    check("and it resolves to the right organization",
          full["matched"].get("acc-gulf-union", {}).get("org_id") == org.id)

    # ── export → CRM ───────────────────────────────────────────────────
    cands = bridge.preview(db, sig_path)
    check("preview offers the signal as a candidate", len(cands) == 1, len(cands))
    res = bridge.export_scoring_eligible(db, sig_path)
    check("export writes it into the CRM", res["exported"] == 1, res)
    check("nothing was skipped", not res["skipped"], res["skipped"])
    crm = db.query(models.Signal).all()
    check("one CRM signal row exists", len(crm) == 1, len(crm))
    check("linked to the right account", crm and crm[0].org_id == org.id)
    check("with the title carried across",
          crm and "RFP" in (crm[0].title or ""), crm and crm[0].title)

    res2 = bridge.export_scoring_eligible(db, sig_path)
    check("re-running the export is idempotent",
          db.query(models.Signal).count() == 1 and res2["exported"] == 0, res2)

    # ── and what comes after: the ABM score reacts ─────────────────────
    score = engagement.recompute_account_score(db, org.id)
    check("the exported signal moves the account's signal score",
          score is not None and score.signal_score > 0,
          getattr(score, "signal_score", None))
    acct = db.get(models.AccountIntelligence, org.id)
    check("the account tier is persisted for the ABM screens",
          acct is not None and acct.priority is not None,
          getattr(acct, "priority", None))

    # ── an unmapped account is reported, not guessed ───────────────────
    # Rename rather than delete: account_intelligence now references this org
    # (the rescore above created it), and the point being tested is name
    # resolution, not cascade behaviour.
    org.canonical_name = "Totally Different Bank"
    org.aliases = []
    db.commit()
    orphan = bridge.build_account_map(db, sig_path)
    check("with no matching organization it is listed as unmatched",
          "acc-gulf-union" in orphan["unmatched"])

    con.close()
    try:
        os.unlink(sig_path)
    except OSError:
        pass
    db.close()

    passed = sum(1 for _, ok in _results if ok)
    print(f"\n{passed}/{len(_results)} checks passed  "
          f"[DB: {os.environ.get('DATABASE_URL', '?').split(':')[0]}]")
    return passed == len(_results)


if __name__ == "__main__":
    sys.exit(0 if run() else 1)


def test_signal_pipeline_e2e():
    assert run()
