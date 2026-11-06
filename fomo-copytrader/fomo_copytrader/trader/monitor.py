"""Real-time trader monitor: websocket push + polling fallback, at-least-once delivery.

Delivery guarantees:
* Websocket ``logsSubscribe`` gives low latency.
* ``getSignaturesForAddress(until=cursor)`` polling catches anything the socket
  missed (disconnects, provider hiccups, restarts). The cursor is persisted.
* Each signature is fetched with ``getTransaction`` (commitment=confirmed) and
  parsed from validator balance data. Duplicates are discarded both here and
  by the DB unique constraint in the copy engine.
* Solana has no "cancelled" state: a transaction that is dropped or expires
  never lands and so never produces an event. Landed-but-failed transactions
  are recorded as FAILED.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from ..chain.parser import parse_transaction
from ..chain.rpc import SolanaRpc
from ..chain.ws import logs_subscribe_loop
from ..models import Trader
from ..schemas import SwapEvent

log = logging.getLogger(__name__)


class TraderMonitor:
    def __init__(self, rpc: SolanaRpc, sm: async_sessionmaker, on_event: Callable[[SwapEvent], Awaitable[object]],
                 ws_url: str | None = None, poll_interval: float = 4.0, coordinator=None):
        self.rpc = rpc
        self.sm = sm
        self.on_event = on_event
        self.ws_url = ws_url
        self.poll_interval = poll_interval
        self.wallet: str | None = None
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._lock = asyncio.Lock()
        self._stop = asyncio.Event()
        self._tasks: list[asyncio.Task] = []
        self.last_poll_ok: float | None = None
        self.ws_status = "disabled" if not ws_url else "idle"
        self.errors = 0
        self.coord = coordinator

    @property
    def running(self) -> bool:
        return any(not t.done() for t in self._tasks)

    def _mark_seen(self, sig: str) -> bool:
        if sig in self._seen:
            return False
        self._seen[sig] = None
        while len(self._seen) > 5000:
            self._seen.popitem(last=False)
        return True

    async def start(self, wallet: str) -> None:
        await self.stop()
        self.wallet = wallet
        self._stop = asyncio.Event()
        await self._init_cursor()
        self._tasks = [asyncio.create_task(self._poll_loop(), name="trader-poll")]
        if self.ws_url:
            self._tasks.append(asyncio.create_task(logs_subscribe_loop(
                self.ws_url, wallet, self._on_ws_signature, self._stop, self._set_ws_status), name="trader-ws"))
        log.info("monitoring trader %s", wallet)

    async def stop(self) -> None:
        self._stop.set()
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._tasks = []

    def _set_ws_status(self, s: str) -> None:
        self.ws_status = s

    async def _cursor(self) -> str | None:
        async with self.sm() as s:
            t = (await s.execute(select(Trader).where(Trader.wallet == self.wallet))).scalar_one_or_none()
            return t.last_signature if t else None

    async def _save_cursor(self, sig: str) -> None:
        async with self.sm() as s:
            t = (await s.execute(select(Trader).where(Trader.wallet == self.wallet))).scalar_one_or_none()
            if t:
                t.last_signature = sig
                await s.commit()

    async def _init_cursor(self) -> None:
        """On first start only look forward: history is for analytics, not copying."""
        if await self._cursor():
            return
        latest = await self.rpc.get_signatures_for_address(self.wallet, limit=1)
        if latest:
            await self._save_cursor(latest[0]["signature"])
            self._mark_seen(latest[0]["signature"])

    async def _on_ws_signature(self, sig: str) -> None:
        await self.process_signature(sig)

    async def process_signature(self, sig: str, retries: int = 6) -> list[SwapEvent]:
        async with self._lock:
            if not self._mark_seen(sig):
                return []
        if self.coord is not None and not await self.coord.first_seen(sig):
            return []
        tx = None
        for i in range(retries):  # tx may not be queryable for a moment after notification
            tx = await self.rpc.get_transaction(sig)
            if tx:
                break
            await asyncio.sleep(min(0.5 * 2 ** i, 5))
        if not tx:
            async with self._lock:
                self._seen.pop(sig, None)  # let polling pick it up later
            if self.coord is not None:
                await self.coord.forget(sig)
            log.warning("transaction %s not yet available", sig)
            return []
        events = parse_transaction(tx, self.wallet)
        for ev in events:
            try:
                await self.on_event(ev)
            except Exception:  # noqa: BLE001
                self.errors += 1
                log.exception("event handler failed for %s", sig)
        return events

    async def poll_once(self) -> int:
        cursor = await self._cursor()
        new: list[dict] = []
        before = None
        while True:  # page back until we reach the cursor
            page = await self.rpc.get_signatures_for_address(self.wallet, limit=100, until=cursor, before=before)
            new.extend(page)
            if len(page) < 100 or not cursor:
                break
            before = page[-1]["signature"]
        count = 0
        for item in reversed(new):  # oldest first
            await self.process_signature(item["signature"])
            await self._save_cursor(item["signature"])
            count += 1
        self.last_poll_ok = time.time()
        return count

    async def _poll_loop(self) -> None:
        backoff = self.poll_interval
        while not self._stop.is_set():
            try:
                await self.poll_once()
                backoff = self.poll_interval
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                self.errors += 1
                log.warning("poll failed: %s", e)
                backoff = min(backoff * 2, 60)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=backoff)
            except asyncio.TimeoutError:
                pass


async def fetch_history(rpc: SolanaRpc, wallet: str, max_tx: int = 300, concurrency: int = 4) -> list[SwapEvent]:
    """Backfill recent history for analytics (read-only)."""
    sigs: list[dict] = []
    before = None
    while len(sigs) < max_tx:
        page = await rpc.get_signatures_for_address(wallet, limit=min(100, max_tx - len(sigs)), before=before)
        if not page:
            break
        sigs.extend(page)
        before = page[-1]["signature"]
        if len(page) < 100:
            break
    sem = asyncio.Semaphore(concurrency)

    async def one(sig: str) -> list[SwapEvent]:
        async with sem:
            try:
                tx = await rpc.get_transaction(sig)
            except Exception as e:  # noqa: BLE001
                log.info("history fetch failed for %s: %s", sig, e)
                return []
            return parse_transaction(tx, wallet) if tx else []

    results = await asyncio.gather(*(one(s["signature"]) for s in sigs))
    events = [e for r in results for e in r]
    events.sort(key=lambda e: (e.slot, e.signature))
    return events
