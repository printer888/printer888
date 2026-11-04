# Implementation Roadmap

Status legend: ✅ implemented in this repository · 🟡 implemented with documented limitation · ⏳ future work

## Phase 1 — Foundations
- ✅ Configuration via environment, `.env.example`, logging setup
- ✅ Bybit v5 REST client (public endpoints, retries, rate limit, validation)
- ✅ Bybit v5 public WebSocket client (tickers, orderbook, trades, liquidations) with reconnect
- ✅ Database layer (SQLAlchemy; PostgreSQL + SQLite fallback), `db/schema.sql`

## Phase 2 — Market analysis
- ✅ Universe filter with recorded exclusion reasons
- ✅ Indicator library (trend, momentum, volatility, volume)
- ✅ Price-action library (structure, S/R, FVG, liquidity zones, patterns, divergences)
- ✅ Multi-timeframe analysis (1m, 5m, 15m, 1h, 4h, 1d, 1w)
- ✅ Derivatives analysis (funding, OI regime, L/S, orderbook, liquidations)
- 🟡 Volume delta — only from live public trades (WebSocket); never inferred from candles
- ✅ Market overview: breadth, liquidity-weighted index, volatility regime

## Phase 3 — Information engines
- ✅ RSS news engine (CoinDesk, Cointelegraph, CNBC, Federal Reserve, ECB, BoE)
- 🟡 Reuters / Bloomberg / FT — require licensed APIs; provider interface only, no scraping
- ✅ Economic calendar (user-maintained JSON with mandatory source URL)
- ✅ Fear & Greed index (alternative.me)
- 🟡 On-chain — stablecoin supply via DefiLlama; exchange flows/whales/wallet
  concentration require paid providers (Glassnode, CryptoQuant, Whale Alert) and are
  reported as *unavailable* until a key is configured
- ⏳ Social-media sentiment (requires X/Reddit API access)

## Phase 4 — Decision layer
- ✅ Transparent 0–100 scoring (6 categories, evidence per line)
- ✅ Opportunity builder with hard gates and NO-TRADE output
- ✅ Leverage & liquidation simulator (1x–20x)

## Phase 5 — Simulation & validation
- ✅ Paper-trading engine (fees, slippage, funding, SL/TP, liquidation, history)
- ✅ Backtesting engine + 3 strategies + buy-and-hold benchmark
- ✅ Walk-forward optimisation and untouched out-of-sample holdout
- ✅ ML diagnostic (purged walk-forward, compared to naive baselines). Not used in the
  score unless it beats baselines out-of-sample (`USE_ML_IN_SCORE`, off by default)
- 🟡 Survivorship bias — Bybit only lists *current* instruments; backtests on today's
  universe are biased. Documented in every backtest report.

## Phase 6 — Delivery
- ✅ FastAPI REST API
- ✅ Dashboard (React + TradingView Lightweight Charts, no build step)
- ✅ Telegram alerts with evidence and risk text, cooldowns
- ✅ Test suite (pytest), Dockerfile + docker-compose (PostgreSQL)

## Next steps (⏳)
1. Persist WebSocket-derived liquidation/trade-flow history for backtesting those features.
2. Maintenance-margin tiers fetched from `/v5/market/risk-limit` per symbol (currently a
   configurable flat MMR with tier-1 default).
3. Historical funding series in backtests for all symbols (supported by the engine;
   wire-up per run via `scripts/run_backtest.py --funding`).
4. Licensed news APIs; LLM-assisted event summarisation with source citation.
5. Portfolio-level risk (correlation caps across simultaneous paper trades).
