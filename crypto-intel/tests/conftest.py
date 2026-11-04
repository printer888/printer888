"""Shared fixtures.

All market data in tests is SYNTHETIC and generated here; it is used only to verify
the code's mechanics and is never presented as real market information.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import httpx
import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("CI_NO_APP", "1")

from cryptointel.data.bybit_client import BybitClient  # noqa: E402

TF_MS = {"1": 60_000, "5": 300_000, "15": 900_000, "60": 3_600_000, "240": 14_400_000,
         "D": 86_400_000, "W": 604_800_000}


def synth_ohlcv(n: int = 600, seed: int = 0, drift: float = 0.0005, vol: float = 0.01, freq: str = "h",
                start: str = "2025-01-01", base: float = 100.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    c = base * np.exp(np.cumsum(rng.normal(drift, vol, n)))
    o = np.r_[base, c[:-1]]
    h = np.maximum(o, c) * (1 + rng.uniform(0, 0.004, n))
    l = np.minimum(o, c) * (1 - rng.uniform(0, 0.004, n))
    idx = pd.date_range(start, periods=n, freq=freq, tz="UTC")
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": rng.uniform(100, 300, n)}, index=idx)


@pytest.fixture
def synth():
    return synth_ohlcv


class FakeBybit:
    """httpx MockTransport emulating the Bybit v5 public endpoints used by the app."""

    def __init__(self, symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "SHITUSDT"), drift=0.0006):
        self.symbols = symbols
        self.drift = drift
        self.now_ms = int(time.time() * 1000)
        self.calls: list[str] = []

    def _price(self, sym: str) -> float:
        return {"BTCUSDT": 60000, "ETHUSDT": 3000, "SOLUSDT": 150, "BNBUSDT": 600, "XRPUSDT": 0.6}.get(sym, 1.0)

    def handler(self, request: httpx.Request) -> httpx.Response:
        p = dict(request.url.params)
        path = request.url.path
        self.calls.append(path)
        ok = lambda result: httpx.Response(200, json={"retCode": 0, "retMsg": "OK", "result": result})
        if path == "/v5/market/instruments-info":
            return ok({"list": [{"symbol": s, "contractType": "LinearPerpetual", "status": "Trading",
                                 "baseCoin": s[:-4], "quoteCoin": "USDT", "launchTime": str(self.now_ms - 400 * 86_400_000),
                                 "fundingInterval": 480, "priceFilter": {"tickSize": "0.01"}} for s in self.symbols],
                       "nextPageCursor": ""})
        if path == "/v5/market/tickers":
            out = []
            for s in self.symbols:
                px = self._price(s)
                illiquid = s == "SHITUSDT"
                out.append({"symbol": s, "lastPrice": str(px), "markPrice": str(px), "indexPrice": str(px),
                            "price24hPcnt": "0.012", "highPrice24h": str(px * 1.02), "lowPrice24h": str(px * 0.98),
                            "turnover24h": "1000" if illiquid else "900000000", "volume24h": "1",
                            "openInterest": "1", "openInterestValue": "100" if illiquid else "500000000",
                            "fundingRate": "0.0001", "nextFundingTime": str(self.now_ms + 3_600_000),
                            "bid1Price": str(px * 0.99999), "ask1Price": str(px * 1.00001)})
            return ok({"category": "linear", "list": out})
        if path == "/v5/market/kline":
            sym, iv, limit = p["symbol"], p["interval"], int(p.get("limit", 200))
            step = TF_MS[iv]
            seed = abs(hash((sym, iv))) % 10_000
            n = limit
            df = synth_ohlcv(n, seed=seed, drift=self.drift, vol=0.006, base=self._price(sym) / 1.4)
            last_open = (self.now_ms // step) * step  # current (still-open) candle
            starts = [last_open - (n - 1 - i) * step for i in range(n)]
            rows = [[str(t), str(r.open), str(r.high), str(r.low), str(r.close), str(r.volume), str(r.volume * r.close)]
                    for t, r in zip(starts, df.itertuples())]
            return ok({"symbol": sym, "category": "linear", "list": rows[::-1]})  # Bybit returns newest first
        if path == "/v5/market/funding/history":
            rows = [{"symbol": p["symbol"], "fundingRate": "0.0001",
                     "fundingRateTimestamp": str(self.now_ms - i * 8 * 3_600_000)} for i in range(60)]
            return ok({"list": rows})
        if path == "/v5/market/open-interest":
            rows = [{"openInterest": str(1000 * (1 + 0.004 * (48 - i))), "timestamp": str(self.now_ms - i * 3_600_000)}
                    for i in range(48)]
            return ok({"list": rows})
        if path == "/v5/market/account-ratio":
            rows = [{"symbol": p["symbol"], "buyRatio": "0.55", "sellRatio": "0.45",
                     "timestamp": str(self.now_ms - i * 3_600_000)} for i in range(24)]
            return ok({"list": rows})
        if path == "/v5/market/orderbook":
            px = self._price(p["symbol"])
            bids = [[str(px * (1 - 0.0002 * i)), "50"] for i in range(1, 51)]
            asks = [[str(px * (1 + 0.0002 * i)), "40"] for i in range(1, 51)]
            return ok({"s": p["symbol"], "b": bids, "a": asks, "ts": self.now_ms})
        if path == "/v5/market/recent-trade":
            return ok({"list": []})
        return httpx.Response(404, json={"retCode": 10001, "retMsg": "not mocked"})


@pytest.fixture
def fake_bybit():
    fb = FakeBybit()
    client = BybitClient(transport=httpx.MockTransport(fb.handler), max_requests_per_second=0)
    yield fb, client
    client.close()


def dump(obj) -> str:
    return json.dumps(obj, default=str)
