# Copy trading performance report (simulation)
_Generated 2026-11-06T00:01:47+00:00_

All P/L figures are net of entry fees, exit fees, network fees and slippage as recorded per fill.
Unrealised figures are marks to the current price and are **not** profits until the position is sold.

## Summary
| Metric | Value |
|---|---|
| capital_usd | 1000.0 |
| equity_usd | 991.87 |
| realized_pnl_usd | -8.1326 |
| unrealized_pnl_usd | 0 |
| unrealized_net_est_usd | 0.0 |
| total_fees_usd | 0.1103 |
| total_slippage_usd | 0.724 |
| total_costs_usd | 0.8342 |
| open_positions | 0 |
| closed_positions | 3 |
| closed_win_rate_pct | 33.3 |
| orders_filled | 7 |
| orders_failed | 2 |
| avg_execution_diff_pct | -2.058 |

## Signal handling
- Trader events recorded: 10
- copied: 4
- failed: 1
- ignored: 1
- skipped: 4
- Median detection latency: 0.8s

## Positions
| # | Token | Status | Trader entry | My entry (incl. costs) | Invested | Realised P/L | Fees | Slippage | Exit |
|---|---|---|---|---|---|---|---|---|---|
| 1 | ALPHA | closed | 0.0025 | 0.0025144 | 25.02 | +0.6871 | 0.0473 | 0.2581 | copy_sell |
| 2 | BETA | closed | 1.2 | 1.20691 | 25.02 | -8.5338 | 0.0315 | 0.2115 | stop_loss |
| 3 | ALPHA | closed | 0.0025 | 0.00261473 | 25.02 | -0.2858 | 0.0315 | 0.2543 | emergency_exit |

## Daily realised P/L
| Date | P/L |
|---|---|
| 2026-11-06 | -8.1326 |

Past results, simulated or real, do not guarantee future results.

## Scenario steps
1. trader buys ALPHA for 2 SOL
2. duplicate delivery of the same tx (websocket + poll)
3. ALPHA price tick -> 0.002514
4. ALPHA price tick -> 0.002480
5. ALPHA price tick -> 0.002584
6. ALPHA price tick -> 0.002527
7. ALPHA price tick -> 0.002600
8. trader sells 50% of ALPHA
9. trader buys BETA
10. trader buys THIN (insufficient liquidity)
11. delayed BETA signal (15 min old)
12. BETA moved +33% then trader adds (price-drift rejection)
13. BETA drops -33% from entry: stop-loss without trader exit
14. trader fails a transaction
15. trader closes ALPHA but our exit route fails
16. route recovers: exit retried by position monitor
17. trader buys ALPHA again
18. emergency stop with flatten
19. signal after emergency stop

## Notifications sent
```
TRADER BUY

Trader: Simulated trader
Token: ALPHA
Amount: 120,000.0000
Value: $300.00
Price: $0.0025
Tx: sig0…xxxx
```

```
COPY TRADE ALERT

Trader: Simulated trader
Action: BUY
Token: ALPHA
Original entry: $0.0025
My execution: $0.0025128141
Size: $25.00
Costs: $0.14
Status: Executed (paper)
Execution difference: +0.51%
```

```
TRADER SELL

Trader: Simulated trader
Token: ALPHA
Sold: 50.0% of position
Value: $180.00
Price: $0.003
Tx: sig0…xxxx
```

```
COPY POSITION REDUCED

Trader: Simulated trader
Action: SELL (copy_sell)
Token: ALPHA
Sold: 50.0%
Exit price: $0.0025866233
Trader exit: $0.003
My position: 4,974.5025 remaining
Net P/L (this sale): +$0.34
Position net P/L: +$0.34
Status: Completed (paper)

P/L is after entry fees, exit fees, network fees and slippage.
```

```
TRADER BUY

Trader: Simulated trader
Token: BETA
Amount: 250.0000
Value: $300.00
Price: $1.2000
Tx: sig0…xxxx
```

```
COPY TRADE ALERT

Trader: Simulated trader
Action: BUY
Token: BETA
Original entry: $1.2000
My execution: $1.2062
Size: $25.00
Costs: $0.14
Status: Executed (paper)
Execution difference: +0.51%
```

