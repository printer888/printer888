"""In-process pub/sub used to push live updates to dashboard websockets."""
from __future__ import annotations

import asyncio
from typing import Any


class EventBus:
    def __init__(self) -> None:
        self._subs: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)

    def publish(self, topic: str, data: Any = None) -> None:
        msg = {"topic": topic, "data": data}
        for q in list(self._subs):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                pass  # slow client; it will resync from REST on next refresh
