# FOMO copy trader

A copy-trading system that monitors a selected FOMO trader's **public Solana wallet** and mirrors their trades,
with risk checks, through a dedicated wallet you control. It runs 24/7 in Docker with a mobile web dashboard and Telegram alerts.

> **Important:** FOMO publishes **no API**, and nothing executes trades *inside* your FOMO account.
> This system uses only documented, public interfaces: Solana RPC to watch the trader, and DexScreener plus Jupiter for market data
> and execution. Details: [docs/INVESTIGATION.md](docs/INVESTIGATION.md).
> It runs in **paper mode** by default. Live execution needs four separate opt-ins, described below.
> Losses are possible; nothing here guarantees profit.

## What it does
* **Trader evaluation**: win rate, average win and loss, profit factor, largest win and loss, max drawdown, trades per day,
  holding time, token history and open positions. Also red flags (small sample, outlier-driven profit, wash-like round trips,
  untradeable sniping, bag-holding) and an estimate of *copyable* returns after latency and costs.
* **Real-time detection**: buys, partial and full sells, failed transactions, transfers. Uses websocket push with polling fallback,
  a persisted cursor, and duplicate-proof processing.
* **Copy execution**: every BUY passes signal age, liquidity, 24 h volume, pool age, mint and freeze authority,
  Token-2022 extensions, holder concentration, price drift since the trader's entry, price impact for *your* size, round-trip
  cost and portfolio limits. SELLs are mirrored in proportion, using the trader's on-chain before/after balances.
* **Position management**: independent stop-loss, take-profit, trailing stop and max-hold rules. Failed exits are retried.
  You also get price-move and inactivity alerts, plus daily-loss, drawdown and failure-streak circuit breakers.
* **Accounting**: P/L is net of entry fees, exit fees, network fees and slippage. Unrealised values are clearly labelled.
* **Ops**: PostgreSQL, Redis leader lock, reconciliation, watchdog, `/health`, nightly backups, HTTPS via Caddy.

## Quick start (local, paper)
```bash
cd fomo-copytrader
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q                                            # 53 offline tests
python -m fomo_copytrader.cli simulate               # full scenario walkthrough + report
cp .env.example .env   # set APP_ENV=dev, SOLANA_RPC_URL, optionally TELEGRAM_*
uvicorn fomo_copytrader.main:app --port 8000         # open http://localhost:8000
python -m fomo_copytrader.cli analyze <TRADER_WALLET>  # read-only evaluation
```

## Deploy 24/7 (any VPS / cloud VM with Docker)
```bash
cd fomo-copytrader
cp .env.example .env          # fill DOMAIN, POSTGRES_PASSWORD, DASHBOARD_TOKEN, SOLANA_RPC_URL/WS, TELEGRAM_*
mkdir -p secrets && echo '[]' > secrets/wallet_keypair.json   # placeholder while in paper mode
docker compose up -d --build
```
Point your domain's DNS at the server. Caddy issues HTTPS automatically. Open `https://<DOMAIN>` on any device
and enter `DASHBOARD_TOKEN`. Point an uptime monitor (UptimeRobot, Better Stack, …) at `https://<DOMAIN>/health`.
Copy `./backups` off the server regularly.

**Telegram:** create a bot with @BotFather → `TELEGRAM_BOT_TOKEN`. Send it a message, then read your chat id from
`https://api.telegram.org/bot<TOKEN>/getUpdates` → `TELEGRAM_CHAT_ID`.

**Finding the trader's wallet:** open their FOMO profile and copy the Solana wallet address it shows, or the address
behind their trades on a block explorer. Paste it into the dashboard → **Analyse** → **Select trader**.

## Enabling live execution (only after paper results justify it)
1. Create a **new, dedicated** Solana wallet. Fund it only with what you allocate (USDC, plus a little SOL for fees).
   Never use your main wallet or seed phrase.
2. Save its keypair JSON as `secrets/wallet_keypair.json` (mounted as a Docker secret, never in `.env` or the DB).
3. In `.env`, set `EXECUTION_MODE=live`, `LIVE_TRADING_ACK=I_UNDERSTAND_REAL_FUNDS_ARE_AT_RISK`,
   `WALLET_KEYPAIR_PATH=/run/secrets/wallet_keypair`, then `docker compose up -d`.
4. On the dashboard, press **Arm live trading** and type the phrase. Arming resets on every restart and on emergency stop.

Start with small `fixed_position_usd` and `max_daily_loss_usd` values.

## Dashboard controls
Start/stop monitoring · Start copying · Pause (no new entries, exits still mirrored) · Stop copying (nothing mirrored;
risk exits stay active) · Emergency stop / Emergency stop + close all · Change trader · Edit risk limits ·
Close a position · Trading history · Performance report.

## Docs
[Investigation](docs/INVESTIGATION.md) · [Architecture](docs/ARCHITECTURE.md) · [Testing](docs/TESTING.md) ·
[Simulation report](docs/SIMULATION_REPORT.md)
