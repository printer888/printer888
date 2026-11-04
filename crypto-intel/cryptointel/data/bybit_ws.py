"""Bybit v5 public WebSocket client.

Streams used (all public):
  tickers.{SYMBOL}        — last price / funding / OI updates
  publicTrade.{SYMBOL}    — individual trades with aggressor side → volume delta
  allLiquidation.{SYMBOL} — liquidation events (linear)
  orderbook.50.{SYMBOL}   — optional depth snapshots/deltas

Bybit requires a ping at least every 20 seconds; this client sends one every 18s,
reconnects with exponential backoff and re-subscribes.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Awaitable, Callable

from .freshness import utcnow

log = logging.getLogger(__name__)

Handler = Callable[[str, dict], Awaitable[None] | None]


@dataclass
class LiquidationEvent:
    ts_ms: int
    symbol: str
    side: str  # "Buy" = a short position was liquidated, "Sell" = a long was liquidated
    size: float
    price: float

    @property
    def notional(self) -> float:
        return self.size * self.price


class LiquidationTracker:
    """Rolling window of liquidations per symbol."""

    def __init__(self, window_seconds: int = 3600 * 24):
        self.window_ms = window_seconds * 1000
        self.events: dict[str, deque[LiquidationEvent]] = defaultdict(deque)
        self.started_ms = int(utcnow().timestamp() * 1000)

    def add(self, ev: LiquidationEvent) -> None:
        q = self.events[ev.symbol]
        q.append(ev)
        cutoff = ev.ts_ms - self.window_ms
        while q and q[0].ts_ms < cutoff:
            q.popleft()

    def summary(self, symbol: str, lookback_seconds: int = 3600) -> dict:
        now_ms = int(utcnow().timestamp() * 1000)
        cutoff = now_ms - lookback_seconds * 1000
        covered = (now_ms - self.started_ms) / 1000
        long_liq = sum(e.notional for e in self.events.get(symbol, ()) if e.ts_ms >= cutoff and e.side == "Sell")
        short_liq = sum(e.notional for e in self.events.get(symbol, ()) if e.ts_ms >= cutoff and e.side == "Buy")
        return {
            "long_liquidations_usd": long_liq,
            "short_liquidations_usd": short_liq,
            "lookback_seconds": lookback_seconds,
            # Only "complete" if the stream has been running for the full lookback.
            "complete": covered >= lookback_seconds,
            "observed_seconds": covered,
        }


class TradeFlowTracker:
    """Aggressor-side volume delta from the public trade stream (reliable data only)."""

    def __init__(self, window_seconds: int = 3600):
        self.window_ms = window_seconds * 1000
        self.trades: dict[str, deque[tuple[int, float, float]]] = defaultdict(deque)
        self.started_ms = int(utcnow().timestamp() * 1000)

    def add(self, symbol: str, ts_ms: int, side: str, size: float, price: float) -> None:
        signed = size * price * (1 if side == "Buy" else -1)
        q = self.trades[symbol]
        q.append((ts_ms, signed, abs(signed)))
        cutoff = ts_ms - self.window_ms
        while q and q[0][0] < cutoff:
            q.popleft()

    def delta(self, symbol: str, lookback_seconds: int = 900) -> dict:
        now_ms = int(utcnow().timestamp() * 1000)
        cutoff = now_ms - lookback_seconds * 1000
        rows = [t for t in self.trades.get(symbol, ()) if t[0] >= cutoff]
        total = sum(t[2] for t in rows)
        net = sum(t[1] for t in rows)
        return {
            "net_delta_usd": net,
            "total_usd": total,
            "delta_ratio": net / total if total else None,
            "n_trades": len(rows),
            "complete": (now_ms - self.started_ms) / 1000 >= lookback_seconds,
        }


class BybitPublicWS:
    def __init__(self, url: str, topics: list[str]):
        self.url = url
        self.topics = topics
        self.handlers: list[Handler] = []
        self.liquidations = LiquidationTracker()
        self.trade_flow = TradeFlowTracker()
        self.last_ticker: dict[str, dict] = {}
        self.last_message_at = None
        self._stop = asyncio.Event()

    def add_handler(self, handler: Handler) -> None:
        self.handlers.append(handler)

    def stop(self) -> None:
        self._stop.set()

    async def run_forever(self) -> None:
        import websockets  # imported lazily so the rest of the package works without it

        backoff = 1.0
        while not self._stop.is_set():
            try:
                async with websockets.connect(self.url, ping_interval=None, open_timeout=15) as ws:
                    log.info("WebSocket connected: %s (%d topics)", self.url, len(self.topics))
                    # Bybit allows up to 10 args per subscribe request.
                    for i in range(0, len(self.topics), 10):
                        await ws.send(json.dumps({"op": "subscribe", "args": self.topics[i : i + 10]}))
                    backoff = 1.0
                    pinger = asyncio.create_task(self._ping(ws))
                    try:
                        async for raw in ws:
                            await self._on_message(raw)
                            if self._stop.is_set():
                                break
                    finally:
                        pinger.cancel()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # network errors → reconnect
                log.warning("WebSocket error (%s); reconnecting in %.0fs", e, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    async def _ping(self, ws) -> None:
        while True:
            await asyncio.sleep(18)
            await ws.send(json.dumps({"op": "ping"}))

    async def _on_message(self, raw: str | bytes) -> None:
        try:
            msg = json.loads(raw)
        except ValueError:
            return
        topic = msg.get("topic")
        if not topic:
            if msg.get("op") == "subscribe" and not msg.get("success", True):
                log.error("Subscription failed: %s", msg.get("ret_msg"))
            return
        self.last_message_at = utcnow()
        self.process(topic, msg)
        for h in self.handlers:
            res = h(topic, msg)
            if asyncio.iscoroutine(res):
                await res

    def process(self, topic: str, msg: dict) -> None:
        """Update in-memory state from a message (sync; unit-testable)."""
        data = msg.get("data")
        if topic.startswith("allLiquidation.") or topic.startswith("liquidation."):
            items = data if isinstance(data, list) else [data]
            for d in items:
                try:
                    self.liquidations.add(
                        LiquidationEvent(
                            ts_ms=int(d.get("T") or d.get("updatedTime") or msg.get("ts")),
                            symbol=d.get("s") or d.get("symbol"),
                            side=d.get("S") or d.get("side"),
                            size=float(d.get("v") or d.get("size")),
                            price=float(d.get("p") or d.get("price")),
                        )
                    )
                except (TypeError, ValueError):
                    continue
        elif topic.startswith("publicTrade."):
            for t in data or []:
                try:
                    self.trade_flow.add(t["s"], int(t["T"]), t["S"], float(t["v"]), float(t["p"]))
                except (KeyError, TypeError, ValueError):
                    continue
        elif topic.startswith("tickers."):
            sym = topic.split(".", 1)[1]
            # Delta messages only contain changed fields: merge.
            cur = self.last_ticker.get(sym, {})
            cur.update({k: v for k, v in (data or {}).items() if v not in (None, "")})
            cur["_ts"] = msg.get("ts")
            self.last_ticker[sym] = cur


def build_topics(symbols: list[str], with_trades: bool = True, with_liquidations: bool = True) -> list[str]:
    topics = []
    for s in symbols:
        topics.append(f"tickers.{s}")
        if with_trades:
            topics.append(f"publicTrade.{s}")
        if with_liquidations:
            topics.append(f"allLiquidation.{s}")
    return topics
