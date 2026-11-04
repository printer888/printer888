"""Market-wide overview: breadth, liquidity-weighted index and volatility regime.

Bybit offers no tradable "crypto index", so a transparent, liquidity-weighted
index of the analysed universe is computed instead.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..data.bybit_client import parse_ticker


def universe_index(tickers: list[dict], symbols: list[str]) -> dict:
    rows = [parse_ticker(t) for t in tickers if t.get("symbol") in set(symbols)]
    rows = [r for r in rows if np.isfinite(r["turnover_24h"]) and np.isfinite(r["change_24h_pct"])]
    if not rows:
        return {"available": False}
    w = np.array([r["turnover_24h"] for r in rows])
    ch = np.array([r["change_24h_pct"] for r in rows])
    w = w / w.sum()
    up = int((ch > 0).sum())
    return {
        "available": True,
        "liquidity_weighted_change_24h_pct": float((w * ch).sum()),
        "equal_weighted_change_24h_pct": float(ch.mean()),
        "advancers": up,
        "decliners": int((ch < 0).sum()),
        "breadth_pct": up / len(rows) * 100,
        "total_turnover_24h_usd": float(sum(r["turnover_24h"] for r in rows)),
        "n": len(rows),
        "method": "24h % change of universe members weighted by 24h turnover",
    }


def market_direction(btc_daily: pd.DataFrame | None, index: dict) -> dict:
    """Classify overall market direction from BTC daily trend and breadth."""
    ev = []
    score = 0
    if btc_daily is not None and len(btc_daily) >= 60:
        c = btc_daily["close"]
        e50 = c.ewm(span=50, adjust=False).mean().iloc[-1]
        e200 = c.ewm(span=200, adjust=False).mean().iloc[-1] if len(c) >= 200 else None
        last = c.iloc[-1]
        if last > e50:
            score += 1
            ev.append("BTC above daily EMA50")
        else:
            score -= 1
            ev.append("BTC below daily EMA50")
        if e200 is not None:
            score += 1 if last > e200 else -1
            ev.append(f"BTC {'above' if last > e200 else 'below'} daily EMA200")
    if index.get("available"):
        b = index["breadth_pct"]
        if b >= 65:
            score += 1
        elif b <= 35:
            score -= 1
        ev.append(f"breadth {b:.0f}% of universe up 24h")
    label = "risk-on / uptrend" if score >= 2 else "risk-off / downtrend" if score <= -2 else "mixed / range"
    return {"label": label, "score": score, "evidence": ev}


def realised_volatility(daily: pd.DataFrame | None, n: int = 30) -> dict:
    if daily is None or len(daily) < n + 1:
        return {"available": False}
    lr = np.log(daily["close"] / daily["close"].shift(1)).dropna()
    cur = float(lr.tail(n).std() * np.sqrt(365) * 100)
    hist = lr.rolling(n).std().dropna() * np.sqrt(365) * 100
    pct = float((hist < cur).mean() * 100) if len(hist) > 30 else None
    return {"available": True, "annualised_pct": cur, "percentile_vs_history": pct, "window_days": n}
