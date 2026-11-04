-- PostgreSQL schema for CryptoIntel (equivalent to cryptointel/db/models.py).
-- The application creates these tables automatically; this file is for DBAs/review.

CREATE TABLE IF NOT EXISTS candles (
    id          BIGSERIAL PRIMARY KEY,
    symbol      VARCHAR(32)  NOT NULL,
    category    VARCHAR(16)  NOT NULL,          -- linear | spot
    timeframe   VARCHAR(4)   NOT NULL,          -- 1m 5m 15m 1h 4h 1d 1w
    ts          TIMESTAMPTZ  NOT NULL,          -- candle open time (UTC)
    open        DOUBLE PRECISION NOT NULL,
    high        DOUBLE PRECISION NOT NULL,
    low         DOUBLE PRECISION NOT NULL,
    close       DOUBLE PRECISION NOT NULL,
    volume      DOUBLE PRECISION NOT NULL,
    turnover    DOUBLE PRECISION NOT NULL,
    CONSTRAINT uq_candle UNIQUE (symbol, category, timeframe, ts)
);

CREATE TABLE IF NOT EXISTS market_snapshots (
    id                  SERIAL PRIMARY KEY,
    ts                  TIMESTAMPTZ NOT NULL,
    symbol              VARCHAR(32) NOT NULL,
    price               DOUBLE PRECISION,
    funding_rate        DOUBLE PRECISION,
    open_interest_value DOUBLE PRECISION,
    turnover_24h        DOUBLE PRECISION,
    spread_bps          DOUBLE PRECISION,
    data                JSONB
);
CREATE INDEX IF NOT EXISTS ix_market_snapshots_ts ON market_snapshots (ts);
CREATE INDEX IF NOT EXISTS ix_market_snapshots_symbol ON market_snapshots (symbol);

CREATE TABLE IF NOT EXISTS opportunities (
    id          SERIAL PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL,
    symbol      VARCHAR(32) NOT NULL,
    status      VARCHAR(16) NOT NULL,           -- SIGNAL | NO_TRADE
    direction   VARCHAR(8),
    score       DOUBLE PRECISION NOT NULL,
    timeframe   VARCHAR(4) NOT NULL,
    price       DOUBLE PRECISION,
    entry       DOUBLE PRECISION,
    stop        DOUBLE PRECISION,
    rr_net      DOUBLE PRECISION,
    payload     JSONB NOT NULL                   -- full scorecard, evidence, gates, plan
);
CREATE INDEX IF NOT EXISTS ix_opportunities_created_at ON opportunities (created_at);
CREATE INDEX IF NOT EXISTS ix_opp_symbol_created ON opportunities (symbol, created_at);

CREATE TABLE IF NOT EXISTS news_events (
    id            SERIAL PRIMARY KEY,
    uid           VARCHAR(64) UNIQUE NOT NULL,   -- sha256(url) prefix
    title         TEXT NOT NULL,
    url           TEXT NOT NULL,
    source        VARCHAR(64) NOT NULL,
    published_at  TIMESTAMPTZ,
    fetched_at    TIMESTAMPTZ NOT NULL,
    importance    VARCHAR(8) NOT NULL,
    confirmation  VARCHAR(64) NOT NULL,
    sentiment     DOUBLE PRECISION NOT NULL,
    payload       JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_news_events_published_at ON news_events (published_at);

CREATE TABLE IF NOT EXISTS paper_trades (
    id            INTEGER PRIMARY KEY,
    symbol        VARCHAR(32) NOT NULL,
    side          VARCHAR(8)  NOT NULL,
    status        VARCHAR(8)  NOT NULL,          -- open | closed
    leverage      DOUBLE PRECISION NOT NULL,
    entry_price   DOUBLE PRECISION NOT NULL,
    entry_time    VARCHAR(40) NOT NULL,
    realized_pnl  DOUBLE PRECISION NOT NULL DEFAULT 0,
    exit_reason   VARCHAR(64),
    closed_at     VARCHAR(40),
    payload       JSONB NOT NULL                 -- fills, fees, funding, TPs, notes
);
CREATE INDEX IF NOT EXISTS ix_paper_trades_symbol ON paper_trades (symbol);
CREATE INDEX IF NOT EXISTS ix_paper_trades_status ON paper_trades (status);

CREATE TABLE IF NOT EXISTS paper_account (
    id               INTEGER PRIMARY KEY,
    updated_at       TIMESTAMPTZ NOT NULL,
    balance          DOUBLE PRECISION NOT NULL,
    starting_equity  DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS backtest_runs (
    id          SERIAL PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL,
    kind        VARCHAR(16) NOT NULL,            -- single | walk_forward | holdout
    strategy    VARCHAR(64) NOT NULL,
    symbol      VARCHAR(32) NOT NULL,
    timeframe   VARCHAR(4)  NOT NULL,
    params      JSONB,
    result      JSONB
);

CREATE TABLE IF NOT EXISTS alerts (
    id          SERIAL PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL,
    type        VARCHAR(32) NOT NULL,
    symbol      VARCHAR(32),
    title       TEXT NOT NULL,
    sent        BOOLEAN NOT NULL,
    payload     JSONB
);
CREATE INDEX IF NOT EXISTS ix_alerts_created_at ON alerts (created_at);
