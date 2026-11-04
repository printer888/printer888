"""Global news & macro event engine.

Pipeline for each item: identify event → timestamp → original source → affected
assets → bullish/bearish implications → expected impact duration → confirmation
status (fact vs. report vs. rumour).

Only real feed items are processed. Reuters, Bloomberg and the Financial Times do
not offer free redistribution feeds; plug in a licensed provider by implementing
`NewsProvider`. Scraping paywalled sites is deliberately not implemented.

News sentiment is weak evidence. It is capped at a small share of the score and is
never treated as a predictor of price.
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol

import httpx

from ..data.freshness import humanize_age, utcnow

log = logging.getLogger(__name__)

ASSET_ALIASES = {
    "BTC": ["bitcoin", "btc"],
    "ETH": ["ethereum", "ether", "eth"],
    "SOL": ["solana", "sol"],
    "BNB": ["bnb", "binance coin", "bnb chain"],
    "XRP": ["xrp", "ripple"],
    "DOGE": ["dogecoin", "doge"],
    "ADA": ["cardano", "ada"],
    "AVAX": ["avalanche", "avax"],
    "LINK": ["chainlink", "link token"],
    "TON": ["toncoin", "the open network"],
    "SUI": ["sui network", "sui"],
    "DOT": ["polkadot"],
    "LTC": ["litecoin", "ltc"],
    "TRX": ["tron", "trx"],
}

# event_type: (keywords, importance, impact_duration, bullish case, bearish case, market_wide)
EVENT_RULES: dict[str, tuple[list[str], str, str, str, str, bool]] = {
    "monetary_policy": (
        ["rate decision", "interest rate", "fomc", "rate cut", "rate hike", "basis points", "monetary policy",
         "policy rate", "quantitative tightening", "balance sheet", "powell", "lagarde", "bailey"],
        "high", "days to weeks",
        "Easier policy / dovish guidance lowers real yields and tends to support risk assets incl. crypto",
        "Tighter policy / hawkish surprise raises discount rates and the dollar, typically a headwind for crypto",
        True),
    "inflation": (
        ["cpi", "inflation", "pce", "consumer prices", "producer prices", "ppi"],
        "high", "hours to days",
        "Cooler-than-expected inflation raises odds of easing (risk-supportive)",
        "Hotter-than-expected inflation lowers odds of easing (risk-negative)", True),
    "employment": (
        ["nonfarm", "non-farm", "payrolls", "unemployment rate", "jobless claims", "jobs report"],
        "high", "hours to days",
        "Data that eases rate expectations without signalling recession can support risk assets",
        "Strong data that pushes yields up, or weak data signalling recession, can weigh on risk assets", True),
    "gdp": (["gdp", "gross domestic product", "recession"], "medium", "days",
            "Stable growth supports risk appetite", "Contraction/recession signals reduce risk appetite", True),
    "geopolitics": (
        ["war", "invasion", "missile", "sanctions", "military", "conflict", "tariff", "trade war", "ceasefire",
         "airstrike", "escalation"],
        "high", "hours to weeks",
        "De-escalation/ceasefire tends to restore risk appetite; some narratives treat BTC as a hedge",
        "Escalation typically triggers risk-off deleveraging across crypto in the short term", True),
    "regulation": (
        ["sec ", "regulator", "regulation", "lawsuit", "cftc", "mica", "ban ", "banned", "legislation", "bill ",
         "enforcement", "license", "stablecoin law", "clarity act", "court"],
        "high", "weeks to months",
        "Regulatory clarity/approvals can unlock institutional demand",
        "Enforcement actions, bans or restrictive rules reduce access and demand", False),
    "etf_flows": (
        ["etf", "inflows", "outflows", "net flows", "spot bitcoin fund", "ibit", "fbtc"],
        "medium", "days",
        "Sustained ETF inflows add structural spot demand",
        "Sustained ETF outflows remove spot demand", False),
    "hack": (
        ["hack", "exploit", "drained", "stolen", "breach", "attacker", "vulnerability", "compromised"],
        "high", "hours to weeks",
        "Rarely bullish; recovery/return of funds can relieve pressure",
        "Direct sell pressure on affected tokens, contagion and confidence loss", False),
    "exchange_failure": (
        ["insolvency", "insolvent", "bankrupt", "bankruptcy", "halts withdrawals", "suspends withdrawals",
         "withdrawals paused", "collapse"],
        "high", "weeks to months",
        "None expected short term",
        "Forced liquidations, contagion and frozen liquidity — historically severe market-wide drawdowns", True),
    "token_unlock": (
        ["token unlock", "unlock", "vesting", "cliff"], "medium", "days to weeks",
        "Already-priced-in unlocks can remove an overhang once passed",
        "New circulating supply can add sell pressure around the unlock date", False),
    "institutional": (
        ["treasury", "buys bitcoin", "purchases bitcoin", "blackrock", "fidelity", "adoption", "custody",
         "acquires", "strategic reserve", "microstrategy", "allocation"],
        "medium", "days to weeks",
        "Institutional accumulation adds demand and legitimacy",
        "Institutional selling or reversal of plans removes demand", False),
    "protocol": (
        ["upgrade", "mainnet", "hard fork", "testnet", "launch", "network outage", "halted", "downtime"],
        "medium", "days",
        "Successful upgrades/launches can improve fundamentals and narrative",
        "Outages, delays or failed upgrades damage confidence", False),
    "listing": (["lists", "listing", "delist", "delisting"], "low", "hours to days",
                "New listings increase access/liquidity", "Delistings reduce liquidity and access", False),
}

SPECULATIVE_MARKERS = [
    "rumor", "rumour", "reportedly", "sources say", "according to sources", "people familiar", "unconfirmed",
    "could ", "might ", "may ", "speculat", "considering", "weighs", "mulls", "expected to", "plans to",
    "allegedly", "?",
]

POS_WORDS = {"surge", "rally", "soar", "gain", "approve", "approval", "inflow", "record high", "bullish", "rebound",
             "jump", "rise", "adopt", "partnership", "upgrade", "cut rates", "ease", "ceasefire", "recover"}
NEG_WORDS = {"plunge", "crash", "drop", "fall", "slump", "hack", "exploit", "outflow", "lawsuit", "ban", "bearish",
             "sell-off", "selloff", "liquidat", "bankrupt", "fraud", "war", "sanction", "hike", "tumble", "stolen",
             "halt", "decline", "fear"}


@dataclass
class NewsEvent:
    title: str
    url: str
    source: str
    official_source: bool
    published_at: datetime | None
    fetched_at: datetime
    summary: str = ""
    event_types: list[str] = field(default_factory=list)
    assets: list[str] = field(default_factory=list)
    market_wide: bool = False
    importance: str = "low"
    impact_duration: str = "unknown"
    bullish_case: list[str] = field(default_factory=list)
    bearish_case: list[str] = field(default_factory=list)
    confirmation: str = "reported"
    sentiment: float = 0.0  # lexicon score in [-1, 1]; weak evidence

    @property
    def uid(self) -> str:
        return hashlib.sha256((self.url or self.title).encode()).hexdigest()[:32]

    def age(self, now: datetime | None = None) -> str:
        if not self.published_at:
            return "unknown (no timestamp in feed)"
        return humanize_age(((now or utcnow()) - self.published_at).total_seconds())

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["published_at"] = self.published_at.isoformat() if self.published_at else None
        d["fetched_at"] = self.fetched_at.isoformat()
        d["age"] = self.age()
        d["uid"] = self.uid
        return d


class NewsProvider(Protocol):
    name: str

    def fetch(self) -> list[NewsEvent]: ...


def _contains(text: str, kw: str) -> bool:
    if kw.endswith(" ") or " " in kw.strip():
        return kw in text
    return re.search(rf"\b{re.escape(kw)}\b", text) is not None


def classify(ev: NewsEvent) -> NewsEvent:
    text = f" {ev.title} {ev.summary} ".lower()
    ranks = {"low": 0, "medium": 1, "high": 2}
    for etype, (kws, imp, dur, bull, bear, wide) in EVENT_RULES.items():
        if any(_contains(text, k) for k in kws):
            ev.event_types.append(etype)
            ev.bullish_case.append(bull)
            ev.bearish_case.append(bear)
            ev.market_wide = ev.market_wide or wide
            if ranks[imp] > ranks[ev.importance]:
                ev.importance, ev.impact_duration = imp, dur
            elif ev.impact_duration == "unknown":
                ev.impact_duration = dur
    for asset, aliases in ASSET_ALIASES.items():
        if any(_contains(text, a) for a in aliases):
            ev.assets.append(asset)
    if ev.market_wide and not ev.assets:
        ev.assets = ["MARKET"]
    if any(m in text for m in SPECULATIVE_MARKERS):
        ev.confirmation = "unconfirmed / speculative wording"
    elif ev.official_source:
        ev.confirmation = "confirmed (official primary source)"
    else:
        ev.confirmation = "reported by news outlet (verify with primary source)"
    pos = sum(1 for w in POS_WORDS if w in text)
    neg = sum(1 for w in NEG_WORDS if w in text)
    ev.sentiment = (pos - neg) / (pos + neg) if pos + neg else 0.0
    if not ev.event_types:
        ev.impact_duration = "unclear"
    return ev


class RSSProvider:
    def __init__(self, name: str, url: str, official: bool, client: httpx.Client | None = None):
        self.name, self.url, self.official = name, url, official
        self.client = client

    def fetch(self) -> list[NewsEvent]:
        import feedparser

        own = self.client is None
        client = self.client or httpx.Client(timeout=15, follow_redirects=True,
                                             headers={"User-Agent": "cryptointel-research/0.1"})
        try:
            resp = client.get(self.url)
            resp.raise_for_status()
            parsed = feedparser.parse(resp.content)
        except Exception as e:
            log.warning("RSS fetch failed for %s: %s", self.name, e)
            return []
        finally:
            if own:
                client.close()
        now = utcnow()
        out = []
        for entry in parsed.entries[:50]:
            ts = entry.get("published_parsed") or entry.get("updated_parsed")
            published = datetime(*ts[:6], tzinfo=timezone.utc) if ts else None
            summary = re.sub(r"<[^>]+>", " ", entry.get("summary", "") or "")[:600]
            out.append(classify(NewsEvent(
                title=(entry.get("title") or "").strip(), url=entry.get("link", ""), source=self.name,
                official_source=self.official, published_at=published, fetched_at=now, summary=summary.strip(),
            )))
        return out


def providers_from_settings(feeds: list[str]) -> list[RSSProvider]:
    out = []
    for spec in feeds:
        parts = spec.split("|")
        if len(parts) >= 2:
            out.append(RSSProvider(parts[0], parts[1], len(parts) > 2 and parts[2] == "1"))
    return out


def fetch_all(providers: list[NewsProvider]) -> list[NewsEvent]:
    seen, out = set(), []
    for p in providers:
        for ev in p.fetch():
            if ev.uid not in seen and ev.title:
                seen.add(ev.uid)
                out.append(ev)
    out.sort(key=lambda e: e.published_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return out


def asset_news_assessment(events: list[NewsEvent], base_asset: str, hours: float = 72,
                          now: datetime | None = None) -> dict:
    """Summarise recent news relevant to one asset (plus market-wide events)."""
    now = now or utcnow()
    rel = [
        e for e in events
        if e.published_at and (now - e.published_at).total_seconds() <= hours * 3600
        and (base_asset in e.assets or "MARKET" in e.assets or (e.market_wide and e.importance == "high"))
    ]
    critical_neg = [e for e in rel if base_asset in e.assets and
                    set(e.event_types) & {"hack", "exchange_failure"} and e.sentiment <= 0]
    confirmed = [e for e in rel if not e.confirmation.startswith("unconfirmed")]
    sent = sum(e.sentiment for e in confirmed) / len(confirmed) if confirmed else 0.0
    return {
        "count": len(rel),
        "confirmed_count": len(confirmed),
        "avg_sentiment_confirmed": sent,
        "critical_negative": [e.title for e in critical_neg],
        "items": [e.to_dict() for e in rel[:8]],
    }
