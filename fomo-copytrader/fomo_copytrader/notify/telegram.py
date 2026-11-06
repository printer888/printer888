"""Telegram Bot API notifications (https://core.telegram.org/bots/api#sendmessage).

All message bodies are built from recorded transaction data. Nothing is sent
when the bot token / chat id are not configured.
"""
from __future__ import annotations

import asyncio
import html
import logging

import httpx

log = logging.getLogger(__name__)


def short(addr: str | None) -> str:
    if not addr:
        return "?"
    return addr if len(addr) <= 12 else f"{addr[:4]}…{addr[-4:]}"


def fmt_price(p: float | None) -> str:
    if p is None:
        return "n/a"
    if p >= 1:
        return f"${p:,.4f}"
    return f"${p:.10f}".rstrip("0")


def fmt_usd(v: float | None, signed: bool = False) -> str:
    if v is None:
        return "n/a"
    return f"{'+' if signed and v >= 0 else ''}{'-' if v < 0 else ''}${abs(v):,.2f}"


class Notifier:
    def __init__(self, bot_token: str | None, chat_id: str | None, client: httpx.AsyncClient | None = None):
        self.enabled = bool(bot_token and chat_id)
        self._url = f"https://api.telegram.org/bot{bot_token}/sendMessage" if bot_token else None
        self.chat_id = chat_id
        self._client = client or httpx.AsyncClient(timeout=10)
        self.sent: list[str] = []  # last messages, shown on the dashboard

    async def send(self, title: str, lines: list[tuple[str, str]] | None = None, footer: str | None = None) -> None:
        body = f"<b>{html.escape(title)}</b>\n\n"
        body += "\n".join(f"{html.escape(k)}: {html.escape(str(v))}" for k, v in (lines or []))
        if footer:
            body += f"\n\n<i>{html.escape(footer)}</i>"
        self.sent.append(body)
        self.sent = self.sent[-50:]
        if not self.enabled:
            return
        for attempt in range(3):
            try:
                r = await self._client.post(self._url, json={
                    "chat_id": self.chat_id, "text": body, "parse_mode": "HTML",
                    "disable_web_page_preview": True})
                if r.status_code == 429:
                    wait = (r.json().get("parameters") or {}).get("retry_after", 2)
                    await asyncio.sleep(min(float(wait), 30))
                    continue
                r.raise_for_status()
                return
            except Exception as e:  # noqa: BLE001 - notifications must never crash trading
                log.warning("telegram send failed (attempt %d): %s", attempt + 1, e)
                await asyncio.sleep(1 + attempt)
