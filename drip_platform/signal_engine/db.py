from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    aliases_json TEXT NOT NULL DEFAULT '[]',
    domains_json TEXT NOT NULL DEFAULT '[]',
    tickers_json TEXT NOT NULL DEFAULT '[]',
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT 'en',
    endpoint TEXT,
    evidence REAL NOT NULL,
    proximity REAL NOT NULL,
    independence REAL NOT NULL,
    specificity REAL NOT NULL,
    incentive_bias REAL NOT NULL DEFAULT 0.0,
    expected_interval_minutes INTEGER NOT NULL DEFAULT 1440,
    enabled INTEGER NOT NULL DEFAULT 1,
    last_attempt_at TEXT,
    last_success_at TEXT,
    last_error TEXT,
    consecutive_errors INTEGER NOT NULL DEFAULT 0,
    observations_total INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS source_runs (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(id),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    fetched_count INTEGER NOT NULL DEFAULT 0,
    accepted_count INTEGER NOT NULL DEFAULT 0,
    duplicate_count INTEGER NOT NULL DEFAULT 0,
    review_count INTEGER NOT NULL DEFAULT 0,
    rejected_count INTEGER NOT NULL DEFAULT 0,
    market_count INTEGER NOT NULL DEFAULT 0,
    corroborating_count INTEGER NOT NULL DEFAULT 0,
    error TEXT
    ,raw_payload BLOB
    ,payload_hash TEXT
);

CREATE TABLE IF NOT EXISTS observations (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(id),
    source_native_id TEXT,
    canonical_url TEXT,
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    language TEXT NOT NULL,
    published_at TEXT,
    observed_at TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    raw_payload TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    status TEXT NOT NULL,
    rejection_reason TEXT,
    UNIQUE(source_id, payload_hash)
);

CREATE INDEX IF NOT EXISTS idx_observations_content_hash ON observations(content_hash);
CREATE INDEX IF NOT EXISTS idx_observations_url ON observations(canonical_url);

CREATE TABLE IF NOT EXISTS observation_accounts (
    observation_id TEXT NOT NULL REFERENCES observations(id),
    account_id TEXT NOT NULL REFERENCES accounts(id),
    confidence REAL NOT NULL,
    reasons_json TEXT NOT NULL,
    selected INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (observation_id, account_id)
);

CREATE TABLE IF NOT EXISTS reviews (
    id TEXT PRIMARY KEY,
    observation_id TEXT NOT NULL REFERENCES observations(id),
    reason_code TEXT NOT NULL,
    detail TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    resolution TEXT
);

CREATE TABLE IF NOT EXISTS signals (
    id TEXT PRIMARY KEY,
    observation_id TEXT NOT NULL UNIQUE REFERENCES observations(id),
    account_id TEXT NOT NULL REFERENCES accounts(id),
    signal_type TEXT NOT NULL,
    direction TEXT NOT NULL,
    urgency TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    product_match TEXT,
    event_at TEXT NOT NULL,
    decay_category TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    relevance_score REAL NOT NULL,
    source_score REAL NOT NULL,
    confidence REAL NOT NULL,
    coverage_cap REAL NOT NULL,
    scoring_eligible INTEGER NOT NULL DEFAULT 0,
    action_eligible INTEGER NOT NULL DEFAULT 0,
    promotion_rule_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active'
);

CREATE INDEX IF NOT EXISTS idx_signals_account ON signals(account_id, event_at);
CREATE INDEX IF NOT EXISTS idx_reviews_status ON reviews(status, created_at);

CREATE TABLE IF NOT EXISTS signal_evidence (
    signal_id TEXT NOT NULL REFERENCES signals(id),
    observation_id TEXT NOT NULL UNIQUE REFERENCES observations(id),
    relationship TEXT NOT NULL CHECK(relationship IN ('primary','corroborating')),
    added_at TEXT NOT NULL,
    PRIMARY KEY(signal_id, observation_id)
);
CREATE INDEX IF NOT EXISTS idx_signal_evidence_signal ON signal_evidence(signal_id);

CREATE TABLE IF NOT EXISTS observation_quality (
    observation_id TEXT PRIMARY KEY REFERENCES observations(id),
    subject TEXT,
    action TEXT,
    object_text TEXT,
    event_date TEXT,
    location TEXT,
    source_family TEXT NOT NULL,
    independence_key TEXT NOT NULL,
    completeness_score REAL NOT NULL,
    materiality_score REAL NOT NULL,
    quality_decision TEXT NOT NULL,
    missing_fields_json TEXT NOT NULL,
    reasons_json TEXT NOT NULL,
    assessed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS claim_relations (
    id TEXT PRIMARY KEY,
    observation_id TEXT NOT NULL REFERENCES observations(id),
    related_signal_id TEXT NOT NULL REFERENCES signals(id),
    relation_type TEXT NOT NULL CHECK(relation_type IN ('contradicts','retracts','corrects')),
    confidence REAL NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    resolved_at TEXT,
    resolution TEXT,
    UNIQUE(observation_id,related_signal_id,relation_type)
);

CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS quality_feedback (
    id TEXT PRIMARY KEY,
    observation_id TEXT NOT NULL REFERENCES observations(id),
    review_id TEXT REFERENCES reviews(id),
    predicted_decision TEXT NOT NULL,
    human_decision TEXT NOT NULL,
    reason TEXT,
    created_at TEXT NOT NULL
);
"""


SOURCE_RUN_COLUMNS = {
    "rejected_count": "INTEGER NOT NULL DEFAULT 0",
    "market_count": "INTEGER NOT NULL DEFAULT 0",
    "corroborating_count": "INTEGER NOT NULL DEFAULT 0",
    "raw_payload": "BLOB",
    "payload_hash": "TEXT",
}

CLAIM_RELATION_COLUMNS = {
    "status": "TEXT NOT NULL DEFAULT 'pending'",
    "resolved_at": "TEXT",
    "resolution": "TEXT",
}


def connect(path: str | Path) -> sqlite3.Connection:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA busy_timeout = 30000")
    if str(db_path) != ":memory:":
        con.execute("PRAGMA journal_mode = WAL")
        con.execute("PRAGMA synchronous = NORMAL")
    return con


def initialize(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)
    existing = {row[1] for row in con.execute("PRAGMA table_info(source_runs)")}
    for name, declaration in SOURCE_RUN_COLUMNS.items():
        if name not in existing:
            con.execute(f"ALTER TABLE source_runs ADD COLUMN {name} {declaration}")
    existing = {row[1] for row in con.execute("PRAGMA table_info(claim_relations)")}
    for name, declaration in CLAIM_RELATION_COLUMNS.items():
        if name not in existing:
            con.execute(f"ALTER TABLE claim_relations ADD COLUMN {name} {declaration}")
    con.execute("INSERT INTO schema_meta(key,value) VALUES('schema_version','3') "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value")
    con.commit()
