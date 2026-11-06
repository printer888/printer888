"""Solana websocket ``logsSubscribe`` listener with automatic reconnection.

The websocket only tells us *that* the wallet was mentioned in a transaction;
the transaction itself is always re-fetched via RPC and parsed from validator
balance data. Polling (``getSignaturesForAddress``) runs alongside as a
fallback, so a dropped socket can delay but not lose events.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable

log = logging.getLogger(__name__)


async def logs_subscribe_loop(ws_url: str, wallet: str, on_signature: Callable[[str], Awaitable[None]],
                              stop: asyncio.Event, on_status: Callable[[str], None] | None = None) -> None:
    import websockets  # imported lazily so tests don't need a socket

    backoff = 1.0
    while not stop.is_set():
        try:
            async with websockets.connect(ws_url, ping_interval=20, ping_timeout=20, max_size=2**22) as ws:
                await ws.send(json.dumps({
                    "jsonrpc": "2.0", "id": 1, "method": "logsSubscribe",
                    "params": [{"mentions": [wallet]}, {"commitment": "confirmed"}],
                }))
                if on_status:
                    on_status("connected")
                backoff = 1.0
                while not stop.is_set():
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=60)
                    except asyncio.TimeoutError:
                        continue
                    msg = json.loads(raw)
                    val = (((msg.get("params") or {}).get("result") or {}).get("value") or {})
                    sig = val.get("signature")
                    if sig:
                        await on_signature(sig)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - any socket failure => reconnect
            if on_status:
                on_status(f"reconnecting: {e.__class__.__name__}")
            log.warning("websocket error (%s); reconnecting in %.0fs", e, backoff)
            try:
                await asyncio.wait_for(stop.wait(), timeout=backoff)
            except asyncio.TimeoutError:
                pass
            backoff = min(backoff * 2, 60)
