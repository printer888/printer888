"""Instrument universe selection.

Not every listed coin deserves analysis. An instrument is only analysed when it is
liquid, tradeable, has enough history, a tight spread, and no signs of abnormal
activity. Every rejection is recorded with its reason so the filter is auditable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .config import Settings
from .data.bybit_client import parse_ticker

STABLECOINS = {"USDT", "USDC", "DAI", "FDUSD", "TUSD", "USDE", "PYUSD", "USDD", "BUSD", "EURT", "EUR", "USD1", "RLUSD"}


@dataclass
class UniverseMember:
    symbol: str
    base: str
    turnover_24h: float
    open_interest_value: float
    spread_bps: float
    change_24h_pct: float
    listing_age_days: float
    funding_interval_minutes: int
    tick_size: float
    is_core: bool
    flags: list[str] = field(default_factory=list)


@dataclass
class UniverseResult:
    members: list[UniverseMember]
    rejected: dict[str, list[str]]
    as_of: datetime

    def symbols(self) -> list[str]:
        return [m.symbol for m in self.members]

    def to_dict(self) -> dict:
        return {
            "as_of": self.as_of.isoformat(),
            "members": [m.__dict__ for m in self.members],
            "rejected_count": len(self.rejected),
            "rejected_sample": dict(list(self.rejected.items())[:50]),
        }


def select_universe(
    instruments: list[dict],
    tickers: list[dict],
    settings: Settings,
    now: datetime | None = None,
) -> UniverseResult:
    now = now or datetime.now(timezone.utc)
    tick_map = {t["symbol"]: parse_ticker(t) for t in tickers}
    wanted_core = set(settings.core_symbols) | set(settings.extra_symbols)
    candidates: list[UniverseMember] = []
    rejected: dict[str, list[str]] = {}

    for inst in instruments:
        sym = inst.get("symbol", "")
        reasons: list[str] = []
        if inst.get("contractType") not in ("LinearPerpetual", None):
            continue  # dated futures are out of scope; skip silently
        if inst.get("quoteCoin") != "USDT":
            continue
        base = inst.get("baseCoin", "")
        if inst.get("status") != "Trading":
            reasons.append(f"status={inst.get('status')}")
        if base.upper() in STABLECOINS:
            reasons.append("stablecoin base asset (no directional information)")
        launch_ms = int(inst.get("launchTime") or 0)
        age_days = (now.timestamp() * 1000 - launch_ms) / 86_400_000 if launch_ms else 0.0
        if age_days < settings.min_listing_days:
            reasons.append(f"listed {age_days:.0f}d ago < {settings.min_listing_days}d (insufficient history)")
        t = tick_map.get(sym)
        if t is None:
            reasons.append("no ticker data")
            rejected[sym] = reasons
            continue
        if not (t["turnover_24h"] >= settings.min_turnover_24h_usd):
            reasons.append(f"24h turnover ${t['turnover_24h']:,.0f} < ${settings.min_turnover_24h_usd:,.0f}")
        if not (t["open_interest_value"] >= settings.min_open_interest_usd):
            reasons.append(f"open interest ${t['open_interest_value']:,.0f} < ${settings.min_open_interest_usd:,.0f}")
        if not (t["spread_bps"] <= settings.max_spread_bps):
            reasons.append(f"spread {t['spread_bps']:.1f}bps > {settings.max_spread_bps}bps")
        if abs(t["change_24h_pct"]) > settings.max_abs_24h_change_pct:
            reasons.append(
                f"24h move {t['change_24h_pct']:+.1f}% exceeds ±{settings.max_abs_24h_change_pct}% (abnormal/unreliable)"
            )
        flags: list[str] = []
        oi = t["open_interest_value"]
        if oi > 0 and t["turnover_24h"] / oi > 40:
            # Turnover dwarfing open interest can indicate wash/churn activity.
            flags.append(f"turnover/OI ratio {t['turnover_24h'] / oi:.0f}x — possible churn; treat volume with caution")
        if reasons:
            rejected[sym] = reasons
            continue
        pf = inst.get("priceFilter", {}) or {}
        candidates.append(
            UniverseMember(
                symbol=sym,
                base=base,
                turnover_24h=t["turnover_24h"],
                open_interest_value=oi,
                spread_bps=t["spread_bps"],
                change_24h_pct=t["change_24h_pct"],
                listing_age_days=age_days,
                funding_interval_minutes=int(inst.get("fundingInterval") or 480),
                tick_size=float(pf.get("tickSize") or 0) or 0.0,
                is_core=sym in wanted_core,
                flags=flags,
            )
        )

    core = [c for c in candidates if c.is_core]
    others = sorted((c for c in candidates if not c.is_core), key=lambda c: c.turnover_24h, reverse=True)
    slots = max(settings.max_universe - len(core), 0)
    members = sorted(core, key=lambda c: c.turnover_24h, reverse=True) + others[:slots]
    for c in others[slots:]:
        rejected[c.symbol] = [f"outside top-{settings.max_universe} by liquidity"]
    for sym in wanted_core:
        if sym in rejected:
            rejected[sym] = ["core symbol failed filter: "] + rejected[sym]
    return UniverseResult(members=members, rejected=rejected, as_of=now)
