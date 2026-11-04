"""Rule-based strategies. Each uses multiple, independent confirmations.

`prepare` adds causal indicator columns; `signal(df, i)` may only read rows <= i
(the engine passes a truncated frame to enforce this).
"""
from __future__ import annotations

import math

import pandas as pd

from ..indicators import ta
from .engine import Order


def _ok(*vals) -> bool:
    return all(v is not None and not (isinstance(v, float) and math.isnan(v)) for v in vals)


class TrendPullback:
    """Trade pullbacks within an established trend.

    Long: close > EMA200, EMA20 > EMA50, ADX > adx_min, RSI crosses back above
    `rsi_trigger` after dipping, close > EMA20. Stop = atr_stop × ATR, target = rr × risk.
    """

    name = "trend_pullback"
    default_params = {"rsi_trigger": 45, "adx_min": 20, "atr_stop": 1.5, "rr": 2.0}

    def __init__(self, **params):
        self.params = {**self.default_params, **params}

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        out["ema20"], out["ema50"], out["ema200"] = ta.ema(df.close, 20), ta.ema(df.close, 50), ta.ema(df.close, 200)
        out["rsi"] = ta.rsi(df.close)
        out["atr"] = ta.atr(df)
        out["adx"] = ta.adx(df)["adx"]
        return out

    def signal(self, df: pd.DataFrame, i: int) -> Order | None:
        if i < 1:
            return None
        r, prev = df.iloc[i], df.iloc[i - 1]
        if not _ok(r.ema200, r.ema50, r.adx, r.atr, prev.rsi, r.rsi):
            return None
        p = self.params
        lo_trig, hi_trig = p["rsi_trigger"], 100 - p["rsi_trigger"]
        if r.close > r.ema200 and r.ema20 > r.ema50 and r.adx > p["adx_min"] and prev.rsi < lo_trig <= r.rsi \
                and r.close > r.ema20:
            stop = r.close - p["atr_stop"] * r.atr
            return Order("long", stop, r.close + p["rr"] * (r.close - stop), "trend pullback long")
        if r.close < r.ema200 and r.ema20 < r.ema50 and r.adx > p["adx_min"] and prev.rsi > hi_trig >= r.rsi \
                and r.close < r.ema20:
            stop = r.close + p["atr_stop"] * r.atr
            return Order("short", stop, r.close - p["rr"] * (stop - r.close), "trend pullback short")
        return None


class DonchianBreakout:
    """Range breakout confirmed by relative volume and trend filter (EMA50 slope)."""

    name = "donchian_breakout"
    default_params = {"lookback": 20, "rvol_min": 1.5, "atr_stop": 2.0, "rr": 2.5}

    def __init__(self, **params):
        self.params = {**self.default_params, **params}

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        n = int(self.params["lookback"])
        out = df.copy()
        out["dc_high"] = df.high.shift(1).rolling(n, min_periods=n).max()
        out["dc_low"] = df.low.shift(1).rolling(n, min_periods=n).min()
        out["rvol"] = ta.relative_volume(df.volume, 20)
        out["atr"] = ta.atr(df)
        out["ema50"] = ta.ema(df.close, 50)
        out["ema50_prev"] = out["ema50"].shift(5)
        return out

    def signal(self, df: pd.DataFrame, i: int) -> Order | None:
        r = df.iloc[i]
        if not _ok(r.dc_high, r.dc_low, r.rvol, r.atr, r.ema50, r.ema50_prev):
            return None
        p = self.params
        if r.close > r.dc_high and r.rvol >= p["rvol_min"] and r.ema50 > r.ema50_prev:
            stop = r.close - p["atr_stop"] * r.atr
            return Order("long", stop, r.close + p["rr"] * (r.close - stop), "volume breakout long")
        if r.close < r.dc_low and r.rvol >= p["rvol_min"] and r.ema50 < r.ema50_prev:
            stop = r.close + p["atr_stop"] * r.atr
            return Order("short", stop, r.close - p["rr"] * (stop - r.close), "volume breakdown short")
        return None


class BollingerReversion:
    """Mean reversion only in non-trending regimes (ADX below threshold)."""

    name = "bollinger_reversion"
    default_params = {"adx_max": 20, "rsi_low": 30, "atr_stop": 1.5}

    def __init__(self, **params):
        self.params = {**self.default_params, **params}

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy().join(ta.bollinger(df.close).add_prefix("bb_"))
        out["rsi"] = ta.rsi(df.close)
        out["adx"] = ta.adx(df)["adx"]
        out["atr"] = ta.atr(df)
        return out

    def signal(self, df: pd.DataFrame, i: int) -> Order | None:
        r = df.iloc[i]
        if not _ok(r.bb_lower, r.bb_upper, r.bb_mid, r.rsi, r.adx, r.atr):
            return None
        p = self.params
        if r.adx < p["adx_max"] and r.close < r.bb_lower and r.rsi < p["rsi_low"]:
            return Order("long", r.close - p["atr_stop"] * r.atr, r.bb_mid, "BB lower-band reversion")
        if r.adx < p["adx_max"] and r.close > r.bb_upper and r.rsi > 100 - p["rsi_low"]:
            return Order("short", r.close + p["atr_stop"] * r.atr, r.bb_mid, "BB upper-band reversion")
        return None


STRATEGIES = {s.name: s for s in (TrendPullback, DonchianBreakout, BollingerReversion)}

# Deliberately small grids: fewer combinations → less data-mining.
PARAM_GRIDS = {
    "trend_pullback": {"rsi_trigger": [40, 45], "adx_min": [18, 25], "atr_stop": [1.5, 2.0], "rr": [2.0, 3.0]},
    "donchian_breakout": {"lookback": [20, 40], "rvol_min": [1.3, 1.8], "atr_stop": [1.5, 2.5], "rr": [2.0, 3.0]},
    "bollinger_reversion": {"adx_max": [18, 22], "rsi_low": [25, 30], "atr_stop": [1.0, 1.5]},
}
