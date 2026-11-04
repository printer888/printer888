import numpy as np
import pandas as pd
import pytest

from cryptointel.indicators import ta


def test_ema_matches_recursive_definition(synth):
    df = synth(100)
    e = ta.ema(df.close, 10)
    alpha = 2 / 11
    manual = [df.close.iloc[0]]
    for x in df.close.iloc[1:]:
        manual.append(alpha * x + (1 - alpha) * manual[-1])
    assert np.allclose(e.iloc[9:], manual[9:])
    assert e.iloc[:9].isna().all()


def test_rsi_edge_cases():
    up = pd.Series(np.arange(1, 50, dtype=float))
    assert ta.rsi(up).iloc[-1] == pytest.approx(100)
    flat = pd.Series(np.full(50, 5.0))
    assert ta.rsi(flat).iloc[-1] == pytest.approx(50)


def test_rsi_wilder_reference():
    rng = np.random.default_rng(1)
    c = pd.Series(100 + rng.normal(0, 1, 200).cumsum())
    r = ta.rsi(c, 14)
    d = c.diff().to_numpy()
    g, l = np.clip(d, 0, None), np.clip(-d, 0, None)
    # Wilder EWM with adjust=False is seeded at the first value; replicate exactly
    ag, al = g[1], l[1]
    out = {}
    for i in range(2, len(c)):
        ag = ag + (g[i] - ag) / 14
        al = al + (l[i] - al) / 14
        out[i] = 100 - 100 / (1 + ag / al) if al else 100.0
    assert r.iloc[-1] == pytest.approx(out[len(c) - 1], rel=1e-9)
    assert ((r.dropna() >= 0) & (r.dropna() <= 100)).all()


def test_atr_constant_range():
    n = 60
    idx = pd.date_range("2025", periods=n, freq="h", tz="UTC")
    df = pd.DataFrame({"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1.0}, index=idx)
    assert ta.atr(df).iloc[-1] == pytest.approx(2.0)


def test_adx_bounds_and_trend(synth):
    df = synth(400, drift=0.003, vol=0.005)
    a = ta.adx(df).dropna()
    assert ((a.adx >= 0) & (a.adx <= 100)).all()
    assert a.plus_di.iloc[-1] > a.minus_di.iloc[-1]


def test_bollinger_and_macd(synth):
    df = synth(200)
    bb = ta.bollinger(df.close)
    valid = bb.dropna()
    assert (valid.upper >= valid.mid).all() and (valid.mid >= valid.lower).all()
    m = ta.macd(df.close)
    assert np.allclose((m.macd - m.signal).dropna(), m["hist"].dropna())


def test_vwap_resets_each_day(synth):
    df = synth(72)
    v = ta.vwap(df, "D")
    first_bar_day2 = df.index[24]
    tp = (df.high + df.low + df.close) / 3
    assert v.loc[first_bar_day2] == pytest.approx(tp.loc[first_bar_day2])


def test_obv_and_rvol():
    idx = pd.date_range("2025", periods=25, freq="h", tz="UTC")
    close = pd.Series(np.r_[np.arange(1, 25), 30.0], index=idx)
    vol = pd.Series(np.r_[np.full(24, 10.0), 50.0], index=idx)
    df = pd.DataFrame({"open": close, "high": close, "low": close, "close": close, "volume": vol})
    assert ta.obv(df).iloc[-1] == pytest.approx(23 * 10 + 50)
    assert ta.relative_volume(vol, 20).iloc[-1] == pytest.approx(5.0)


def test_volume_profile_poc():
    idx = pd.date_range("2025", periods=30, freq="h", tz="UTC")
    close = np.r_[np.full(20, 100.0), np.linspace(101, 110, 10)]
    vol = np.r_[np.full(20, 100.0), np.full(10, 1.0)]
    df = pd.DataFrame({"open": close, "high": close + 0.1, "low": close - 0.1, "close": close, "volume": vol}, index=idx)
    vp = ta.volume_profile(df, bins=20)
    assert abs(vp["poc"] - 100) < 1
    assert vp["val"] <= vp["poc"] <= vp["vah"]


def test_volume_delta_only_from_trades():
    assert ta.volume_delta_from_trades(pd.DataFrame())["available"] is False
    idx = pd.date_range("2025", periods=3, freq="s", tz="UTC")
    tr = pd.DataFrame({"price": [10, 10, 10], "size": [3, 1, 1], "side": ["Buy", "Sell", "Sell"]}, index=idx)
    d = ta.volume_delta_from_trades(tr)
    assert d["delta_usd"] == pytest.approx(10) and d["delta_ratio"] == pytest.approx(0.2)


def test_indicators_are_causal(synth):
    """Changing future bars must not change past indicator values."""
    df = synth(400)
    a = ta.compute_all(df)
    df2 = df.copy()
    df2.iloc[300:, :4] *= 1.5
    b = ta.compute_all(df2)
    cols = ["ema20", "ema200", "rsi", "macd", "adx", "atr", "bb_upper", "cci", "obv", "rvol", "stochrsi_k"]
    pd.testing.assert_frame_equal(a[cols].iloc[:300], b[cols].iloc[:300])
