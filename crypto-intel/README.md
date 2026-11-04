# CryptoIntel — Crypto Market Intelligence & Trading-Analysis System

A research platform that monitors Bybit public market data, combines technical,
structural, derivatives, news/macro, sentiment and on-chain evidence into a
**transparent 0–100 score**. It then produces either a fully specified *hypothetical*
trade plan or **`NO TRADE — INSUFFICIENT CONFIRMATION`**. It paper-trades those plans
against live prices and validates strategies with walk-forward backtests.

> **Research and simulation only.** The system never places real orders and has
> no order-placement code. Nothing here is financial advice. No outcome is certain,
> and simulated or historical performance does not guarantee future results.

## What's inside

| Area | Implementation |
|---|---|
| Bybit integration | REST v5 public client (klines, tickers, instruments, OI, funding, L/S ratio, orderbook, trades) with retries and rate limiting; public WebSocket (tickers, trades → volume delta, liquidations) with heartbeat and reconnect |
| Universe filter | Turnover, open interest, spread, listing age, abnormal 24h moves, stablecoin pairs, churn flag. Every rejection is recorded with a reason |
| Technical analysis | EMA 9/20/50/100/200, SMA, MACD, ADX/DI, RSI, StochRSI, ROC, CCI, Bollinger, ATR, historical vol, VWAP, OBV, volume profile (POC/VA), RVOL, trade-based volume delta. All causal |
| Price action | Confirmed swings, HH/HL/LH/LL, BOS/CHoCH, S/R clustering, volume-confirmed breakouts, fair value gaps, equal-high/low liquidity pools, candlestick patterns, RSI divergence |
| Multi-timeframe | 1m, 5m, 15m, 1h, 4h, 1d, 1w (primary 1h, trigger 15m, context 4h/1d by default) |
| Derivatives | Funding (scaled to the symbol's interval, percentile), OI-vs-price regime, account L/S crowding, orderbook depth/imbalance, liquidations |
| News & macro | RSS from CoinDesk, Cointelegraph, CNBC, Federal Reserve, ECB, BoE. Each item gets event type, affected assets, bullish and bearish cases, impact duration, and a fact/report/rumour label. Economic calendar with mandatory source URLs |
| Sentiment & on-chain | Fear & Greed (alternative.me), sentiment-vs-price divergences, stablecoin supply (DefiLlama). Paid metrics are explicitly marked *unavailable* |
| Scoring | Technical 25 · Structure 20 · Volume/Liquidity 15 · Derivatives 15 · News/Macro 15 · Sentiment/On-chain 10. Every point is explained, and missing data scores 0 |
| Risk | Leverage simulator for 1x–20x: exposure, margin, liquidation estimate, fees, funding, R:R, drawdown, in fixed-risk and fixed-margin modes |
| Paper trading | Live-price fills with slippage, taker/maker fees, funding settlement, partial TPs, break-even stop, pessimistic intrabar handling, estimated liquidation, full history in the DB |
| Backtesting | Event-driven engine (next-bar fills, costs, funding), 3 strategies, walk-forward optimisation, untouched holdout, buy-and-hold benchmark, honest verdicts |
| ML | Purged walk-forward classifier compared against naive baselines. It stays out of the score unless it beats them out-of-sample |
| Alerts | Telegram messages for breakouts, unusual volume/volatility, high-impact news, sentiment shifts, new setups, paper-trade events and drawdown. Each one includes evidence and risks, with cooldowns |
| Delivery | FastAPI REST API, a React + TradingView Lightweight Charts dashboard (no build step), PostgreSQL/SQLite, Docker |

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/SCORING.md](docs/SCORING.md) and
[docs/ROADMAP.md](docs/ROADMAP.md).

## Quick start

```bash
cd crypto-intel
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env                    # optional: Telegram token, PostgreSQL URL, thresholds
cp config/economic_calendar.example.json config/economic_calendar.json   # then fill from official sources
python -m pytest                        # run the test suite
python -m cryptointel.cli serve         # http://127.0.0.1:8000  (API docs at /docs)
```

With Docker and PostgreSQL:

