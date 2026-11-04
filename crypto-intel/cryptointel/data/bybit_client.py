"""Bybit v5 public market-data REST client.

Only public, unauthenticated endpoints are used. This client contains no
order-placement code by design.

Docs: https://bybit-exchange.github.io/docs/v5/intro
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

import httpx
import numpy as np
import pandas as pd

from .freshness import TIMEFRAME_SECONDS, utcnow

log = logging.getLogger(__name__)

INTERVAL_MAP = {"1m": "1", "5m": "5", "15m": "15", "1h": "60", "4h": "240", "1d": "D", "1w": "W"}
OI_INTERVALS = {"5m": "5min", "15m": "15min", "30m": "30min", "1h": "1h", "4h": "4h", "1d": "1d"}


class BybitAPIError(RuntimeError):
    def __init__(self, ret_code: int, ret_msg: str, path: str):
        super().__init__(f"Bybit error {ret_code} on {path}: {ret_msg}")
        self.ret_code = ret_code
        self.ret_msg = ret_msg


class RateLimiter:
    """Simple thread-safe minimum-interval limiter."""

    def __init__(self, per_second: float):
        self.min_interval = 1.0 / per_second if per_second > 0 else 0.0
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delay = self._last + self.min_interval - now
            if delay > 0:
                time.sleep(delay)
            self._last = time.monotonic()


class BybitClient:
    def __init__(
        self,
        base_url: str = "https://api.bybit.com",
        timeout: float = 10.0,
        max_requests_per_second: float = 8.0,
        max_retries: int = 4,
        transport: httpx.BaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.max_retries = max_retries
        self._limiter = RateLimiter(max_requests_per_second)
        self._http = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            transport=transport,
            headers={"User-Agent": "cryptointel-research/0.1"},
        )

    def close(self) -> None:
        self._http.close()

    # ------------------------------------------------------------------ core
    def _get(self, path: str, params: dict[str, Any]) -> dict:
        params = {k: v for k, v in params.items() if v is not None}
        backoff = 1.0
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            self._limiter.wait()
            try:
                resp = self._http.get(path, params=params)
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise httpx.HTTPStatusError(
                        f"HTTP {resp.status_code}", request=resp.request, response=resp
                    )
                resp.raise_for_status()
                payload = resp.json()
                code = payload.get("retCode", -1)
                if code == 10006:  # rate limit
                    raise BybitAPIError(code, payload.get("retMsg", ""), path)
                if code != 0:
                    # Non-retryable business errors (bad symbol, bad params...)
                    raise BybitAPIError(code, payload.get("retMsg", ""), path)
                return payload.get("result", {})
            except BybitAPIError as e:
                if e.ret_code != 10006:
                    raise
                last_exc = e
            except (httpx.TransportError, httpx.HTTPStatusError, ValueError) as e:
                last_exc = e
            if attempt < self.max_retries:
                log.warning("Bybit request %s failed (%s); retry in %.1fs", path, last_exc, backoff)
                time.sleep(backoff)
                backoff = min(backoff * 2, 16)
        raise RuntimeError(f"Bybit request {path} failed after retries: {last_exc}")

    # -------------------------------------------------------------- endpoints
    def server_time_ms(self) -> int:
        res = self._get("/v5/market/time", {})
        return int(res["timeNano"]) // 1_000_000 if "timeNano" in res else int(res["timeSecond"]) * 1000

    def instruments(self, category: str = "linear") -> list[dict]:
        out: list[dict] = []
        cursor = None
        while True:
            res = self._get(
                "/v5/market/instruments-info", {"category": category, "limit": 1000, "cursor": cursor}
            )
            out.extend(res.get("list", []))
            cursor = res.get("nextPageCursor")
            if not cursor:
                break
        return out

    def tickers(self, category: str = "linear", symbol: str | None = None) -> list[dict]:
        res = self._get("/v5/market/tickers", {"category": category, "symbol": symbol})
        return res.get("list", [])

    def klines(
        self,
        symbol: str,
        timeframe: str,
        category: str = "linear",
        limit: int = 300,
        start_ms: int | None = None,
        end_ms: int | None = None,
        drop_open_candle: bool = True,
        now_ms: int | None = None,
    ) -> pd.DataFrame:
        """OHLCV candles in ascending time order.

        The most recent candle returned by Bybit is still forming; analysing it
        would leak an incomplete bar into indicators, so by default it is dropped.
        """
        res = self._get(
            "/v5/market/kline",
            {
                "category": category,
                "symbol": symbol,
                "interval": INTERVAL_MAP[timeframe],
                "limit": min(limit, 1000),
                "start": start_ms,
                "end": end_ms,
            },
        )
        df = klines_to_frame(res.get("list", []))
        if drop_open_candle and not df.empty:
            now = now_ms if now_ms is not None else int(utcnow().timestamp() * 1000)
            tf_ms = TIMEFRAME_SECONDS[timeframe] * 1000
            closed = (df.index.as_unit("ms").asi8 + tf_ms) <= now
            df = df[closed]
        return df

    def klines_range(
        self, symbol: str, timeframe: str, start_ms: int, end_ms: int, category: str = "linear"
    ) -> pd.DataFrame:
        """Paginate klines over an arbitrary historical range (for backtests)."""
        frames = []
        tf_ms = TIMEFRAME_SECONDS[timeframe] * 1000
        cursor_end = end_ms
        while cursor_end > start_ms:
            df = self.klines(
                symbol, timeframe, category, limit=1000, start_ms=start_ms, end_ms=cursor_end,
                drop_open_candle=True,
            )
            if df.empty:
                break
            frames.append(df)
            first_ms = int(df.index[0].timestamp() * 1000)
            if first_ms <= start_ms:
                break
            cursor_end = first_ms - tf_ms
        if not frames:
            return klines_to_frame([])
        out = pd.concat(frames).sort_index()
        out = out[~out.index.duplicated(keep="last")]
        return out[(out.index >= pd.Timestamp(start_ms, unit="ms", tz="UTC"))]

    def orderbook(self, symbol: str, category: str = "linear", limit: int = 50) -> dict:
        res = self._get("/v5/market/orderbook", {"category": category, "symbol": symbol, "limit": limit})
        return {
            "symbol": res.get("s", symbol),
            "bids": [(float(p), float(q)) for p, q in res.get("b", [])],
            "asks": [(float(p), float(q)) for p, q in res.get("a", [])],
            "ts": int(res.get("ts", 0)),
        }

    def open_interest(self, symbol: str, interval: str = "1h", limit: int = 48) -> pd.Series:
        res = self._get(
            "/v5/market/open-interest",
            {"category": "linear", "symbol": symbol, "intervalTime": OI_INTERVALS[interval], "limit": limit},
        )
        rows = res.get("list", [])
        if not rows:
            return pd.Series(dtype=float, name="open_interest")
        idx = pd.to_datetime([int(r["timestamp"]) for r in rows], unit="ms", utc=True)
        s = pd.Series([float(r["openInterest"]) for r in rows], index=idx, name="open_interest")
        return s.sort_index()

    def funding_history(
        self, symbol: str, limit: int = 200, start_ms: int | None = None, end_ms: int | None = None
    ) -> pd.Series:
        res = self._get(
            "/v5/market/funding/history",
            {"category": "linear", "symbol": symbol, "limit": limit, "startTime": start_ms, "endTime": end_ms},
        )
        rows = res.get("list", [])
        if not rows:
            return pd.Series(dtype=float, name="funding_rate")
        idx = pd.to_datetime([int(r["fundingRateTimestamp"]) for r in rows], unit="ms", utc=True)
        return pd.Series([float(r["fundingRate"]) for r in rows], index=idx, name="funding_rate").sort_index()

    def long_short_ratio(self, symbol: str, period: str = "1h", limit: int = 48) -> pd.DataFrame:
        res = self._get(
            "/v5/market/account-ratio",
            {"category": "linear", "symbol": symbol, "period": period, "limit": limit},
        )
        rows = res.get("list", [])
        if not rows:
            return pd.DataFrame(columns=["buy_ratio", "sell_ratio"])
        idx = pd.to_datetime([int(r["timestamp"]) for r in rows], unit="ms", utc=True)
        df = pd.DataFrame(
            {"buy_ratio": [float(r["buyRatio"]) for r in rows], "sell_ratio": [float(r["sellRatio"]) for r in rows]},
            index=idx,
        )
        return df.sort_index()

    def recent_trades(self, symbol: str, category: str = "linear", limit: int = 1000) -> pd.DataFrame:
        res = self._get("/v5/market/recent-trade", {"category": category, "symbol": symbol, "limit": limit})
        rows = res.get("list", [])
        if not rows:
            return pd.DataFrame(columns=["price", "size", "side"])
        idx = pd.to_datetime([int(r["time"]) for r in rows], unit="ms", utc=True)
        return pd.DataFrame(
            {
                "price": [float(r["price"]) for r in rows],
                "size": [float(r["size"]) for r in rows],
                "side": [r["side"] for r in rows],
            },
            index=idx,
        ).sort_index()


def klines_to_frame(rows: list[list]) -> pd.DataFrame:
    cols = ["open", "high", "low", "close", "volume", "turnover"]
    if not rows:
        return pd.DataFrame(columns=cols, index=pd.DatetimeIndex([], tz="UTC", name="ts"), dtype=float)
    arr = np.array(rows, dtype=float)
    idx = pd.to_datetime(arr[:, 0].astype("int64"), unit="ms", utc=True)
    df = pd.DataFrame(arr[:, 1:7], index=idx, columns=cols)
    df.index.name = "ts"
    df = df.sort_index()
    return df[~df.index.duplicated(keep="last")]


def parse_ticker(t: dict) -> dict:
    """Normalise a Bybit ticker dict into floats; missing values become NaN."""

    def f(key: str) -> float:
        v = t.get(key)
        try:
            return float(v) if v not in (None, "") else float("nan")
        except (TypeError, ValueError):
            return float("nan")

    bid, ask = f("bid1Price"), f("ask1Price")
    mid = (bid + ask) / 2 if bid > 0 and ask > 0 else float("nan")
    spread_bps = (ask - bid) / mid * 1e4 if mid == mid and mid > 0 else float("nan")
    return {
        "symbol": t.get("symbol"),
        "last_price": f("lastPrice"),
        "mark_price": f("markPrice"),
        "index_price": f("indexPrice"),
        "change_24h_pct": f("price24hPcnt") * 100,
        "high_24h": f("highPrice24h"),
        "low_24h": f("lowPrice24h"),
        "turnover_24h": f("turnover24h"),
        "volume_24h": f("volume24h"),
        "open_interest": f("openInterest"),
        "open_interest_value": f("openInterestValue"),
        "funding_rate": f("fundingRate"),
        "next_funding_ms": int(t["nextFundingTime"]) if t.get("nextFundingTime") else None,
        "bid": bid,
        "ask": ask,
        "spread_bps": spread_bps,
    }
