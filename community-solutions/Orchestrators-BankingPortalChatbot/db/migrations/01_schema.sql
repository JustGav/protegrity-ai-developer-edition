-- ──────────────────────────────────────────────────────────────────
-- 01_schema.sql  — Banking Portal schema
--
-- Executed automatically by the Postgres Docker container on first
-- start (files in /docker-entrypoint-initdb.d/ are run in name order).
-- ──────────────────────────────────────────────────────────────────

-- ── customers ──────────────────────────────────────────────────────
-- Scalar columns are indexed for fast look-up; the full protected
-- record is also stored as JSONB so nothing is lost.
CREATE TABLE IF NOT EXISTS customers (
    customer_id     TEXT        PRIMARY KEY,
    username        TEXT        NOT NULL UNIQUE,
    password_hash   TEXT        NOT NULL,
    name            TEXT,           -- Protegrity-tokenised display name
    dob             TEXT,           -- tokenised
    ssn             TEXT,           -- tokenised
    email           TEXT,           -- tokenised
    phone           TEXT,           -- tokenised
    address         TEXT,           -- tokenised
    data            JSONB       NOT NULL    -- full protected JSON record
);

CREATE INDEX IF NOT EXISTS idx_customers_username ON customers (username);

-- ── accounts ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS accounts (
    account_id      TEXT        PRIMARY KEY,
    customer_id     TEXT        NOT NULL REFERENCES customers (customer_id) ON DELETE CASCADE,
    account_number  TEXT        NOT NULL,
    routing_number  TEXT,
    type            TEXT,
    balance         NUMERIC(15, 2),
    currency        TEXT        DEFAULT 'USD',
    opened_date     DATE,
    status          TEXT
);

CREATE INDEX IF NOT EXISTS idx_accounts_customer ON accounts (customer_id);

-- ── credit_cards ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS credit_cards (
    card_id         TEXT        PRIMARY KEY,
    customer_id     TEXT        NOT NULL REFERENCES customers (customer_id) ON DELETE CASCADE,
    card_number     TEXT,           -- tokenised
    card_type       TEXT,
    card_tier       TEXT,
    expiration      TEXT,
    cvv             TEXT,           -- tokenised
    credit_limit    NUMERIC(15, 2),
    current_balance NUMERIC(15, 2),
    available_credit NUMERIC(15, 2),
    status          TEXT,
    reward_points   INTEGER
);

CREATE INDEX IF NOT EXISTS idx_cards_customer ON credit_cards (customer_id);

-- ── transactions ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS transactions (
    transaction_id  TEXT        PRIMARY KEY,
    customer_id     TEXT        NOT NULL REFERENCES customers (customer_id) ON DELETE CASCADE,
    account_id      TEXT,
    date            TIMESTAMP,
    category        TEXT,
    merchant        TEXT,
    amount          NUMERIC(15, 2),
    type            TEXT,
    description     TEXT,
    status          TEXT
);

CREATE INDEX IF NOT EXISTS idx_transactions_customer ON transactions (customer_id);
CREATE INDEX IF NOT EXISTS idx_transactions_date    ON transactions (date DESC);
