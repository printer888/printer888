"""Performance statistics. All figures are historical/simulated, not forecasts."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


def _safe(x: float | None) -> float | None:
    if x is None:
        return None
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def max_drawdown(equity: pd.Series) -> float:
    if equity.empty:
        return 0.0
    dd = equity / equity.cummax() - 1
    return float(dd.min() * 100)


def performance(equity: pd.Series, trades: list[dict], periods_per_year: float) -> dict:
    out: dict = {"n_trades": len(trades)}
    if equity.empty:
        return out
    rets = equity.pct_change().dropna()
    start, end = float(equity.iloc[0]), float(equity.iloc[-1])
    out["start_equity"] = start
    out["end_equity"] = end
    out["total_return_pct"] = (end / start - 1) * 100
    days = (equity.index[-1] - equity.index[0]).total_seconds() / 86400 if len(equity) > 1 else 0
    out["period_days"] = days
    out["cagr_pct"] = _safe(((end / start) ** (365 / days) - 1) * 100) if days >= 30 and end > 0 else None
    out["max_drawdown_pct"] = max_drawdown(equity)
    sd = rets.std(ddof=1)
    out["sharpe"] = _safe(rets.mean() / sd * np.sqrt(periods_per_year)) if sd and sd > 0 else None
    downside = np.sqrt((np.minimum(rets, 0) ** 2).mean())
    out["sortino"] = _safe(rets.mean() / downside * np.sqrt(periods_per_year)) if downside > 0 else None
    out["calmar"] = _safe(out["cagr_pct"] / abs(out["max_drawdown_pct"])) if out["cagr_pct"] is not None and out["max_drawdown_pct"] < 0 else None
    if trades:
        pnl = np.array([t["pnl"] for t in trades])
        wins, losses = pnl[pnl > 0], pnl[pnl <= 0]
        out["win_rate_pct"] = len(wins) / len(pnl) * 100
        out["avg_win"] = float(wins.mean()) if len(wins) else 0.0
        out["avg_loss"] = float(losses.mean()) if len(losses) else 0.0
        out["profit_factor"] = _safe(wins.sum() / abs(losses.sum())) if losses.sum() < 0 else None
        out["expectancy"] = float(pnl.mean())
        rm = [t["r_multiple"] for t in trades if t.get("r_multiple") is not None]
        out["expectancy_r"] = float(np.mean(rm)) if rm else None
        out["total_fees"] = float(sum(t.get("fees", 0) for t in trades))
        out["total_funding"] = float(sum(t.get("funding", 0) for t in trades))
        out["avg_bars_held"] = float(np.mean([t.get("bars_held", 0) for t in trades]))
        out["largest_loss"] = float(pnl.min())
        streak = cur = 0
        for p in pnl:
            cur = cur + 1 if p <= 0 else 0
            streak = max(streak, cur)
        out["max_consecutive_losses"] = streak
    return {k: (_safe(v) if isinstance(v, float) else v) for k, v in out.items()}


def buy_and_hold(df: pd.DataFrame, initial_equity: float, fee: float, slippage_bps: float) -> pd.Series:
    """Spot buy-and-hold benchmark with entry/exit costs applied."""
    if df.empty:
        return pd.Series(dtype=float)
    entry = df["open"].iloc[0] * (1 + slippage_bps / 1e4)
    qty = initial_equity * (1 - fee) / entry
    eq = qty * df["close"]
    eq.iloc[-1] = eq.iloc[-1] * (1 - fee) * (1 - slippage_bps / 1e4)
    return eq.rename("benchmark_equity")