```bash
export POSTGRES_PASSWORD=choose-a-strong-password
cp .env.example .env
docker compose up --build               # dashboard at http://127.0.0.1:8000
```

### CLI

```bash
python -m cryptointel.cli scan                                   # one scan, print scores and gate failures
python -m cryptointel.cli backtest BTCUSDT --tf 1h --strategy trend_pullback --mode walk_forward --days 365
python -m cryptointel.cli backtest ETHUSDT --mode holdout --strategy donchian_breakout
python -m cryptointel.cli ml SOLUSDT --tf 1h --horizon 12
python -m cryptointel.cli leverage --entry 100 --stop 96 --targets 108 112
```

### Main API endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/overview` | BTC/ETH, market direction, universe index, volatility, Fear & Greed, events, paper equity |
| GET | `/api/opportunities` | Current SIGNAL / NO_TRADE results with full scorecards |
| GET | `/api/analysis/{symbol}` | All timeframes, indicators, levels, derivatives, news |
| GET | `/api/candles/{symbol}?tf=1h` | Closed candles with EMAs/Bollinger/RSI for charts |
| POST | `/api/leverage/simulate` | Leverage comparison |
| GET | `/api/paper/trades`, `/api/paper/performance` | Simulated trade history & stats |
| POST | `/api/backtest` | `single` / `walk_forward` / `holdout` run on downloaded history |
| GET | `/api/news`, `/api/alerts` | Classified news and alert log |

## System rules and where the code enforces them

| Rule | Enforcement |
|---|---|
| Never claim certainty / guarantee profit | Disclaimers in API, dashboard, alerts and reports. Language is "hypothetical", "scenario", "observation" |
| Never fabricate data or news | Only real feed/API values are used. Failed fetches return `None` and are scored 0. Paid metrics are shown as *unavailable*. Calendar entries without a source URL are rejected. Synthetic data exists only inside `tests/` |
| Identify data age | `Stamped` values, candle staleness checks, and ages shown for prices, news, F&G and on-chain data |
| Distinguish facts, estimates and hypotheses | News `confirmation` field. Liquidation is labelled an *estimate*. Divergences are worded as observations |
| No signal when essential data is missing | Gate 1 in `analysis/opportunity.py` (primary/trigger/higher TF, fresh price, ATR, price-vs-candle consistency) |
| Capital preservation | Fixed 1% risk sizing, stop distance limits, a liquidation-before-stop rejection, a max-open-trades cap and drawdown alerts |
| Report failures honestly | Backtest verdicts (`FAILED`, `Underperformed buy-and-hold`, `likely overfit`), with parameter-combination counts disclosed |
| Avoid excessive signals | Eight hard gates, a minimum score of 70, alert cooldowns and one open paper trade per symbol |
| Explain every conclusion | Each score component carries an evidence string, and every gate failure is listed |

## Known limitations

- **Verification status:** the network sandbox this was built in blocks `api.bybit.com`. All code paths were tested against a mocked Bybit API that follows the v5 response format, plus synthetic price series. Run `python -m cryptointel.cli scan` on your machine to confirm live connectivity before relying on the dashboard.
- Liquidation prices are estimates: flat MMR, isolated margin. Bybit's real figure depends on risk-limit tier, margin mode, mark price and account settings.
- Reuters, Bloomberg and FT need licensed APIs and are not scraped. News classification uses keywords, so read the source.
- Survivorship bias: Bybit lists only current instruments, so backtests on today's universe look better than reality.
- Liquidation and volume-delta data come only from the live WebSocket. They are flagged as incomplete until the full window has been observed, and they are not available historically.
- Social-media sentiment, exchange flows, whale tracking and wallet concentration need paid or authenticated APIs. They are not implemented beyond an explicit *unavailable* status.

## Security

- No credentials in code. Settings come from environment variables or `.env`, which is git-ignored. Log output redacts tokens, and `/api/config` masks secrets.
- No API key is needed. If you add one, make it **read-only**, with no trading and no withdrawal permissions.
- The Docker setup binds the dashboard to `127.0.0.1` by default. Put authentication in front of it before exposing it.
