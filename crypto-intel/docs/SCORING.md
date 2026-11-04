# Scoring & Decision Methodology

Source: `cryptointel/analysis/scoring.py` and `cryptointel/analysis/opportunity.py`.

The engine scores **both** a long and a short scenario for every instrument. The
higher-scoring scenario is evaluated against the hard gates. If any gate fails, the
result is `NO TRADE — INSUFFICIENT CONFIRMATION` and every failed gate is listed.
The rejected plan is kept only as diagnostic data and is never shown as levels to act on.

## Score components (max 100)

### Technical conditions — 25
| Component | Max | Logic |
|---|---|---|
| Primary (1h) trend | 5 | timeframe bias (EMA stack, EMA200, MACD, RSI zone, ROC, VWAP, OBV, structure) scaled: full points at bias ≥ 0.7 in the scenario direction |
| 4h trend alignment | 2.5 | same, on 4h |
| 1d trend alignment | 2.5 | same, on 1d |
| Momentum | 8 | RSI zone (long: 50–70 = 3, 70–75 = 1, ≥ 75 = 0), MACD histogram sign 2, StochRSI cross not at extreme 1.5, ROC sign 1.5 |
| Volatility conditions | 4 | regime normal = 2, low = 1, high = 0; plus 2 if not stretched beyond Bollinger band |
| Volume confirmation | 3 | OBV slope aligned 1.5, price on correct side of VWAP 1.5 |

### Market structure — 20
| Component | Max | Logic |
|---|---|---|
| 1h structure | 6 | HH+HL (long) / LH+LL (short) |
| 4h structure | 4 | aligned 4, range 1 |
| Room to opposing level | 4 | ≥ 2 ATR = 4, ≥ 1 ATR = 2; no level (price discovery) = 3 |
| Confluence | 3 | 1 each: BOS, CHoCH, volume-confirmed range break, RSI divergence, candlestick pattern, unfilled FVG behind price |
| 15m trigger alignment | 3 | 15m bias in direction |

### Volume & liquidity — 15
24h turnover 4 · spread 3 · depth within ±0.5% (thinner side) 4 · 1h RVOL on a candle in the scenario's direction 4 (RVOL < 0.8 → 1).

### Derivatives — 15
| Component | Max | Logic |
|---|---|---|
| Funding positioning | 5 | crowded on the scenario's side = 0, neutral = 4, crowded on the opposite side = 5 (contrarian) |
| OI/price regime | 5 | long: new longs 5, short covering 2, neutral 2, long liquidation 1, new shorts 0 (mirrored for shorts) |
| Account L/S ratio | 2 | penalises retail crowding on the scenario's side |
| Order flow | 3 | orderbook imbalance 1.5 + aggressor delta (WebSocket) 1.5 |

### News & macro — 15
No high-impact scheduled event in 24h = 6 (only if a calendar is loaded) · confirmed news
sentiment 0–5 (neutral = 2.5) · shock events (hack/insolvency) 4.

### Sentiment & on-chain — 10
Fear & Greed, contrarian-aware, 4 · stablecoin supply 30d trend 3 · sentiment/price divergence 3.

## Missing data

A component whose data is unavailable, stale or failed to fetch is scored **0** and listed in
`missing_data` as `[DATA MISSING → 0]`. With news, calendar and sentiment all unavailable,
the maximum possible score is 75 (see the end-to-end test).

## Hard gates

1. Essential data: primary, trigger and ≥ 1 higher timeframe present and fresh. Current
   price must be < 5 minutes old, ATR available, and live price within 3 ATR of the last closed candle.
2. Score ≥ `MIN_SCORE` (70).
3. Technical ≥ 12 and structure ≥ 10 (multiple independent confirmations).
4. No higher timeframe has bias ≤ −0.35 against the scenario.
5. Not overextended: RSI < 78 for longs, > 22 for shorts.
6. No high-impact macro event within 24h. No hack/insolvency news on the asset (longs).
7. Stop within 0.8–3.5 ATR. Net R:R (50% at TP1, 50% at TP2, after fees, slippage and ~1 day of funding) ≥ `MIN_RR` (2.0).
8. Estimated liquidation at `PAPER_LEVERAGE` lies beyond the stop.

## Trade-plan construction

- **Entry zone:** current price to 0.3 ATR in the favourable direction.
- **Stop:** beyond the nearest confirmed swing that is at least 0.5 ATR away, plus a 0.25 ATR
  buffer. If no swing exists, 1.5 ATR, labelled as a volatility stop. Minimum 0.8 ATR.
- **Targets:** just in front of the next opposing S/R levels (1h and 4h). Without levels,
  2R and 3R projections, flagged as price discovery.
- **Invalidation:** structural close beyond the stop level, a higher-TF EMA50 break,
  funding/OI extremes, and unscheduled high-impact news.
