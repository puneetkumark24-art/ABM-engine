from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path


BRIDGE_SCHEMA = """
CREATE TABLE IF NOT EXISTS signal_v2_exports (
    signal_uuid TEXT PRIMARY KEY,
    drip_signal_id INTEGER,
    drip_news_id INTEGER,
    exported_at TEXT NOT NULL DEFAULT (datetime('now')),
    export_policy TEXT NOT NULL
);
"""


class SignalBridge:
    """One-way, idempotent export from signal-v2 into DRIP Intelligence.

    The bridge inserts only into DRIP's `signals`, `news_items`, and its own
    audit table. It has no dependency on drafts, contacts, or send providers.
    """

    def __init__(self, signal_db: str | Path, drip_db: str | Path):
        self.signal_db = Path(signal_db)
        self.drip_db = Path(drip_db)

    @staticmethod
    def _connect(path: Path) -> sqlite3.Connection:
        con = sqlite3.connect(path)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        return con

    def initialize(self) -> None:
        with closing(self._connect(self.drip_db)) as con:
            con.executescript(BRIDGE_SCHEMA)
            con.commit()

    def preview(self) -> list[dict]:
        """Return eligible, unexported records without changing either DB."""
        self.initialize()
        with closing(self._connect(self.signal_db)) as source, closing(self._connect(self.drip_db)) as target:
            exported = {r[0] for r in target.execute("SELECT signal_uuid FROM signal_v2_exports")}
            rows = source.execute(
                """SELECT s.*,a.canonical_name,o.canonical_url
                   FROM signals s JOIN accounts a ON a.id=s.account_id
                   JOIN observations o ON o.id=s.observation_id
                   WHERE s.status='active' AND s.scoring_eligible=1
                   ORDER BY s.event_at"""
            ).fetchall()
            return [dict(r) for r in rows if r["id"] not in exported]

    def export_scoring_eligible(self) -> dict:
        """Publish safe Intelligence records; never creates or approves drafts."""
        candidates = self.preview()
        exported = []
        with closing(self._connect(self.drip_db)) as con:
            for row in candidates:
                priority = "P1" if row["urgency"] == "CRITICAL" else "P2" if row["urgency"] == "HIGH" else "P3"
                impact = max(0, min(25, round(row["confidence"] * row["relevance_score"] * 25)))
                cur = con.execute(
                    """INSERT INTO signals(institution,signal_type,priority,headline,detail,source_url,source_name,
                       score_impact,detected_at,used_in_touch) VALUES(?,?,?,?,?,?,?,?,?,0)""",
                    (row["canonical_name"], row["signal_type"].upper(), priority, row["title"], row["summary"],
                     row["canonical_url"], "Signal Engine v2", impact, row["event_at"]),
                )
                drip_signal_id = cur.lastrowid
                cur = con.execute(
                    """INSERT INTO news_items(category,institution,headline,summary,source_url,source_name,
                       relevance_score,detected_at,is_read) VALUES(?,?,?,?,?,?,?,?,0)""",
                    (row["signal_type"].upper(), row["canonical_name"], row["title"], row["summary"], row["canonical_url"],
                     "Signal Engine v2", round(row["relevance_score"] * 10), row["event_at"]),
                )
                drip_news_id = cur.lastrowid
                con.execute(
                    "INSERT INTO signal_v2_exports(signal_uuid,drip_signal_id,drip_news_id,export_policy) VALUES(?,?,?,?)",
                    (row["id"], drip_signal_id, drip_news_id, "scoring-eligible-v1"),
                )
                exported.append(row["id"])
            con.commit()
        return {"eligible": len(candidates), "exported": len(exported), "signal_ids": exported}
