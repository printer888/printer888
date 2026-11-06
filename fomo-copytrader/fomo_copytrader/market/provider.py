"""Market data facade with short TTL caching.

``MarketData`` is the interface the engine depends on; tests substitute a
fake implementation, and production uses ``LiveMarketData``.
"""
from __future__ import annotations

import logging
import time
from typing import Protocol

from ..constants import STABLE_MINTS, WSOL_MINT
from ..schemas import Quote, TokenMarket
from .dexscreener import DexScreener
from .jupiter import Jupiter

log = logging.getLogger(__name__)


class MarketData(Protocol):
    async def token_market(self, mint: str) -> TokenMarket | None: ...
    async def price_usd(self, mint: str) -> float | None: ...
    async def quote(self, input_mint: str, output_mint: str, amount_raw: int, slippage_bps: int) -> Quote | None: ...


class LiveMarketData:
    def __init__(self, dex: DexScreener, jup: Jupiter, ttl_sec: float = 5.0):
        self.dex = dex
        self.jup = jup
        self.ttl = ttl_sec
        self._cache: dict[tuple, tuple[float, object]] = {}

    def _get(self, key):
        hit = self._cache.get(key)
        if hit and time.monotonic() - hit[0] < self.ttl:
            return hit[1]
        return None

    def _put(self, key, val):
        self._cache[key] = (time.monotonic(), val)
        return val

    async def token_market(self, mint: str) -> TokenMarket | None:
        key = ("m", mint)
        if (c := self._get(key)) is not None:
            return c
        try:
            return self._put(key, await self.dex.token_market(mint))
        except Exception as e:  # noqa: BLE001
            log.warning("dexscreener failed for %s: %s", mint, e)
            return None

    async def price_usd(self, mint: str) -> float | None:
        if mint in STABLE_MINTS:
            return 1.0
        key = ("p", mint)
        if (c := self._get(key)) is not None:
            return c
        try:
            p = (await self.jup.prices_usd([mint])).get(mint)
        except Exception as e:  # noqa: BLE001
            log.warning("jupiter price failed for %s: %s", mint, e)
            p = None
        if p is None and mint != WSOL_MINT:
            m = await self.token_market(mint)
            p = m.price_usd if m else None
        if p is not None:
            self._put(key, p)
        return p

    async def quote(self, input_mint, output_mint, amount_raw, slippage_bps) -> Quote | None:
        try:
            return await self.jup.quote(input_mint, output_mint, amount_raw, slippage_bps)
        except Exception as e:  # noqa: BLE001
            log.warning("jupiter quote failed %s->%s: %s", input_mint, output_mint, e)
            return None
