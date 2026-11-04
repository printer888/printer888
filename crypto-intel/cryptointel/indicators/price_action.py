"""Price-action analysis: swings, structure, S/R, breakouts, FVGs, liquidity, patterns.

Swing points need `right` bars after the pivot to be confirmed. Functions here only
return swings whose confirmation bar exists in the supplied data, so nothing uses
future information.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class Swing:
    pos: int          # bar position of the pivot
    confirmed_pos: int  # bar position at which the pivot became known
    ts: pd.Timestamp
    price: float
    kind: str         # "high" | "low"


def swing_points(df: pd.DataFrame, left: int = 3, right: int = 3) -> list[Swing]:
    highs, lows = df["high"].to_numpy(), df["low"].to_numpy()
    n = len(df)
    out: list[Swing] = []
    for i in range(left, n - right):
        h = highs[i]
        if h > highs[i - left : i].max() and h >= highs[i + 1 : i + right + 1].max():
            out.append(Swing(i, i + right, df.index[i], float(h), "high"))
        lo = lows[i]
        if lo < lows[i - left : i].min() and lo <= lows[i + 1 : i + right + 1].min():
            out.append(Swing(i, i + right, df.index[i], float(lo), "low"))
    return out


@dataclass
class Structure:
    trend: str  # "bullish" | "bearish" | "range"
    labels: list[str]
    last_swing_high: float | None
    last_swing_low: float | None
    prev_swing_high: float | None
    prev_swing_low: float | None
    bos: str | None  # "bullish" / "bearish" break of structure on the last close
    choch: str | None  # change of character (potential reversal)
    evidence: list[str] = field(default_factory=list)


def market_structure(df: pd.DataFrame, swings: list[Swing] | None = None) -> Structure:
    swings = swings if swings is not None else swing_points(df)
    sh = [s for s in swings if s.kind == "high"]
    sl = [s for s in swings if s.kind == "low"]
    close = float(df["close"].iloc[-1])
    labels, ev = [], []
    trend = "range"
    if len(sh) >= 2 and len(sl) >= 2:
        hh = sh[-1].price > sh[-2].price
        hl = sl[-1].price > sl[-2].price
        labels += ["HH" if hh else "LH", "HL" if hl else "LL"]
        if hh and hl:
            trend = "bullish"
            ev.append("higher highs and higher lows")
        elif not hh and not hl:
            trend = "bearish"
            ev.append("lower highs and lower lows")
        else:
            ev.append(f"mixed structure ({labels[0]}/{labels[1]}) — range or transition")
    else:
        ev.append("not enough confirmed swings to define structure")

    last_h = sh[-1].price if sh else None
    last_l = sl[-1].price if sl else None
    bos = choch = None
    if last_h is not None and close > last_h:
        bos = "bullish"
        if trend == "bearish":
            choch = "bullish"
            ev.append(f"close {close:.6g} broke the last lower high {last_h:.6g} — bullish change of character")
        else:
            ev.append(f"close broke above last swing high {last_h:.6g} (bullish BOS)")
    elif last_l is not None and close < last_l:
        bos = "bearish"
        if trend == "bullish":
            choch = "bearish"
            ev.append(f"close {close:.6g} broke the last higher low {last_l:.6g} — bearish change of character")
        else:
            ev.append(f"close broke below last swing low {last_l:.6g} (bearish BOS)")
    return Structure(
        trend, labels, last_h, last_l,
        sh[-2].price if len(sh) >= 2 else None, sl[-2].price if len(sl) >= 2 else None,
        bos, choch, ev,
    )


@dataclass
class Level:
    price: float
    touches: int
    last_pos: int
    kind: str  # "support" | "resistance"

    def to_dict(self) -> dict:
        return {"price": self.price, "touches": self.touches, "kind": self.kind}


def support_resistance(
    df: pd.DataFrame, atr_value: float, swings: list[Swing] | None = None, tol_atr: float = 0.5
) -> dict[str, list[Level]]:
    swings = swings if swings is not None else swing_points(df)
    close = float(df["close"].iloc[-1])
    tol = max(atr_value * tol_atr, close * 1e-4)
    pts = sorted(swings, key=lambda s: s.price)
    clusters: list[list[Swing]] = []
    for s in pts:
        if clusters and abs(s.price - np.mean([x.price for x in clusters[-1]])) <= tol:
            clusters[-1].append(s)
        else:
            clusters.append([s])
    supports, resistances = [], []
    for c in clusters:
        price = float(np.mean([x.price for x in c]))
        lvl = Level(price, len(c), max(x.pos for x in c), "support" if price < close else "resistance")
        (supports if price < close else resistances).append(lvl)
    supports.sort(key=lambda l: l.price, reverse=True)
    resistances.sort(key=lambda l: l.price)
    return {"supports": supports, "resistances": resistances}


def breakout(df: pd.DataFrame, lookback: int = 20, rvol: pd.Series | None = None, min_rvol: float = 1.5) -> dict:
    """Close beyond the prior `lookback`-bar range, with volume confirmation."""
    if len(df) < lookback + 2:
        return {"type": None, "evidence": "insufficient bars"}
    prior = df.iloc[-lookback - 1 : -1]
    hi, lo = float(prior["high"].max()), float(prior["low"].min())
    c = float(df["close"].iloc[-1])
    rv = float(rvol.iloc[-1]) if rvol is not None and pd.notna(rvol.iloc[-1]) else None
    vol_ok = rv is not None and rv >= min_rvol
    rv_txt = f"RVOL {rv:.2f}" if rv is not None else "RVOL n/a"
    if c > hi:
        return {"type": "breakout" if vol_ok else "breakout_unconfirmed", "level": hi,
                "evidence": f"close {c:.6g} > {lookback}-bar high {hi:.6g}, {rv_txt}"}
    if c < lo:
        return {"type": "breakdown" if vol_ok else "breakdown_unconfirmed", "level": lo,
                "evidence": f"close {c:.6g} < {lookback}-bar low {lo:.6g}, {rv_txt}"}
    return {"type": None, "range_high": hi, "range_low": lo, "evidence": f"inside {lookback}-bar range"}


def fair_value_gaps(df: pd.DataFrame, lookback: int = 100, min_size_atr: float = 0.1,
                    atr_series: pd.Series | None = None) -> list[dict]:
    """Three-candle imbalances that have not been fully filled by later price."""
    n = len(df)
    hi, lo = df["high"].to_numpy(), df["low"].to_numpy()
    atr_arr = atr_series.to_numpy() if atr_series is not None else None
    gaps = []
    for i in range(max(2, n - lookback), n):
        min_size = (atr_arr[i] * min_size_atr) if atr_arr is not None and np.isfinite(atr_arr[i]) else 0
        if lo[i] > hi[i - 2] and lo[i] - hi[i - 2] > min_size:
            bottom, top = hi[i - 2], lo[i]
            later_low = lo[i + 1 :].min() if i + 1 < n else np.inf
            if later_low > bottom:
                gaps.append({"type": "bullish", "bottom": float(bottom), "top": float(top),
                             "ts": df.index[i - 1].isoformat(), "partially_filled": bool(later_low < top)})
        if hi[i] < lo[i - 2] and lo[i - 2] - hi[i] > min_size:
            bottom, top = hi[i], lo[i - 2]
            later_high = hi[i + 1 :].max() if i + 1 < n else -np.inf
            if later_high < top:
                gaps.append({"type": "bearish", "bottom": float(bottom), "top": float(top),
                             "ts": df.index[i - 1].isoformat(), "partially_filled": bool(later_high > bottom)})
    return gaps[-10:]


def liquidity_zones(swings: list[Swing], atr_value: float, tol_atr: float = 0.15) -> list[dict]:
    """Equal highs/lows: clusters of stops ('resting liquidity') that price often targets."""
    out = []
    tol = atr_value * tol_atr
    for kind, side in (("high", "buy-side liquidity (stops above equal highs)"),
                       ("low", "sell-side liquidity (stops below equal lows)")):
        pts = sorted((s for s in swings[-40:] if s.kind == kind), key=lambda s: s.price)
        group: list[Swing] = []
        for s in pts + [None]:  # sentinel flushes the last group
            if s is not None and group and abs(s.price - group[-1].price) <= tol:
                group.append(s)
                continue
            if len(group) >= 2:
                out.append({"price": float(np.mean([g.price for g in group])), "count": len(group), "type": side})
            group = [s] if s is not None else []
    return out


def candlestick_patterns(df: pd.DataFrame, atr_value: float | None = None) -> list[dict]:
    """Patterns on the last closed candles, with minimal context checks."""
    if len(df) < 4:
        return []
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    out = []
    i = len(df) - 1
    body = abs(c[i] - o[i])
    rng = h[i] - l[i]
    if rng <= 0:
        return out
    upper = h[i] - max(o[i], c[i])
    lower = min(o[i], c[i]) - l[i]
    prior_trend = c[i - 1] - c[max(0, i - 6)]
    big = atr_value is None or rng >= 0.5 * atr_value

    if c[i - 1] < o[i - 1] and c[i] > o[i] and c[i] >= o[i - 1] and o[i] <= c[i - 1] and big:
        out.append({"pattern": "bullish_engulfing", "bias": "bullish"})
    if c[i - 1] > o[i - 1] and c[i] < o[i] and c[i] <= o[i - 1] and o[i] >= c[i - 1] and big:
        out.append({"pattern": "bearish_engulfing", "bias": "bearish"})
    if lower >= 2 * body and upper <= 0.3 * rng and prior_trend < 0:
        out.append({"pattern": "hammer", "bias": "bullish"})
    if upper >= 2 * body and lower <= 0.3 * rng and prior_trend > 0:
        out.append({"pattern": "shooting_star", "bias": "bearish"})
    if body <= 0.1 * rng:
        out.append({"pattern": "doji", "bias": "neutral"})
    if h[i] < h[i - 1] and l[i] > l[i - 1]:
        out.append({"pattern": "inside_bar", "bias": "neutral"})
    # Morning / evening star (3 candles)
    b1, b2 = abs(c[i - 2] - o[i - 2]), abs(c[i - 1] - o[i - 1])
    if c[i - 2] < o[i - 2] and b2 < 0.5 * b1 and c[i] > o[i] and c[i] > (o[i - 2] + c[i - 2]) / 2:
        out.append({"pattern": "morning_star", "bias": "bullish"})
    if c[i - 2] > o[i - 2] and b2 < 0.5 * b1 and c[i] < o[i] and c[i] < (o[i - 2] + c[i - 2]) / 2:
        out.append({"pattern": "evening_star", "bias": "bearish"})
    return out


def rsi_divergence(df: pd.DataFrame, rsi_series: pd.Series, swings: list[Swing]) -> str | None:
    """Regular divergence between the last two confirmed swing lows/highs."""
    r = rsi_series.to_numpy()
    lows = [s for s in swings if s.kind == "low"][-2:]
    highs = [s for s in swings if s.kind == "high"][-2:]
    n = len(df)
    if len(lows) == 2 and lows[-1].pos >= n - 30:
        a, b = lows
        if b.price < a.price and np.isfinite(r[a.pos]) and np.isfinite(r[b.pos]) and r[b.pos] > r[a.pos] + 2:
            return "bullish"
    if len(highs) == 2 and highs[-1].pos >= n - 30:
        a, b = highs
        if b.price > a.price and np.isfinite(r[a.pos]) and np.isfinite(r[b.pos]) and r[b.pos] < r[a.pos] - 2:
            return "bearish"
    return None
