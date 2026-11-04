"""Telegram Bot API delivery (sendMessage). Token comes from the environment only."""
from __future__ import annotations

import html
import logging

import httpx

log = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str, client: httpx.Client | None = None):
        self.token, self.chat_id = token, chat_id
        self.client = client

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    def send(self, text_html: str) -> bool:
        if not self.enabled:
            log.info("Telegram disabled; alert logged only:\n%s", text_html)
            return False
        own = self.client is None
        client = self.client or httpx.Client(timeout=10)
        try:
            r = client.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                json={"chat_id": self.chat_id, "text": text_html[:4000], "parse_mode": "HTML",
                      "disable_web_page_preview": True},
            )
            ok = r.status_code == 200 and r.json().get("ok", False)
            if not ok:
                log.warning("Telegram send failed: HTTP %s", r.status_code)
            return ok
        except Exception as e:
            log.warning("Telegram send error: %s", type(e).__name__)
            return False
        finally:
            if own:
                client.close()


def esc(s: object) -> str:
    return html.escape(str(s), quote=False)
