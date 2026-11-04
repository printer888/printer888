import numpy as np
import pandas as pd

from cryptointel.indicators import price_action as pa


def _from_close(close, spread=0.2):
    idx = pd.date_range("2025", periods=len(close), freq="h", tz="UTC")
    close = np.asarray(close, dtype=float)
    o = np.r_[close[0], close[:-1]]
    return pd.DataFrame({"open": o, "high": np.maximum(o, close) + spread, "low": np.minimum(o, close) - spread,
                         "close": close, "volume": 100.0}, index=idx)


def zigzag(up=True):
    pts = [100, 110, 104, 116, 109, 122, 114, 128] if up else [128, 118, 124, 112, 119, 105, 111, 98]
    seg = []
    for a, b in zip(pts, pts[1:]):
        seg += list(np.linspace(a, b, 8, endpoint=False))
    seg.append(pts[-1])
    return _from_close(seg)


def test_swings_are_confirmed_only_with_future_bars():
    df = zigzag()
    sw = pa.swing_points(df, 3, 3)
    assert sw, "expected swings"
    assert all(s.confirmed_pos == s.pos + 3 and s.confirmed_pos < len(df) for s in sw)


def test_structure_bullish_and_bearish():
    assert pa.market_structure(zigzag(True)).trend == "bullish"
    assert pa.market_structure(zigzag(False)).trend == "bearish"


def test_support_resistance_split_by_price():
    df = zigzag()
    lv = pa.support_resistance(df, atr_value=1.0)
    close = df.close.iloc[-1]
    assert all(l.price < close for l in lv["supports"])
    assert all(l.price > close for l in lv["resistances"])


def test_fair_value_gap_detected_and_filled():
    close = [100, 100, 100, 100, 106, 112, 113, 114]
    df = _from_close(close, spread=0.1)
    gaps = pa.fair_value_gaps(df, lookback=10)
    assert any(g["type"] == "bullish" for g in gaps)
    # price returns through the gap → it is filled and disappears
    df2 = _from_close(close + [100, 99], spread=0.1)
    assert not any(g["type"] == "bullish" for g in pa.fair_value_gaps(df2, lookback=12))


def test_bullish_engulfing():
    idx = pd.date_range("2025", periods=6, freq="h", tz="UTC")
    df = pd.DataFrame({"open": [10, 9.8, 9.6, 9.4, 9.3, 8.9], "close": [9.8, 9.6, 9.4, 9.3, 9.0, 9.5],
                       "high": [10.1, 9.9, 9.7, 9.5, 9.35, 9.6], "low": [9.7, 9.5, 9.3, 9.2, 8.95, 8.85],
                       "volume": 1}, index=idx)
    pats = [p["pattern"] for p in pa.candlestick_patterns(df)]
    assert "bullish_engulfing" in pats


def test_breakout_requires_volume():
    df = _from_close(list(np.full(25, 100.0)) + [105.0])
    rv_low = pd.Series(1.0, index=df.index)
    rv_hi = pd.Series(2.0, index=df.index)
    assert pa.breakout(df, 20, rv_low)["type"] == "breakout_unconfirmed"
    assert pa.breakout(df, 20, rv_hi)["type"] == "breakout"
