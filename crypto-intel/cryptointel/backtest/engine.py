"""Event-driven bar backtester.

Bias controls:
  • Look-ahead: the strategy sees rows 0..i only (it receives a truncated view);
    orders fill at the NEXT bar's open, with slippage.
  • Intrabar ambiguity: if stop and target are both inside one bar, the stop is
    assumed to fill first (pessimistic). Gaps through the stop fill at the open.
  • Costs: taker fee + slippage on entries and stop exits; maker fee on targets;
    funding charged at each funding timestamp crossed while the position is open.
  • Survivorship: Bybit only lists *currently trading* instruments, so backtests on
    today's universe overstate results. This is stated in every report.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import numpy as np
import pandas as pd

from ..data.freshness import TIMEFRAME_SECONDS
from ..indicators.ta import PERIODS_PER_YEAR
from .metrics import buy_and_hold, performance

BIAS_NOTES = [
    "Survivorship bias: only instruments listed today are available from Bybit; delisted coins are absent.",
    "Simulated fills: next-bar-open entries with slippage; stop-first assumption when a bar touches both levels.",
    "Past performance — simulated or real — does not guarantee future results.",
]


@dataclass
class Order:
    side: str  # "long" | "short"
    stop: float
    target: float
    reason: str = ""


class Strategy(Protocol):
    name: str
    params: dict

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame: ...

    def signal(self, df: pd.DataFrame, i: int) -> Order | None: ...


@dataclass
class BacktestConfig:
    timeframe: str = "1h"
    initial_equity: float = 10_000.0
    risk_per_trade: float = 0.01
    max_leverage: float = 3.0
    taker_fee: float = 0.00055
    maker_fee: float = 0.0002
    slippage_bps: float = 3.0
    funding_rate_per_interval: float = 0.0001  # assumption when no series supplied
    funding_interval_hours: int = 8
    funding_series: pd.Series | None = None
    max_bars_in_trade: int | None = 96


@dataclass
class BacktestResult:
    strategy: str
    params: dict
    trades: list[dict]
    equity: pd.Series
    metrics: dict
    benchmark_metrics: dict
    notes: list[str] = field(default_factory=lambda: list(BIAS_NOTES))

    def summary(self) -> dict:
        return {"strategy": self.strategy, "params": self.params, "metrics": self.metrics,
                "benchmark_buy_and_hold": self.benchmark_metrics, "notes": self.notes,
                "trades": self.trades[-200:]}


def _funding_times_between(t0: pd.Timestamp, t1: pd.Timestamp, hours: int) -> list[pd.Timestamp]:
    """Funding timestamps in (t0, t1]."""
    step = pd.Timedelta(hours=hours)
    first = t0.floor(f"{hours}h") + step
    out = []
    t = first
    while t <= t1:
        out.append(t)
        t += step
    return out


def run_backtest(df: pd.DataFrame, strategy: Strategy, cfg: BacktestConfig, trade_start: int = 0) -> BacktestResult:
    data = strategy.prepare(df)
    n = len(data)
    o, h, l, c = (data[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close"))
    idx = data.index
    tf_delta = pd.Timedelta(seconds=TIMEFRAME_SECONDS[cfg.timeframe])
    slip = cfg.slippage_bps / 1e4
    equity = cfg.initial_equity
    eq_curve = np.full(n, np.nan)
    trades: list[dict] = []
    pos: dict | None = None
    pending: Order | None = None

    def funding_rate_at(ts: pd.Timestamp) -> float:
        fs = cfg.funding_series
        if fs is not None and len(fs):
            prior = fs[fs.index <= ts]
            if len(prior):
                return float(prior.iloc[-1])
        return cfg.funding_rate_per_interval

    def close_pos(i: int, price: float, fee_rate: float, reason: str) -> None:
        nonlocal equity, pos
        d = pos["d"]
        gross = d * (price - pos["entry"]) * pos["qty"]
        exit_fee = price * pos["qty"] * fee_rate
        pnl = gross - pos["entry_fee"] - exit_fee - pos["funding"]
        equity += gross - exit_fee - pos["funding"]  # entry fee already deducted at open
        trades.append({
            "side": "long" if d > 0 else "short", "entry_time": pos["time"].isoformat(),
            "exit_time": idx[i].isoformat(), "entry": pos["entry"], "exit": price, "stop": pos["stop"],
            "target": pos["target"], "qty": pos["qty"], "pnl": pnl, "fees": pos["entry_fee"] + exit_fee,
            "funding": pos["funding"], "r_multiple": pnl / pos["risk_usd"] if pos["risk_usd"] else None,
            "bars_held": i - pos["i"] + 1, "exit_reason": reason, "reason": pos["reason"],
        })
        pos = None

    for i in range(n):
        # 1) fill pending order at this bar's open
        if pending is not None and pos is None:
            d = 1 if pending.side == "long" else -1
            entry = o[i] * (1 + d * slip)
            valid = d * (entry - pending.stop) > 0 and d * (pending.target - entry) > 0
            if valid:
                stop_fill = pending.stop * (1 - d * slip)
                per_unit = d * (entry - stop_fill) + (entry + stop_fill) * cfg.taker_fee
                qty = equity * cfg.risk_per_trade / per_unit
                qty = min(qty, equity * cfg.max_leverage / entry)
                if qty > 0:
                    fee = entry * qty * cfg.taker_fee
                    equity -= fee
                    pos = {"d": d, "entry": entry, "stop": pending.stop, "target": pending.target, "qty": qty,
                           "entry_fee": fee, "funding": 0.0, "i": i, "time": idx[i],
                           "risk_usd": qty * per_unit, "reason": pending.reason}
            pending = None

        # 2) manage open position within bar i
        if pos is not None:
            d = pos["d"]
            for ft in _funding_times_between(idx[i], idx[i] + tf_delta, cfg.funding_interval_hours):
                if ft > pos["time"]:
                    pos["funding"] += d * pos["qty"] * c[i] * funding_rate_at(ft)
            stop, target = pos["stop"], pos["target"]
            hit_stop = (l[i] <= stop) if d > 0 else (h[i] >= stop)
            hit_tgt = (h[i] >= target) if d > 0 else (l[i] <= target)
            if hit_stop:
                gap = (o[i] <= stop) if d > 0 else (o[i] >= stop)
                px = (o[i] if gap else stop) * (1 - d * slip)
                close_pos(i, px, cfg.taker_fee, "stop (gap)" if gap else "stop")
            elif hit_tgt:
                close_pos(i, target, cfg.maker_fee, "target")
            elif cfg.max_bars_in_trade and i - pos["i"] + 1 >= cfg.max_bars_in_trade:
                close_pos(i, c[i] * (1 - d * slip), cfg.taker_fee, "time stop")

        # 3) mark to market
        unreal = pos["d"] * (c[i] - pos["entry"]) * pos["qty"] - pos["funding"] if pos else 0.0
        eq_curve[i] = equity + unreal

        # 4) strategy decision at bar close (only rows <= i visible)
        if pos is None and pending is None and i >= trade_start and i < n - 1:
            pending = strategy.signal(data.iloc[: i + 1], i)

    if pos is not None:
        close_pos(n - 1, c[-1] * (1 - pos["d"] * slip), cfg.taker_fee, "end of data")
        eq_curve[-1] = equity
    eq = pd.Series(eq_curve, index=idx, name="equity").iloc[trade_start:]
    ppy = PERIODS_PER_YEAR.get(cfg.timeframe, 365)
    trades_in = [t for t in trades if pd.Timestamp(t["entry_time"]) >= idx[trade_start]] if n else []
    bench = buy_and_hold(data.iloc[trade_start:], cfg.initial_equity, cfg.taker_fee, cfg.slippage_bps)
    # rebase strategy equity to start at initial equity for the evaluation window
    if len(eq) and eq.iloc[0] != 0:
        eq = eq / eq.iloc[0] * cfg.initial_equity
    return BacktestResult(
        strategy=strategy.name, params=dict(strategy.params), trades=trades_in, equity=eq,
        metrics=performance(eq, trades_in, ppy), benchmark_metrics=performance(bench, [], ppy),
    )
