# System Architecture

CryptoIntel is a research and simulation platform. **It never places real orders.**
All Bybit access uses public market-data endpoints; no API key is required, and if
one is ever configured it must be a *read-only* key with no trade or withdrawal
permissions.

## High-level data flow

```
                ┌──────────────────────────── External sources ────────────────────────────┐
                │ Bybit REST v5 (public)   Bybit WebSocket v5 (public)   RSS: CoinDesk,     │
                │ klines, tickers, OI,     tickers, orderbook.50,        Cointelegraph,     │
                │ funding, L/S ratio,      publicTrade, allLiquidation   CNBC, Fed, ECB,    │
                │ orderbook, instruments                                 BoE                │
                │ alternative.me Fear&Greed   DefiLlama stablecoins   economic_calendar.json│
                └───────┬──────────────────────────┬───────────────────────────┬───────────┘
                        │                          │                           │
              cryptointel/data            cryptointel/data/bybit_ws     cryptointel/analysis/news
              bybit_client.py             (LiquidationTracker,          macro.py, sentiment.py,
              (retry, rate limit,          TradeFlowTracker)            onchain.py
               freshness stamps)                   │                           │
                        │                          │                           │
                        ▼                          ▼                           ▼
              ┌────────────────────────────────────────────────────────────────────────┐
              │ universe.py — liquidity / reliability filter (turnover, OI, spread,     │
              │ listing age, extreme moves, stablecoin pairs). Every exclusion explained│
              └───────────────────────────────┬────────────────────────────────────────┘
                                              ▼
              ┌────────────────────────────────────────────────────────────────────────┐
              │ indicators/ta.py + indicators/price_action.py  (pure, causal functions) │
              │ analysis/timeframe.py — per-timeframe report (1m … 1w)                  │
              │ analysis/derivatives.py — funding, OI/price regime, L/S, book imbalance │
              │ analysis/market.py — breadth, liquidity-weighted index, volatility      │
              └───────────────────────────────┬────────────────────────────────────────┘
                                              ▼
              ┌────────────────────────────────────────────────────────────────────────┐
              │ analysis/scoring.py — transparent 0–100 score per direction             │
              │   Technical 25 · Structure 20 · Volume/Liquidity 15 · Derivatives 15 ·  │
              │   News/Macro 15 · Sentiment/On-chain 10  (missing data = 0 points)      │
              │ analysis/opportunity.py — hard gates, trade plan or                     │
              │   "NO TRADE — INSUFFICIENT CONFIRMATION"                                 │
              └──────────────┬───────────────────────┬──────────────────────┬──────────┘
                             ▼                       ▼                      ▼
                  risk/leverage.py         paper/engine.py          alerts/ (rules +
                  educational leverage     simulated fills, fees,   Telegram, cooldowns)
                  & liquidation sim        funding, SL/TP, history
                             │                       │                      │
                             └───────────┬───────────┴──────────────────────┘
                                         ▼
                     db/ (SQLAlchemy; PostgreSQL in prod, SQLite for dev)
                                         ▼
                     api/main.py (FastAPI)  ──►  web/ dashboard (React + Lightweight Charts)

     Offline research path:  backtest/ (event-driven engine, walk-forward, OOS holdout,
                             benchmark) and ml/ (purged walk-forward classifiers vs. baselines)
```

## Module responsibilities

| Package | Responsibility |
|---|---|
| `cryptointel/config.py` | All settings from environment variables (`.env`). No secrets in code. |
| `data/bybit_client.py` | Synchronous Bybit v5 REST client: retries with backoff, client-side rate limiting, response validation, conversion to DataFrames, open-candle detection. |
| `data/bybit_ws.py` | Async public WebSocket client with heartbeat and reconnect; maintains rolling liquidation and trade-flow (volume delta) state. |
| `data/freshness.py` | `Stamped` values carrying source and timestamp; staleness checks used by the scoring gates. |
| `universe.py` | Selects analysable instruments and records *why* each other instrument was rejected. |
| `indicators/ta.py` | EMA/SMA/MACD/ADX, RSI/StochRSI/ROC/CCI, Bollinger/ATR/historical vol, VWAP/OBV/volume profile/RVOL/volume delta. |
| `indicators/price_action.py` | Confirmed swing points, market structure (HH/HL/LH/LL, BOS/CHoCH), S/R clustering, breakouts, FVGs, liquidity pools, candlestick patterns, RSI divergence. |
| `analysis/timeframe.py` | Combines indicators into an explainable per-timeframe report with a bias in [-1, 1]. |
| `analysis/derivatives.py` | Funding percentile, OI-vs-price regime, positioning crowding, orderbook imbalance/depth/spread, liquidations. |
| `analysis/news.py` | RSS ingestion, event classification, asset mapping, bullish/bearish implications, impact duration, fact vs. rumour labelling. |
| `analysis/macro.py` | Economic calendar (user-maintained, sourced), event-risk windows. |
| `analysis/sentiment.py` | Fear & Greed, sentiment/price divergence detection. |
| `analysis/onchain.py` | Stablecoin supply (DefiLlama). Paid-data providers are explicit "unavailable" stubs. |
| `analysis/scoring.py` | Category scoring with evidence lines and data-availability flags. |
| `analysis/opportunity.py` | Hard gates + trade plan (entry zone, stop, TPs, net R:R after costs, invalidation). |
| `risk/leverage.py` | Position exposure, liquidation estimate, fees, funding, R:R, drawdown at 1–20x. |
| `paper/engine.py` | Simulated broker driven by live prices; pessimistic intrabar fills. |
| `backtest/` | Engine, strategies, metrics, walk-forward & holdout validation, benchmark. |
| `ml/model.py` | Feature set, purged walk-forward evaluation, comparison with naive baselines. |
| `alerts/` | Alert rules, de-duplication/cooldown, Telegram delivery. |
| `db/` | ORM models and repository; `db/schema.sql` for PostgreSQL. |
| `services/monitor.py` | Orchestrates scans, persistence, paper trading and alerts. |
| `api/main.py` | REST API + static dashboard. |

## Design principles enforced in code

1. **Causality.** Indicators use only past data; swing points are only usable after
   their confirmation bars; backtests fill at the *next* bar's open; open (unfinished)
   candles are dropped before analysis.
2. **Missing ≠ positive.** Every score component has an `available` flag; unavailable
   components contribute 0 points and are listed in the explanation.
3. **Age is always shown.** Every external datum is stamped with its source time and
   the dashboard shows its age; stale essentials block signals.
4. **Multiple confirmations.** A signal requires minimum sub-scores in *both*
   technical and structure categories, higher-timeframe agreement, a valid structural
   stop and net R:R ≥ threshold after fees, slippage and estimated funding.
5. **Capital preservation.** Fixed-fractional risk sizing; leverage only changes margin
   and liquidation distance; plans whose liquidation price is closer than the stop are
   rejected.
6. **Honest evaluation.** Backtests include fees, slippage and funding, and always print
   a buy-and-hold benchmark, in-sample vs. out-of-sample degradation and the number of
   parameter combinations tried.
