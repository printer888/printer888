"""Redis-backed coordination (optional; falls back to in-process when REDIS_URL is unset).

* Leader lock: only one process may monitor and trade. If a second replica is
  started by mistake (deploy overlap, scaling), it stays on standby instead of
  doubling every order.
* Signature dedupe: a shared fast-path cache in front of the DB unique keys.
"""
from __future__ import annotations

import logging
import os
import socket
import uuid

log = logging.getLogger(__name__)

LEADER_KEY = "copytrader:leader"
_RENEW = """
if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('pexpire', KEYS[1], ARGV[2]) else return 0 end
"""


class Coordinator:
    def __init__(self, redis_url: str | None, ttl_ms: int = 30_000):
        self.ttl_ms = ttl_ms
        self.ident = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"
        self.redis = None
        if redis_url:
            import redis.asyncio as aioredis

            self.redis = aioredis.from_url(redis_url, decode_responses=True)
        self.is_leader = self.redis is None  # no redis => single process assumed

    async def acquire_or_renew(self) -> bool:
        if self.redis is None:
            return True
        try:
            if self.is_leader:
                ok = await self.redis.eval(_RENEW, 1, LEADER_KEY, self.ident, self.ttl_ms)
                self.is_leader = bool(ok)
            if not self.is_leader:
                self.is_leader = bool(await self.redis.set(LEADER_KEY, self.ident, nx=True, px=self.ttl_ms))
        except Exception as e:  # noqa: BLE001 - losing redis => stop trading rather than risk duplicates
            log.warning("leader lock check failed: %s", e)
            self.is_leader = False
        return self.is_leader

    async def first_seen(self, signature: str) -> bool:
        if self.redis is None:
            return True
        try:
            return bool(await self.redis.set(f"copytrader:sig:{signature}", "1", nx=True, ex=7 * 86400))
        except Exception:  # noqa: BLE001 - DB constraint remains the source of truth
            return True

    async def forget(self, signature: str) -> None:
        if self.redis is not None:
            try:
                await self.redis.delete(f"copytrader:sig:{signature}")
            except Exception:  # noqa: BLE001
                pass

    async def close(self) -> None:
        if self.redis is not None:
            try:
                if self.is_leader:
                    await self.redis.eval("if redis.call('get',KEYS[1])==ARGV[1] then return redis.call('del',KEYS[1]) end",
                                          1, LEADER_KEY, self.ident)
                await self.redis.aclose()
            except Exception:  # noqa: BLE001
                pass
