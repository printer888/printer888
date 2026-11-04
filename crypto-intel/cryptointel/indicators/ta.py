"""Technical indicators implemented with pandas/numpy.

All functions are *causal*: the value at bar t depends only on bars <= t.
Wilder smoothing (alpha = 1/n) is used where the original definition requires it
(RSI, ATR, ADX), matching TA-Lib / TradingView conventions after warm-up.
Inputs are DataFrames with columns open, high, low, close, volume.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# ------------------------------------------------------------------ helpers
def _wilder(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()


# ------------------------------------------------------------------ trend
def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    line = ema(close, fast) - ema(close, slow)
    sig = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return pd.DataFrame({"macd": line, "signal": sig, "hist": line - sig})


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()], axis=1
    ).max(axis=1)
    tr.iloc[0] = df["high"].iloc[0] - df["low"].iloc[0] if len(df) else np.nan
    return tr


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    return _wilder(true_range(df), n)


def adx(df: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    atr_n = atr(df, n)
    plus_di = 100 * _wilder(plus_dm, n) / atr_n
    minus_di = 100 * _wilder(minus_dm, n) / atr_n
    denom = (plus_di + minus_di).replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / denom
    return pd.DataFrame({"adx": _wilder(dx, n), "plus_di": plus_di, "minus_di": minus_di})


# ------------------------------------------------------------------ momentum
def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = _wilder(delta.clip(lower=0), n)
    loss = _wilder(-delta.clip(upper=0), n)
    rs = gain / loss
    out = 100 - 100 / (1 + rs)
    out = out.where(loss != 0, 100.0)
    out = out.where(~((gain == 0) & (loss == 0)), 50.0)
    return out.where(gain.notna())


def stoch_rsi(close: pd.Series, rsi_n: int = 14, stoch_n: int = 14, k: int = 3, d: int = 3) -> pd.DataFrame:
    r = rsi(close, rsi_n)
    lo = r.rolling(stoch_n, min_periods=stoch_n).min()
    hi = r.rolling(stoch_n, min_periods=stoch_n).max()
    raw = 100 * (r - lo) / (hi - lo).replace(0, np.nan)
    k_line = raw.rolling(k, min_periods=k).mean()
    return pd.DataFrame({"k": k_line, "d": k_line.rolling(d, min_periods=d).mean()})


def roc(close: pd.Series, n: int = 10) -> pd.Series:
    return 100 * (close / close.shift(n) - 1)


def cci(df: pd.DataFrame, n: int = 20) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3
    ma = tp.rolling(n, min_periods=n).mean()
    mad = tp.rolling(n, min_periods=n).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
    return (tp - ma) / (0.015 * mad.replace(0, np.nan))


# ------------------------------------------------------------------ volatility
def bollinger(close: pd.Series, n: int = 20, k: float = 2.0) -> pd.DataFrame:
    mid = sma(close, n)
    sd = close.rolling(n, min_periods=n).std(ddof=0)
    upper, lower = mid + k * sd, mid - k * sd
    width = (upper - lower) / mid
    pct_b = (close - lower) / (upper - lower).replace(0, np.nan)
    return pd.DataFrame({"mid": mid, "upper": upper, "lower": lower, "bandwidth": width, "pct_b": pct_b})


def historical_volatility(close: pd.Series, n: int = 20, periods_per_year: float = 365) -> pd.Series:
    """Annualised close-to-close volatility (crypto trades 365 days/year)."""
    lr = np.log(close / close.shift(1))
    return lr.rolling(n, min_periods=n).std(ddof=1) * np.sqrt(periods_per_year)


PERIODS_PER_YEAR = {
    "1m": 525_600, "5m": 105_120, "15m": 35_040, "1h": 8_760, "4h": 2_190, "1d": 365, "1w": 52,
}


# ------------------------------------------------------------------ volume
def vwap(df: pd.DataFrame, anchor: str | None = "D") -> pd.Series:
    """Anchored VWAP (resets each UTC session for anchor='D'); cumulative if anchor is None."""
    tp = (df["high"] + df["low"] + df["close"]) / 3
    pv = tp * df["volume"]
    if anchor is None:
        return pv.cumsum() / df["volume"].cumsum().replace(0, np.nan)
    keys = df.index.floor(anchor) if anchor != "W" else df.index.to_period("W").start_time
    return pv.groupby(keys).cumsum() / df["volume"].groupby(keys).cumsum().replace(0, np.nan)


def rolling_vwap(df: pd.DataFrame, n: int = 20) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3
    return (tp * df["volume"]).rolling(n, min_periods=n).sum() / df["volume"].rolling(n, min_periods=n).sum()


def obv(df: pd.DataFrame) -> pd.Series:
    direction = np.sign(df["close"].diff()).fillna(0)
    return (direction * df["volume"]).cumsum()


def relative_volume(volume: pd.Series, n: int = 20) -> pd.Series:
    """Current bar volume / average of the *previous* n bars."""
    base = volume.shift(1).rolling(n, min_periods=n).mean()
    return volume / base.replace(0, np.nan)


def volume_profile(df: pd.DataFrame, bins: int = 24, value_area: float = 0.70) -> dict:
    """Volume-by-price histogram using each bar's typical price.

    Returns POC (point of control), value-area high/low and the histogram.
    This is an approximation: intrabar distribution of volume is unknown.
    """
    if df.empty:
        return {"poc": None, "vah": None, "val": None, "levels": []}
    lo, hi = df["low"].min(), df["high"].max()
    if hi <= lo:
        return {"poc": float(lo), "vah": float(hi), "val": float(lo), "levels": []}
    edges = np.linspace(lo, hi, bins + 1)
    tp = ((df["high"] + df["low"] + df["close"]) / 3).to_numpy()
    idx = np.clip(np.digitize(tp, edges) - 1, 0, bins - 1)
    vol = np.bincount(idx, weights=df["volume"].to_numpy(), minlength=bins)
    centers = (edges[:-1] + edges[1:]) / 2
    poc_i = int(np.argmax(vol))
    total = vol.sum()
    lo_i = hi_i = poc_i
    acc = vol[poc_i]
    while total > 0 and acc / total < value_area and (lo_i > 0 or hi_i < bins - 1):
        below = vol[lo_i - 1] if lo_i > 0 else -1
        above = vol[hi_i + 1] if hi_i < bins - 1 else -1
        if above >= below:
            hi_i += 1
            acc += vol[hi_i]
        else:
            lo_i -= 1
            acc += vol[lo_i]
    return {
        "poc": float(centers[poc_i]),
        "vah": float(edges[hi_i + 1]),
        "val": float(edges[lo_i]),
        "levels": [{"price": float(c), "volume": float(v)} for c, v in zip(centers, vol)],
    }


def volume_delta_from_trades(trades: pd.DataFrame) -> dict:
    """Aggressor volume delta from real trade prints (columns price, size, side).

    Candle data does not contain aggressor side, so delta is *never* estimated
    from OHLCV in this project.
    """
    if trades is None or trades.empty:
        return {"available": False}
    notional = trades["price"] * trades["size"]
    buy = float(notional[trades["side"] == "Buy"].sum())
    sell = float(notional[trades["side"] == "Sell"].sum())
    total = buy + sell
    return {
        "available": total > 0,
        "buy_usd": buy,
        "sell_usd": sell,
        "delta_usd": buy - sell,
        "delta_ratio": (buy - sell) / total if total else None,
        "window_start": trades.index[0].isoformat(),
        "window_end": trades.index[-1].isoformat(),
        "n_trades": int(len(trades)),
    }


def slope(s: pd.Series, n: int = 10) -> pd.Series:
    """Least-squares slope over n bars, normalised by the series' mean level."""
    x = np.arange(n) - (n - 1) / 2
    denom = (x ** 2).sum()

    def _f(y: np.ndarray) -> float:
        m = np.abs(y).mean()
        return float((x * (y - y.mean())).sum() / denom / m) if m else 0.0

    return s.rolling(n, min_periods=n).apply(_f, raw=True)


