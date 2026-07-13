-- ═══════════════════════════════════════════════════════════════
-- ABM INTELLIGENCE PLATFORM V2 — Account-First Schema
-- ═══════════════════════════════════════════════════════════════

-- ┌─────────────────────────────────────────────────┐
-- │  LAYER 1: ACCOUNTS (the anchor for everything)  │
-- └─────────────────────────────────────────────────┘
CREATE TABLE accounts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE,
    name_ar         TEXT,                          -- Arabic name
    segment         TEXT,                          -- Commercial Bank, Digital Bank, BNPL, SME Lending, Payments, Insurance
    sub_segment     TEXT,                          -- Islamic, Conventional, Neo, etc.
    country         TEXT DEFAULT 'KSA',
    website         TEXT,
    employees       INTEGER,
    assets_usd      REAL,                          -- Total assets in USD billions
    founded         TEXT,
    -- Digital maturity
    digital_maturity INTEGER DEFAULT 5,            -- 1-10 scale
    core_banking    TEXT,                           -- Temenos, Mambu, Finastra, etc.
    open_banking    TEXT DEFAULT 'Unknown',         -- Active, Planned, None, Unknown
    -- Status
    tier            TEXT DEFAULT 'Tier 3',          -- Tier 1, Tier 2, Tier 3
    priority        TEXT DEFAULT 'COLD',            -- HOT, WARM, COLD
    status          TEXT DEFAULT 'Prospect',        -- Prospect, Engaged, Opportunity, Customer, Lost
    score           INTEGER DEFAULT 0,              -- Composite score 0-100
    -- Ownership
    owner           TEXT DEFAULT 'Puneet',
    -- Timestamps
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now')),
    last_signal_at  TEXT,
    last_touch_at   TEXT
);

-- ┌─────────────────────────────────────────────────┐
-- │  LAYER 2: CONTACTS (linked to accounts)         │
-- └─────────────────────────────────────────────────┘
CREATE TABLE contacts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id      INTEGER REFERENCES accounts(id),
    full_name       TEXT NOT NULL,
    role            TEXT,
    department      TEXT,                           -- Retail, Lending, Technology, Innovation, Risk
    seniority       TEXT,                           -- C-Suite, VP, Director, Manager
    persona         TEXT,                           -- Decision Maker, Influencer, Champion, Blocker, User
    decision_weight INTEGER DEFAULT 5,              -- 1-10: how much this person influences buying
    -- Contact info
    email           TEXT,
    email_confidence TEXT DEFAULT 'Unknown',        -- Verified, Likely, Guessed, Unknown
    phone           TEXT,
    whatsapp        TEXT,
    linkedin_url    TEXT,
    -- Status
    warmness        TEXT DEFAULT 'Cold',            -- Hot, Warm, Cold
    is_ksa_national INTEGER DEFAULT 0,
    -- Compliance
    consent_status  TEXT DEFAULT 'none',            -- none, opted_in, denied
    consent_date    TEXT,
    consent_source  TEXT,
    do_not_contact  INTEGER DEFAULT 0,
    -- Metadata
    data_source     TEXT,                           -- Apollo, LinkedIn, Manual, Conference
    background_notes TEXT,
    is_active       INTEGER DEFAULT 1,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

-- ┌─────────────────────────────────────────────────┐
-- │  LAYER 3: PRODUCTS (Decimal's catalog)          │
-- └─────────────────────────────────────────────────┘
CREATE TABLE products (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE,
    category        TEXT,                           -- Platform, Module, Service
    description     TEXT,
    target_segments TEXT,                           -- JSON array: ["Commercial Bank","Digital Bank"]
    key_benefits    TEXT,
    competitors     TEXT                            -- JSON array: ["Temenos","Mambu"]
);

-- ┌─────────────────────────────────────────────────┐
-- │  LAYER 4: PRODUCT FIT (account × product)       │
-- └─────────────────────────────────────────────────┘
CREATE TABLE product_fit (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id      INTEGER REFERENCES accounts(id),
    product_id      INTEGER REFERENCES products(id),
    fit_score       INTEGER DEFAULT 50,             -- 0-100
    fit_reason      TEXT,
    pitch_angle     TEXT,
    objection_notes TEXT,
    UNIQUE(account_id, product_id)
);

-- ┌─────────────────────────────────────────────────┐
-- │  LAYER 5: SIGNALS (attributed to accounts)      │
-- └─────────────────────────────────────────────────┘
CREATE TABLE signals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id      INTEGER REFERENCES accounts(id),  -- NULL = unattributed
    signal_type     TEXT,                              -- leadership_change, regulatory, product_launch, hiring, funding, partnership
    source          TEXT,                              -- Google News, SAMA, LinkedIn, Job Board
    title           TEXT,
    summary         TEXT,
    url             TEXT UNIQUE,
    urgency         TEXT DEFAULT 'LOW',                -- HIGH, MEDIUM, LOW
    relevance       TEXT DEFAULT 'NEW',
    product_match   TEXT,                              -- Which Decimal product this signal maps to
    is_read         INTEGER DEFAULT 0,
    is_actioned     INTEGER DEFAULT 0,                 -- Has outreach been triggered?
    created_at      TEXT DEFAULT (datetime('now'))
);

