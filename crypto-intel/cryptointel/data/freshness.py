"""Timestamped values: every external datum carries its source and observation time."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Generic, TypeVar

T = TypeVar("T")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ms_to_dt(ms: int | float | str) -> datetime:
    return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc)


def humanize_age(seconds: float) -> str:
    if seconds < 0:
        return "in the future"
    if seconds < 90:
        return f"{int(seconds)}s"
    if seconds < 5400:
        return f"{int(seconds // 60)}m"
    if seconds < 172800:
        return f"{seconds / 3600:.1f}h"
    return f"{seconds / 86400:.1f}d"


@dataclass
class Stamped(Generic[T]):
    value: T
    source: str
    as_of: datetime
    note: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def age_seconds(self, now: datetime | None = None) -> float:
        return ((now or utcnow()) - self.as_of).total_seconds()

    def is_stale(self, max_age_seconds: float, now: datetime | None = None) -> bool:
        return self.age_seconds(now) > max_age_seconds

    def describe_age(self, now: datetime | None = None) -> str:
        return humanize_age(self.age_seconds(now))

    def to_dict(self) -> dict:
        return {
            "value": self.value,
            "source": self.source,
            "as_of": self.as_of.isoformat(),
            "age": self.describe_age(),
            "note": self.note,
        }


# Maximum acceptable age for data used in a signal, per timeframe (seconds).
# A candle series is stale when its last *closed* candle is older than ~2 bars.
TIMEFRAME_SECONDS = {
    "1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400, "1w": 604800,
}


def max_candle_age(tf: str) -> float:
    return TIMEFRAME_SECONDS[tf] * 2.5
