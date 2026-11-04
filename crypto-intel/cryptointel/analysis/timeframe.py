"""Explainable single-timeframe analysis combining indicators and price action."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd

from ..data.freshness import TIMEFRAME_SECONDS, humanize_age, max_candle_age, utcnow
from ..indicators import price_action as pa
from ..indicators import ta

MIN_BARS = 60

SNAPSHOT_COLS = [
    "close", "ema9", "ema20", "ema50", "ema100", "ema200", "sma50", "sma200", "macd", "macd_signal",
    "macd_hist", "adx", "plus_di", "minus_di", "rsi", "stochrsi_k", "stochrsi_d", "roc", "cci",
    "bb_upper", "bb_mid", "bb_lower", "bb_pct_b", "bb_bandwidth", "atr", "atr_pct", "hv", "vwap",
    "obv_slope", "rvol",
]


def _f(x) -> float | None:
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


@dataclass
class TimeframeAnalysis:
    timeframe: str
    sufficient: bool
    bars: int
    last_close_time: datetime | None = None
    stale: bool = True
    age: str = ""
    trend: str = "neutral"
    bias: float = 0.0
    adx: float | None = None
    volatility_regime: str = "unknown"
    snapshot: dict = field(default_factory=dict)
    structure: dict = field(default_factory=dict)
    supports: list[dict] = field(default_factory=list)
    resistances: list[dict] = field(default_factory=list)
    breakout: dict = field(default_factory=dict)
    fvgs: list[dict] = field(default_factory=list)
    liquidity: list[dict] = field(default_factory=list)
    patterns: list[dict] = field(default_factory=list)
    divergence: str | None = None
    volume_profile: dict = field(default_factory=dict)
    bullish_evidence: list[str] = field(default_factory=list)
    bearish_evidence: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    swing_highs: list[float] = field(default_factory=list)
    swing_lows: list[float] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["last_close_time"] = self.last_close_time.isoformat() if self.last_close_time else None
        return d


def analyze_timeframe(df: pd.DataFrame, timeframe: str, now: datetime | None = None) -> TimeframeAnalysis:
    now = now or utcnow()
    if df is None or len(df) < MIN_BARS:
        return TimeframeAnalysis(timeframe, False, 0 if df is None else len(df),
                                 notes=[f"only {0 if df is None else len(df)} closed bars (< {MIN_BARS}); not analysed"])
    ind = ta.compute_all(df, timeframe)
    last = ind.iloc[-1]
    snap = {k: _f(last.get(k)) for k in SNAPSHOT_COLS}
    snap["candle_dir"] = float(np.sign(last["close"] - last["open"]))
    close = snap["close"]
    last_close_time = ind.index[-1].to_pydatetime() + pd.Timedelta(seconds=TIMEFRAME_SECONDS[timeframe])
    age_s = (now - last_close_time).total_seconds()
    res = TimeframeAnalysis(
        timeframe=timeframe, sufficient=True, bars=len(df), last_close_time=last_close_time,
        stale=age_s > max_candle_age(timeframe), age=humanize_age(age_s), snapshot=snap, adx=snap["adx"],
    )
    bull, bear, notes = res.bullish_evidence, res.bearish_evidence, res.notes
    score, weight = 0.0, 0.0

    def vote(cond_bull: bool, cond_bear: bool, w: float, bull_txt: str, bear_txt: str) -> None:
        nonlocal score, weight
        weight += w
        if cond_bull:
            score += w
            bull.append(bull_txt)
        elif cond_bear:
            score -= w
            bear.append(bear_txt)

    # --- trend
    if snap["ema200"] is not None:
        vote(close > snap["ema200"], close < snap["ema200"], 0.20,
             "price above EMA200", "price below EMA200")
    else:
        notes.append("EMA200 unavailable (insufficient history) — long-term trend unknown")
    if snap["ema20"] is not None and snap["ema50"] is not None:
        vote(snap["ema20"] > snap["ema50"], snap["ema20"] < snap["ema50"], 0.15,
             "EMA20 above EMA50", "EMA20 below EMA50")
    emas = [snap[f"ema{n}"] for n in (9, 20, 50, 100, 200)]
    if all(e is not None for e in emas):
        up = all(a > b for a, b in zip(emas, emas[1:]))
        dn = all(a < b for a, b in zip(emas, emas[1:]))
        vote(up, dn, 0.10, "EMA 9>20>50>100>200 fully stacked bullish", "EMAs fully stacked bearish")
    if snap["macd"] is not None and snap["macd_hist"] is not None:
        vote(snap["macd"] > 0 and snap["macd_hist"] > 0, snap["macd"] < 0 and snap["macd_hist"] < 0, 0.10,
             "MACD above zero with positive histogram", "MACD below zero with negative histogram")
    # --- momentum
    if snap["rsi"] is not None:
        vote(55 <= snap["rsi"] < 75, 25 < snap["rsi"] <= 45, 0.10,
             f"RSI {snap['rsi']:.0f} in bullish momentum zone", f"RSI {snap['rsi']:.0f} in bearish momentum zone")
        if snap["rsi"] >= 75:
            notes.append(f"RSI {snap['rsi']:.0f} overbought — late-entry risk for longs")
        if snap["rsi"] <= 25:
            notes.append(f"RSI {snap['rsi']:.0f} oversold — late-entry risk for shorts")
    if snap["roc"] is not None:
        vote(snap["roc"] > 0, snap["roc"] < 0, 0.05, f"ROC(10) {snap['roc']:+.2f}%", f"ROC(10) {snap['roc']:+.2f}%")
    if snap["cci"] is not None and abs(snap["cci"]) > 100:
        notes.append(f"CCI {snap['cci']:.0f} — {'stretched up' if snap['cci'] > 0 else 'stretched down'}")
    # --- volume
    if snap["vwap"] is not None:
        vote(close > snap["vwap"], close < snap["vwap"], 0.05, "price above VWAP", "price below VWAP")
    if snap["obv_slope"] is not None:
        vote(snap["obv_slope"] > 0, snap["obv_slope"] < 0, 0.05, "OBV rising (accumulation)", "OBV falling (distribution)")

    # --- structure
    swings = pa.swing_points(ind)
    res.swing_highs = [s.price for s in swings if s.kind == "high"][-5:]
    res.swing_lows = [s.price for s in swings if s.kind == "low"][-5:]
    st = pa.market_structure(ind, swings)
    res.structure = {k: v for k, v in st.__dict__.items()}
    vote(st.trend == "bullish", st.trend == "bearish", 0.20,
         "market structure: " + "; ".join(st.evidence), "market structure: " + "; ".join(st.evidence))
    if st.choch:
        (bull if st.choch == "bullish" else bear).append(f"{st.choch} change of character")

    atr_v = snap["atr"] or float((ind["high"] - ind["low"]).tail(14).mean())
    lv = pa.support_resistance(ind.tail(200), atr_v, [s for s in swings if s.pos >= len(ind) - 200])
    res.supports = [l.to_dict() for l in lv["supports"][:5]]
    res.resistances = [l.to_dict() for l in lv["resistances"][:5]]
    res.breakout = pa.breakout(ind, 20, ind["rvol"])
    if res.breakout.get("type") == "breakout":
        bull.append("volume-confirmed breakout: " + res.breakout["evidence"])
    elif res.breakout.get("type") == "breakdown":
        bear.append("volume-confirmed breakdown: " + res.breakout["evidence"])
    elif res.breakout.get("type"):
        notes.append("unconfirmed range break (low volume): " + res.breakout["evidence"])
    res.fvgs = pa.fair_value_gaps(ind, 100, 0.1, ind["atr"])
    res.liquidity = pa.liquidity_zones(swings, atr_v)
    res.patterns = pa.candlestick_patterns(ind, atr_v)
    for p in res.patterns:
        if p["bias"] == "bullish":
            bull.append(f"candlestick: {p['pattern']}")
        elif p["bias"] == "bearish":
            bear.append(f"candlestick: {p['pattern']}")
    res.divergence = pa.rsi_divergence(ind, ind["rsi"], swings)
    if res.divergence:
        (bull if res.divergence == "bullish" else bear).append(f"{res.divergence} RSI divergence")
    res.volume_profile = {k: v for k, v in ta.volume_profile(ind.tail(100)).items() if k != "levels"}

    # --- volatility regime: current ATR% vs its own last-100-bar distribution
    atrp = ind["atr_pct"].dropna().tail(100)
    if len(atrp) >= 30:
        pct = float((atrp < atrp.iloc[-1]).mean())
        res.volatility_regime = "high" if pct >= 0.85 else "low" if pct <= 0.15 else "normal"
        res.snapshot["atr_pct_percentile"] = round(pct * 100, 1)
    if snap["bb_bandwidth"] is not None:
        bw = ind["bb_bandwidth"].dropna().tail(120)
        if len(bw) >= 30 and bw.iloc[-1] <= bw.quantile(0.1):
            notes.append("Bollinger squeeze (bandwidth in lowest decile) — volatility expansion likely, direction unknown")

    res.bias = float(np.clip(score / weight, -1, 1)) if weight else 0.0
    adx_v = snap["adx"] or 0
    if res.bias >= 0.35:
        res.trend = "bullish"
    elif res.bias <= -0.35:
        res.trend = "bearish"
    else:
        res.trend = "neutral"
    if adx_v < 18:
        notes.append(f"ADX {adx_v:.0f} — weak/no trend; trend signals less reliable")
    return res
