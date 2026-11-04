from __future__ import annotations

import logging
import re

_SECRET_PATTERNS = [
    re.compile(r"(bot)(\d+:[A-Za-z0-9_-]{20,})"),  # telegram bot token in URLs
    re.compile(r"(api_key=)[^&\s]+"),
    re.compile(r"(X-BAPI-API-KEY['\"]?:\s*['\"]?)[^'\"\s]+"),
]


class RedactingFilter(logging.Filter):
    """Ensures credentials never reach log output."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        redacted = msg
        for pat in _SECRET_PATTERNS:
            redacted = pat.sub(r"\1***", redacted)
        if redacted != msg:
            record.msg = redacted
            record.args = ()
        return True


def setup_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    if getattr(root, "_cryptointel_configured", False):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%Y-%m-%dT%H:%M:%S")
    )
    handler.addFilter(RedactingFilter())
    root.addHandler(handler)
    root.setLevel(level.upper())
    # httpx logs full URLs at INFO; keep it quiet.
    for name in ("httpx", "httpx2", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
    root._cryptointel_configured = True  # type: ignore[attr-defined]
