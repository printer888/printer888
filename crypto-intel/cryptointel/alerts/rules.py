"""Alert rules. Every alert carries the evidence that triggered it and the relevant risks."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable

from ..analysis.timeframe import TimeframeAnalysis
from ..data.freshness import utcnow
from .telegram import TelegramNotifier, esc

log = logging.getLogger(__name__)


@dataclass
class Alert:
    type: str
    symbol: str | None
    title: str
    evidence: list[str]
    risks: list[str]
    severity: str = "info"  # info | warning | critical
    created_at: datetime = field(default_factory=utcnow)

    def to_html(self) -> str:
        icon = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}.get(self.severity, "")
        lines = [f"{icon} <b>{esc(self.title)}</b>"]
        if self.symbol:
            lines.append(f"Symbol: <code>{esc(self.symbol)}</code>")
        lines.append("<b>Evidence</b>")
        lines += [f"• {esc(e)}" for e in self.evidence] or ["• (none)"]
        lines.append("<b>Risks / caveats</b>")
        lines += [f"• {esc(r)}" for r in self.risks]
        lines.append(f"<i>{self.created_at:%Y-%m-%d %H:%M} UTC · research/simulation only, not financial advice</i>")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {"type": self.type, "symbol": self.symbol, "title": self.title, "evidence": self.evidence,
                "risks": self.risks, "severity": self.severity, "created_at": self.created_at.isoformat()}


GENERIC_RISK = "Single observations are not predictive; confirm with other evidence before drawing conclusions."


class AlertManager:
    def __init__(self, notifier: TelegramNotifier, cooldown_minutes: int = 60,
                 sink: Callable[[Alert, bool], None] | None = None):
        self.notifier = notifier
        self.cooldown = timedelta(minutes=cooldown_minutes)
        self.sink = sink
        self._last: dict[tuple, datetime] = {}
        self.recent: list[Alert] = []

    def emit(self, alert: Alert, key_extra: str = "") -> bool:
        key = (alert.type, alert.symbol, key_extra)
        now = utcnow()
        if key in self._last and now - self._last[key] < self.cooldown:
            return False
        self._last[key] = now
        sent = self.notifier.send(alert.to_html())
        self.recent = (self.recent + [alert])[-200:]
        if self.sink:
            try:
                self.sink(alert, sent)
            except Exception as e:  # persistence failure must not kill alerting
                log.warning("alert sink failed: %s", e)
        return True


# ---------------------------------------------------------------- rule functions
def breakout_alert(symbol: str, tfa: TimeframeAnalysis) -> Alert | None:
    b = tfa.breakout or {}
    if b.get("type") not in ("breakout", "breakdown") or tfa.stale:
        return None
    risks = [GENERIC_RISK, "Breakouts frequently fail and retrace into the range (false breakouts)."]
    if tfa.snapshot.get("rsi") and (tfa.snapshot["rsi"] > 75 or tfa.snapshot["rsi"] < 25):
        risks.append(f"RSI {tfa.snapshot['rsi']:.0f} is extreme — extended move.")
    return Alert("breakout", symbol, f"{symbol} {tfa.timeframe} volume-confirmed {b['type']}",
                 [b["evidence"], f"{tfa.timeframe} trend {tfa.trend}, ADX {tfa.adx or 0:.0f}"], risks, "warning")


def unusual_volume_alert(symbol: str, tfa: TimeframeAnalysis, threshold: float = 3.0) -> Alert | None:
    rv = tfa.snapshot.get("rvol")
    if rv is None or rv < threshold or tfa.stale:
        return None
    cd = tfa.snapshot.get("candle_dir", 0)
    return Alert("unusual_volume", symbol, f"{symbol} unusual volume on {tfa.timeframe} ({rv:.1f}× average)",
                 [f"RVOL {rv:.2f} vs 20-bar average", f"candle closed {'up' if cd > 0 else 'down' if cd < 0 else 'flat'}"],
                 [GENERIC_RISK, "Volume spikes can mark both initiation and exhaustion of moves.",
                  "Exchange-specific volume may not reflect the whole market."], "info")


def volatility_alert(symbol: str, tfa: TimeframeAnalysis) -> Alert | None:
    pct = tfa.snapshot.get("atr_pct_percentile")
    if pct is None or pct < 97 or tfa.stale:
        return None
    return Alert("volatility", symbol, f"{symbol} unusual volatility on {tfa.timeframe}",
                 [f"ATR% at the {pct:.0f}th percentile of the last 100 bars",
                  f"ATR {tfa.snapshot.get('atr_pct') or 0:.2f}% of price"],
                 ["Wider spreads, slippage and stop-hunts are more likely.",
                  "Leveraged positions face higher liquidation risk."], "warning")


def news_alert(ev: dict) -> Alert | None:
    if ev.get("importance") != "high":
        return None
    return Alert("news", None, f"High-impact news: {ev['title'][:150]}",
                 [f"source: {ev['source']} ({ev['confirmation']})", f"published: {ev.get('published_at')} (age {ev.get('age')})",
                  f"event type: {', '.join(ev.get('event_types', []))}", f"assets: {', '.join(ev.get('assets', [])) or 'n/a'}",
                  f"expected impact duration: {ev.get('impact_duration')}",
                  *(f"bullish case: {b}" for b in ev.get("bullish_case", [])[:1]),
                  *(f"bearish case: {b}" for b in ev.get("bearish_case", [])[:1]), ev.get("url", "")],
                 ["Headline classification is automated keyword matching — read the original source.",
                  "Market reaction to news is uncertain and often already priced in."], "warning")


def sentiment_shift_alert(prev: int | None, cur: int | None, label: str | None) -> Alert | None:
    if prev is None or cur is None or abs(cur - prev) < 15:
        return None
    return Alert("sentiment", None, f"Sentiment shift: Fear & Greed {prev} → {cur} ({label})",
                 [f"change of {cur - prev:+d} points"],
                 ["Fear & Greed is a lagging composite; extremes can persist.", GENERIC_RISK], "info")


def signal_alert(opp: dict) -> Alert:
    sim = opp.get("simulation", {})
    ev = [f"score {opp['score']:.0f}/100 ({opp['direction']})",
          f"entry zone {opp['entry_zone'][0]:.6g}–{opp['entry_zone'][1]:.6g}, stop {opp['stop']:.6g}, "
          f"TPs {', '.join(f'{x:.6g}' for x in opp['take_profits'])}",
          f"net R:R (blended) {opp['rr_net_blended']:.2f}"] + opp.get("supporting", [])[:4]
    risks = opp.get("risks", [])[:3] + opp.get("invalidation", [])[:2] + [
        f"simulated at {sim.get('leverage')}x: est. liquidation {sim.get('liquidation_price', 0):.6g}",
        "Hypothetical setup for paper trading only."]
    return Alert("signal", opp["symbol"], f"{opp['symbol']} {opp['headline']}", ev, risks, "info")


def paper_event_alert(ev: dict) -> Alert:
    sev = "critical" if "LIQUIDATION" in ev["reason"] else "info"
    return Alert("paper_trade", ev["symbol"], f"Paper trade #{ev['trade_id']} {ev['symbol']} {ev['side']}: {ev['reason']}",
                 [f"exit {ev['qty']:.6g} @ {ev['price']:.6g}, leg P&L {ev['pnl']:+.2f} USDT",
                  f"trade closed: {ev['closed']}; realised {ev['realized_pnl']:+.2f} USDT"
                  + (f" ({ev['r_multiple']:+.2f}R)" if ev.get("r_multiple") is not None and ev["closed"] else "")],
                 ["Simulated fill — real fills may differ (slippage, latency, liquidity)."], sev)


def drawdown_alert(dd_pct: float, threshold: float, name: str = "paper portfolio") -> Alert | None:
    if dd_pct > -threshold:
        return None
    return Alert("drawdown", None, f"Excessive drawdown: {name} {dd_pct:.1f}%",
                 [f"current drawdown {dd_pct:.1f}% exceeds alert threshold -{threshold:.0f}%"],
                 ["Consider pausing the strategy and reviewing whether market regime has changed.",
                  "Do not increase size to recover losses."], "critical")
