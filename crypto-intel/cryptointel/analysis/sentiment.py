"""Market sentiment: Fear & Greed index and sentiment-vs-price divergences."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import httpx
import pandas as pd

from ..data.freshness import Stamped, utcnow

log = logging.getLogger(__name__)

FNG_URL = "https://api.alternative.me/fng/"


def fetch_fear_greed(limit: int = 30, client: httpx.Client | None = None) -> Stamped[list[dict]] | None:
    """Fetch Fear & Greed history (alternative.me). Returns None on failure — never a guess."""
    own = client is None
    client = client or httpx.Client(timeout=10)
    try:
        r = client.get(FNG_URL, params={"limit": limit, "format": "json"})
        r.raise_for_status()
        data = r.json().get("data", [])
        rows = [
            {"value": int(d["value"]), "label": d["value_classification"],
             "ts": pd.Timestamp(int(d["timestamp"]), unit="s", tz="UTC")}
            for d in data
        ]
        rows.sort(key=lambda x: x["ts"])
        if not rows:
            return None
        return Stamped(rows, "alternative.me Fear & Greed Index", rows[-1]["ts"].to_pydatetime(),
                       note="daily composite index; updates once per day")
    except Exception as e:
        log.warning("Fear & Greed fetch failed: %s", e)
        return None
    finally:
        if own:
            client.close()


@dataclass
class SentimentReport:
    fear_greed: int | None = None
    fear_greed_label: str | None = None
    fear_greed_change_7d: int | None = None
    as_of: str | None = None
    age: str | None = None
    divergences: list[str] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def analyze_sentiment(
    fng: Stamped[list[dict]] | None,
    btc_daily: pd.DataFrame | None,
    oi_change_24h_pct: float | None = None,
    price_change_24h_pct: float | None = None,
) -> SentimentReport:
    rep = SentimentReport()
    if fng and fng.value:
        if fng.is_stale(2 * 86400):
            rep.observations.append(f"Fear & Greed data is {fng.describe_age()} old — ignored as stale")
        else:
            cur = fng.value[-1]
            rep.fear_greed, rep.fear_greed_label = cur["value"], cur["label"]
            rep.as_of, rep.age = fng.as_of.isoformat(), fng.describe_age()
            if len(fng.value) >= 8:
                rep.fear_greed_change_7d = cur["value"] - fng.value[-8]["value"]
    if rep.fear_greed is not None and btc_daily is not None and len(btc_daily) >= 15:
        c, v = btc_daily["close"], btc_daily["volume"]
        ret7 = float((c.iloc[-1] / c.iloc[-8] - 1) * 100)
        if rep.fear_greed >= 70 and ret7 < -2:
            rep.divergences.append(
                f"Greed ({rep.fear_greed}) while BTC fell {ret7:.1f}% over 7d — optimism not confirmed by price; "
                "may indicate distribution or late buyers (observation, not a forecast)")
        if rep.fear_greed <= 30:
            lower_low = c.iloc[-1] < c.iloc[-8:-1].min()
            vol_falling = v.tail(5).mean() < v.iloc[-20:-5].mean() * 0.8
            if ret7 > 2:
                rep.divergences.append(
                    f"Fear ({rep.fear_greed}) while BTC rose {ret7:.1f}% over 7d — pessimism not confirmed by price")
            elif lower_low and vol_falling:
                rep.divergences.append(
                    f"Fear ({rep.fear_greed}) with new 7d low on falling volume — selling pressure may be fading "
                    "(seller exhaustion is a hypothesis, not confirmed)")
    if oi_change_24h_pct is not None and price_change_24h_pct is not None:
        if oi_change_24h_pct > 10 and abs(price_change_24h_pct) > 5:
            rep.divergences.append(
                f"BTC open interest +{oi_change_24h_pct:.1f}% during a {price_change_24h_pct:+.1f}% move — "
                "leveraged positioning is building; moves can extend but liquidation cascades are more likely")
    if rep.fear_greed is not None:
        if rep.fear_greed >= 80:
            rep.observations.append("Extreme greed — historically associated with elevated pullback risk")
        elif rep.fear_greed <= 20:
            rep.observations.append("Extreme fear — historically associated with elevated rebound potential but "
                                    "also capitulation risk")
    return rep
