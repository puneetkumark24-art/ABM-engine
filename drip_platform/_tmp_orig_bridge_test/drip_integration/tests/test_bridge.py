from __future__ import annotations

import sqlite3
import sys
import unittest
import uuid
from contextlib import closing
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "drip_integration"))

from signal_engine.db import SCHEMA
from abm_engine.signal_integration.bridge import SignalBridge


DRIP_SCHEMA = """
CREATE TABLE signals (
 id INTEGER PRIMARY KEY AUTOINCREMENT,institution TEXT,signal_type TEXT,priority TEXT,headline TEXT,detail TEXT,
 source_url TEXT,source_name TEXT,score_impact INTEGER,detected_at TEXT,used_in_touch INTEGER
);
CREATE TABLE news_items (
 id INTEGER PRIMARY KEY AUTOINCREMENT,category TEXT,institution TEXT,contact_name TEXT,headline TEXT,summary TEXT,
 source_url TEXT,source_name TEXT,relevance_score INTEGER,detected_at TEXT,is_read INTEGER
);
"""


class BridgeTests(unittest.TestCase):
    def test_export_is_one_way_and_idempotent(self):
        token = uuid.uuid4().hex
        signal_db = ROOT / "work" / f"bridge_signal_{token}.db"
        drip_db = ROOT / "work" / f"bridge_drip_{token}.db"
        try:
            with closing(sqlite3.connect(signal_db)) as con:
                con.executescript(SCHEMA)
                con.execute("INSERT INTO accounts(id,canonical_name) VALUES('d360','D360 Bank')")
                con.execute("""INSERT INTO sources(id,name,kind,evidence,proximity,independence,specificity)
                               VALUES('test','Test','rss',.9,.9,.9,.9)""")
                con.execute("""INSERT INTO observations(id,source_id,title,body,language,observed_at,ingested_at,raw_payload,payload_hash,content_hash,parser_version,status,canonical_url)
                               VALUES('o','test','D360 partnership','Payments','en','2026-08-01','2026-08-01','raw','p','c','v','promoted','https://example.com/evidence')""")
                con.execute("""INSERT INTO signals(id,observation_id,account_id,signal_type,direction,urgency,title,summary,event_at,decay_category,expires_at,relevance_score,source_score,confidence,coverage_cap,scoring_eligible,action_eligible,promotion_rule_version,created_at)
                               VALUES('s','o','d360','partnership','mixed','HIGH','D360 partnership','Payments','2026-08-01','STRATEGIC','2027-08-01',.8,.8,.8,.8,1,0,'v','2026-08-01')""")
                con.commit()
            with closing(sqlite3.connect(drip_db)) as con:
                con.executescript(DRIP_SCHEMA)
            bridge = SignalBridge(signal_db, drip_db)
            self.assertEqual(len(bridge.preview()), 1)
            self.assertEqual(bridge.export_scoring_eligible()["exported"], 1)
            self.assertEqual(bridge.export_scoring_eligible()["exported"], 0)
            with closing(sqlite3.connect(drip_db)) as con:
                self.assertEqual(con.execute("SELECT COUNT(*) FROM signals").fetchone()[0], 1)
                self.assertEqual(con.execute("SELECT COUNT(*) FROM news_items").fetchone()[0], 1)
                self.assertEqual(con.execute("SELECT source_url FROM signals").fetchone()[0], "https://example.com/evidence")
        finally:
            signal_db.unlink(missing_ok=True)
            drip_db.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