```
TRADER BUY

Trader: Simulated trader
Token: THIN
Amount: 3,000.0000
Value: $150.00
Price: $0.05
Tx: sig0…xxxx
```

```
COPY SKIPPED

Token: THIN
Reason: liquidity 9,000 USD < 50,000

Risk checks rejected this copy.
```

```
TRADER BUY

Trader: Simulated trader
Token: BETA
Amount: 125.0000
Value: $150.00
Price: $1.2000
Tx: sig0…xxxx
```

```
COPY SKIPPED

Token: BETA
Reason: signal too old (901s > 120s)

Risk checks rejected this copy.
```

```
TRADER BUY

Trader: Simulated trader
Token: BETA
Amount: 125.0000
Value: $150.00
Price: $1.2000
Tx: sig0…xxxx
```

```
COPY SKIPPED

Token: BETA
Reason: price already moved +33.3% since trader entry (> 10.0%)

Risk checks rejected this copy.
```

```
SIGNIFICANT PRICE MOVE

Token: BETA
Move: +32.7%
Price: $1.6000
Unrealised P/L (before exit costs): $8.15
```

```
RISK LIMIT REACHED

Token: BETA
Rule: stop_loss (-33.7%)
Entry (incl. costs): $1.2069
Current: $0.8

Closing copied position under the configured risk policy.
```

```
COPY TRADE CLOSED

Trader: Simulated trader
Action: SELL (stop_loss)
Token: BETA
Sold: 100.0%
Exit price: $0.7959471692
Trader exit: n/a
My position: Closed
Net P/L (this sale): -$8.53
Position net P/L: -$8.53
Status: Completed (paper)

P/L is after entry fees, exit fees, network fees and slippage.
```

```
TRADER SELL

Trader: Simulated trader
Token: ALPHA
Sold: 100.0% of position
Value: $225.00
Price: $0.00375
Tx: sig0…xxxx
```

```
TRANSACTION FAILED

Order: #5 SELL (copy_sell)
Token: BONK…XXXX
Error: no exit route / quote
Consecutive failures: 1
```

```
TRANSACTION FAILED

Order: #6 SELL (copy_sell)
Token: BONK…XXXX
Error: no exit route / quote
Consecutive failures: 2
```

```
COPY TRADE CLOSED

Trader: Simulated trader
Action: SELL (copy_sell)
Token: ALPHA
Sold: 100.0%
Exit price: $0.0025866233
Trader exit: n/a
My position: Closed
Net P/L (this sale): +$0.34
Position net P/L: +$0.69
Status: Completed (paper)

P/L is after entry fees, exit fees, network fees and slippage.
```

```
TRADER BUY

Trader: Simulated trader
Token: ALPHA
Amount: 120,000.0000
Value: $300.00
Price: $0.0025
Tx: sig0…xxxx
```

```
COPY TRADE ALERT

Trader: Simulated trader
Action: BUY
Token: ALPHA
Original entry: $0.0025
My execution: $0.0026130815
Size: $25.00
Costs: $0.14
Status: Executed (paper)
Execution difference: +4.52%
```

```
COPY TRADE CLOSED

Trader: Simulated trader
Action: SELL (emergency_exit)
Token: ALPHA
Sold: 100.0%
Exit price: $0.0025864998
Trader exit: n/a
My position: Closed
Net P/L (this sale): -$0.29
Position net P/L: -$0.29
Status: Completed (paper)

P/L is after entry fees, exit fees, network fees and slippage.
```

```
EMERGENCY STOP

Reason: simulation drill
Live trading: disarmed
Positions closed: 1
```

```
TRADER BUY

Trader: Simulated trader
Token: BETA
Amount: 250.0000
Value: $300.00
Price: $1.2000
Tx: sig0…xxxx
```

```
COPY SKIPPED

Token: BETA
Reason: emergency stop active; copying paused

Risk checks rejected this copy.
```

_Synthetic market data, deterministic seed. This validates system behaviour, not trading performance._
