# Architecture

```
            Solana RPC (websocket logsSubscribe + getSignaturesForAddress polling)
                                   │ signatures
                                   ▼
┌──────────────────── TraderMonitor ────────────────────┐   Redis: leader lock + signature dedupe
│ getTransaction(confirmed) → parser (balance diffs)     │
│ → SwapEvent: BUY / SELL_PARTIAL / SELL_FULL / FAILED / │
│   TRANSFER_IN/OUT                                      │
└──────────────────────────┬────────────────────────────┘
                           ▼
┌──────────────────── CopyEngine ───────────────────────┐   PostgreSQL
│ 1. persist TraderEvent (unique sig+mint+kind)          │   traders, trader_events,
│ 2. BUY: size → market/contract/route data → RiskEngine │   positions, copy_orders
│    → CopyOrder (unique idempotency key) → Executor     │   (unique idempotency_key),
│ 3. SELL: trader sold fraction (pre/post balance)       │   kv (state, risk limits),
│    → reduce our position by the same fraction          │   audit_log
└───────┬───────────────────────────────┬───────────────┘
        ▼                               ▼
  Executor: PaperExecutor (default)   Notifier (Telegram) · EventBus → dashboard WebSocket
            LiveExecutor (gated)
        ▲
┌───────┴────────── PositionMonitor (every 15 s) ───────┐
│ mark-to-market, stop-loss / take-profit / trailing /   │
│ max-hold, retry failed exits, price-move alerts,       │
│ trader-inactivity alert, equity high-water mark        │
└────────────────────────────────────────────────────────┘
  Reconciler (5 min): orders vs positions, stale pending orders, wallet balances (live)
  Watchdog (30 s): restarts a dead monitor, alerts when polling stalls
  Daily report (Telegram) · /health for uptime monitors · nightly pg_dump backups
```

## Module map
| Path | Responsibility |
|---|---|
| `chain/rpc.py` | Documented Solana JSON-RPC calls with retry/backoff |
| `chain/ws.py` | `logsSubscribe` with automatic reconnection |
| `chain/parser.py` | Transaction → trader actions from validator balance data |
| `trader/monitor.py` | Real-time monitoring, persisted cursor, history backfill |
| `trader/analytics.py` | Win rate, drawdown, holding time, red flags, copyability, score |
| `market/*` | DexScreener + Jupiter clients, token contract checks |
| `risk/engine.py` | Pure risk functions: sizing, entry checks, halts, exit rules |
| `engine/copy_engine.py` | Orchestration, idempotent orders, P/L accounting |
| `engine/position_monitor.py` | Independent exit protection |
| `engine/reconcile.py` | Reconciliation |
| `execution/paper.py` | Real quotes, simulated fills, explicit cost model |
| `execution/live.py` | Jupiter swap signing; disabled unless fully authorised |
| `api/app.py`, `api/static/index.html` | REST + WebSocket API and the mobile dashboard |
| `coordination.py` | Redis leader lock (single active trader instance) |

## Accounting rules
* **Cost basis** = USD paid + entry network fee. Slippage is already inside the fill price, and is also
  tracked separately for reporting, never subtracted twice.
* **Realised P/L** on each sale = proceeds − exit network fee − the sold share of the cost basis.
  So every realised figure is net of entry fees, exit fees, network fees and slippage.
* **Unrealised P/L** is a mark to the current price. The dashboard also shows an estimate net of the exit network fee,
  and labels both as not profit until sold.

## Safety layers for real execution
1. `EXECUTION_MODE=live` **and** `LIVE_TRADING_ACK=<exact phrase>` **and** a keypair file → otherwise the live executor cannot even be constructed.
2. Runtime arming from the dashboard (re-typing the phrase). Arming is **cleared on every restart** and on emergency stop.
3. The guard is re-checked immediately before broadcasting each transaction.
4. Emergency stop blocks all new entries at execution time, not just at signal time.
5. Redis leader lock: a second instance can never trade at the same time.