-- ┌─────────────────────────────────────────────────┐
-- │  LAYER 6: ACCOUNT SCORES (daily recalculation)  │
-- └─────────────────────────────────────────────────┘
CREATE TABLE account_scores (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id      INTEGER REFERENCES accounts(id),
    score_date      TEXT DEFAULT (date('now')),
    -- Component scores
    signal_score    INTEGER DEFAULT 0,              -- 0-35
    regulatory_score INTEGER DEFAULT 0,             -- 0-30
    reachability_score INTEGER DEFAULT 0,           -- 0-20
    relationship_score INTEGER DEFAULT 0,           -- 0-15
    -- Composite
    total_score     INTEGER DEFAULT 0,              -- 0-100
    tier            TEXT,                            -- HOT (>=75), WARM (>=50), COLD (<50)
    score_notes     TEXT,
    UNIQUE(account_id, score_date)
);

-- ┌─────────────────────────────────────────────────┐
-- │  LAYER 7: RELATIONSHIPS (warm paths)            │
-- └─────────────────────────────────────────────────┘
CREATE TABLE relationships (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    from_type       TEXT,                           -- decimal, vendor, partner, investor, consultant
    from_name       TEXT,
    from_contact    TEXT,
    to_account_id   INTEGER REFERENCES accounts(id),
    to_contact_id   INTEGER REFERENCES contacts(id),
    relationship_type TEXT,                         -- knows, introduced_by, met_at, referred_by, worked_with
    strength        TEXT DEFAULT 'Weak',            -- Strong, Medium, Weak
    context         TEXT,                           -- "Met at GITEX 2025", "Ex-Deloitte colleague"
    last_interaction TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

-- ┌─────────────────────────────────────────────────┐
-- │  LAYER 8: OPPORTUNITIES (pipeline tracking)     │
-- └─────────────────────────────────────────────────┘
CREATE TABLE opportunities (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id      INTEGER REFERENCES accounts(id),
    product_id      INTEGER REFERENCES products(id),
    stage           TEXT DEFAULT 'Identified',      -- Identified, Contacted, Meeting, Proposal, Negotiation, Won, Lost
    probability     INTEGER DEFAULT 10,             -- 0-100%
    estimated_value TEXT,
    currency        TEXT DEFAULT 'SAR',
    champion_id     INTEGER REFERENCES contacts(id),
    next_step       TEXT,
    notes           TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now')),
    closed_at       TEXT
);

-- ┌─────────────────────────────────────────────────┐
-- │  LAYER 9: BUYING COMMITTEE (per account)        │
-- └─────────────────────────────────────────────────┘
CREATE TABLE buying_committee (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id      INTEGER REFERENCES accounts(id),
    contact_id      INTEGER REFERENCES contacts(id),
    product_id      INTEGER REFERENCES products(id),
    committee_role  TEXT,                            -- Decision Maker, Influencer, Champion, Blocker, User, Approver
    engagement      TEXT DEFAULT 'Unknown',          -- Engaged, Neutral, Unknown, Resistant
    notes           TEXT,
    UNIQUE(account_id, contact_id, product_id)
);

-- ┌─────────────────────────────────────────────────┐
-- │  EXECUTION TABLES (evolved from V8)             │
-- └─────────────────────────────────────────────────┘
CREATE TABLE drafts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id      INTEGER REFERENCES accounts(id),
    contact_id      INTEGER REFERENCES contacts(id),
    channel         TEXT DEFAULT 'email',
    subject         TEXT,
    body            TEXT,
    status          TEXT DEFAULT 'pending',
    source          TEXT DEFAULT 'ai',
    signal_id       INTEGER REFERENCES signals(id),  -- Which signal triggered this draft
    product_id      INTEGER REFERENCES products(id), -- Which product is being pitched
    sequence_step   INTEGER DEFAULT 1,               -- Touch 1, 2, 3...
    created_at      TEXT DEFAULT (datetime('now')),
    reviewed_at     TEXT,
    sent_at         TEXT,
    reviewer_notes  TEXT
);

CREATE TABLE touch_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id      INTEGER REFERENCES accounts(id),
    contact_id      INTEGER REFERENCES contacts(id),
    channel         TEXT,
    subject         TEXT,
    body            TEXT,
    status          TEXT,
    signal_id       INTEGER,
    sent_at         TEXT DEFAULT (datetime('now'))
);

CREATE TABLE templates (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    channel         TEXT DEFAULT 'email',
    subject         TEXT,
    body            TEXT,
    product_id      INTEGER REFERENCES products(id),
    persona_target  TEXT,                            -- Which persona type this template targets
    sequence_step   INTEGER DEFAULT 1,
    is_active       INTEGER DEFAULT 1,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

-- Existing tables carried forward
CREATE TABLE audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT, details TEXT,
    timestamp TEXT DEFAULT (datetime('now'))
);

CREATE TABLE unsubscribes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE, token TEXT,
    unsubscribed_at TEXT DEFAULT (datetime('now'))
);

-- ┌─────────────────────────────────────────────────┐
-- │  INDEXES                                         │
-- └─────────────────────────────────────────────────┘
CREATE INDEX idx_contacts_account ON contacts(account_id);
CREATE INDEX idx_signals_account ON signals(account_id);
CREATE INDEX idx_signals_type ON signals(signal_type);
CREATE INDEX idx_drafts_account ON drafts(account_id);
CREATE INDEX idx_drafts_contact ON drafts(contact_id);
CREATE INDEX idx_drafts_status ON drafts(status);
CREATE INDEX idx_scores_account ON account_scores(account_id);
CREATE INDEX idx_opportunities_account ON opportunities(account_id);
CREATE INDEX idx_touch_account ON touch_log(account_id);
CREATE INDEX idx_buying_account ON buying_committee(account_id);