# ------------------------------------------------------------------ bundle
def compute_all(df: pd.DataFrame, timeframe: str = "1h") -> pd.DataFrame:
    """Attach the full indicator set as columns (copy of df)."""
    out = df.copy()
    c = out["close"]
    for n in (9, 20, 50, 100, 200):
        out[f"ema{n}"] = ema(c, n)
    out["sma50"] = sma(c, 50)
    out["sma200"] = sma(c, 200)
    out = out.join(macd(c).add_prefix("macd_").rename(columns={"macd_macd": "macd"}))
    out = out.join(adx(out))
    out["rsi"] = rsi(c)
    out = out.join(stoch_rsi(c).add_prefix("stochrsi_"))
    out["roc"] = roc(c, 10)
    out["cci"] = cci(out)
    out = out.join(bollinger(c).add_prefix("bb_"))
    out["atr"] = atr(out)
    out["atr_pct"] = out["atr"] / c * 100
    out["hv"] = historical_volatility(c, 20, PERIODS_PER_YEAR.get(timeframe, 365))
    out["vwap"] = vwap(out, "D") if timeframe in ("1m", "5m", "15m", "1h") else rolling_vwap(out, 20)
    out["obv"] = obv(out)
    out["obv_slope"] = slope(out["obv"], 10)
    out["rvol"] = relative_volume(out["volume"], 20)
    return out
