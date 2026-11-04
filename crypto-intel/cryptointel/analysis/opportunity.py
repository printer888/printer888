"""Turn scores into either a fully specified hypothetical trade plan or NO TRADE.

Hard gates (all must pass; each failure is reported):
  1. Essential data present and fresh (primary, trigger and ≥1 higher timeframe; price).
  2. Best direction's score ≥ MIN_SCORE.
  3. Technical and structure sub-scores both above minimums (multi-confirmation).
  4. No higher timeframe opposes the direction.
  5. Not overextended (RSI) on the primary timeframe.
  6. No high-impact scheduled macro event within 24h (when calendar loaded).
  7. Valid stop distance (0.8–3.5 ATR) and net R:R ≥ MIN_RR after fees, slippage, funding.
  8. Estimated liquidation price beyond the stop at the simulated leverage.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..config import Settings
from ..data.freshness import utcnow
from ..risk.leverage import CostModel, simulate_trade
from .scoring import HIGHER_TFS, TRIGGER_TF, ScoreCard, ScoringInputs, score
from .timeframe import TimeframeAnalysis

NO_TRADE = "NO TRADE — INSUFFICIENT CONFIRMATION"


@dataclass
class Opportunity:
    symbol: str
    status: str  # "SIGNAL" | "NO_TRADE"
    headline: str
    direction: str | None
    score: float
    score_long: float
    score_short: float
    timeframe: str
    price: float | None
    trend: dict = field(default_factory=dict)
    scenario: str = ""
    entry_zone: tuple[float, float] | None = None
    entry: float | None = None
    stop: float | None = None
    take_profits: list[float] = field(default_factory=list)
    rr_gross: list[float] = field(default_factory=list)
    rr_net_blended: float | None = None
    costs: dict = field(default_factory=dict)
    simulation: dict = field(default_factory=dict)
    invalidation: list[str] = field(default_factory=list)
    supporting: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    gate_failures: list[str] = field(default_factory=list)
    scorecard: dict = field(default_factory=dict)
    scorecard_opposite: dict = field(default_factory=dict)
    news: list[dict] = field(default_factory=list)
    missing_data: list[str] = field(default_factory=list)
    rejected_plan: dict | None = None  # diagnostic only: the plan that failed the gates
    created_at: str = field(default_factory=lambda: utcnow().isoformat())
    disclaimer: str = ("Hypothetical analysis for simulation only — not a recommendation. "
                       "No outcome is certain.")

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["entry_zone"] = list(self.entry_zone) if self.entry_zone else None
        return d


def _structural_stop(direction: str, entry: float, atr: float, tfa: TimeframeAnalysis) -> tuple[float, str]:
    if direction == "long":
        cands = [x for x in tfa.swing_lows if x < entry - 0.5 * atr]
        if cands:
            lvl = max(cands)
            return lvl - 0.25 * atr, f"below swing low {lvl:.6g} (−0.25 ATR buffer)"
        return entry - 1.5 * atr, "volatility stop 1.5 ATR (no structural swing low available)"
    cands = [x for x in tfa.swing_highs if x > entry + 0.5 * atr]
    if cands:
        lvl = min(cands)
        return lvl + 0.25 * atr, f"above swing high {lvl:.6g} (+0.25 ATR buffer)"
    return entry + 1.5 * atr, "volatility stop 1.5 ATR (no structural swing high available)"


def _targets(direction: str, entry: float, risk: float, atr: float, levels: list[float]) -> tuple[list[float], str]:
    d = 1 if direction == "long" else -1
    lv = sorted({l for l in levels if d * (l - entry) > 0.1 * atr}, key=lambda l: d * (l - entry))
    if not lv:
        return [entry + d * 2 * risk, entry + d * 3 * risk], "no opposing levels in lookback: 2R / 3R projections"
    tp1 = lv[0] - d * 0.1 * atr
    nxt = [l for l in lv[1:] if d * (l - tp1) >= 0.5 * risk]
    tp2 = (nxt[0] - d * 0.1 * atr) if nxt else tp1 + d * risk
    return [tp1, tp2], "targets placed just in front of opposing S/R levels"


def build_opportunity(
    symbol: str,
    inputs: ScoringInputs,
    settings: Settings,
    price: float | None,
    funding_rate: float | None,
    funding_interval_minutes: int = 480,
    equity: float | None = None,
) -> Opportunity:
    tfs = inputs.timeframes
    ptf = inputs.primary_tf
    p = tfs.get(ptf)
    long_card, short_card = score(inputs, "long"), score(inputs, "short")
    best: ScoreCard = long_card if long_card.total >= short_card.total else short_card
    other = short_card if best is long_card else long_card
    direction = best.direction
    d = 1 if direction == "long" else -1
    word = "bullish" if d > 0 else "bearish"
    fails: list[str] = []
    trend = {tf: t.trend for tf, t in tfs.items() if t.sufficient}

    opp = Opportunity(
        symbol=symbol, status="NO_TRADE", headline=NO_TRADE, direction=None, score=best.total,
        score_long=long_card.total, score_short=short_card.total, timeframe=ptf, price=price, trend=trend,
        scorecard=best.to_dict(), scorecard_opposite=other.to_dict(), missing_data=best.missing,
    )
    if inputs.news:
        opp.news = inputs.news.get("items", [])[:5]

    # Gate 1: essential data
    highers = [tfs.get(t) for t in HIGHER_TFS.get(ptf, [])]
    trig = tfs.get(TRIGGER_TF.get(ptf, ""))
    if p is None or not p.sufficient or p.stale:
        fails.append(f"primary timeframe {ptf} missing or stale")
    if trig is None or not trig.sufficient or trig.stale:
        fails.append("trigger timeframe missing or stale")
    if not any(h is not None and h.sufficient and not h.stale for h in highers):
        fails.append("no usable higher timeframe")
    if price is None or not price > 0:
        fails.append("no current price")
    if fails:
        opp.gate_failures = fails
        opp.scenario = "Essential data missing — no analysis-based scenario is produced."
        return opp

    s = p.snapshot
    atr = s["atr"]
    if not atr or not atr > 0:
        opp.gate_failures = [f"{ptf} ATR unavailable"]
        return opp
    gap_atr = abs(price - s["close"]) / atr
    if gap_atr > 3:
        opp.gate_failures = [f"live price {price:.6g} is {gap_atr:.1f} ATR from the last closed {ptf} candle "
                             f"({s['close']:.6g}) — inconsistent data or an extreme move in progress; re-check"]
        opp.scenario = "Price and candle data disagree — no plan produced."
        return opp
    opp.supporting = (p.bullish_evidence if d > 0 else p.bearish_evidence)[:8]
    for h in highers:
        if h is not None and h.sufficient:
            ev = h.bullish_evidence if d > 0 else h.bearish_evidence
            opp.supporting += [f"[{h.timeframe}] {e}" for e in ev[:3]]
    opp.risks = list(p.notes) + list(inputs.derivatives.warnings if inputs.derivatives else [])
    opp.risks += [f"[{h.timeframe}] {e}" for h in highers if h is not None and h.sufficient
                  for e in (h.bearish_evidence if d > 0 else h.bullish_evidence)[:2]]

    # Gate 2/3
    if best.total < settings.min_score:
        fails.append(f"score {best.total:.1f} < minimum {settings.min_score:.0f}")
    if best.points("technical") < settings.min_technical_points:
        fails.append(f"technical {best.points('technical'):.1f} < {settings.min_technical_points}")
    if best.points("structure") < settings.min_structure_points:
        fails.append(f"structure {best.points('structure'):.1f} < {settings.min_structure_points}")
    # Gate 4
    for h in highers:
        if h is not None and h.sufficient and not h.stale and d * h.bias <= -0.35:
            fails.append(f"{h.timeframe} trend is {h.trend} — opposes the {direction} scenario")
    # Gate 5
    r = s.get("rsi")
    if r is not None and ((d > 0 and r >= 78) or (d < 0 and r <= 22)):
        fails.append(f"{ptf} RSI {r:.0f} — overextended; chasing risk")
    # Gate 6
    if inputs.calendar_risk and inputs.calendar_risk.get("high_impact_events"):
        fails.append("high-impact macro event within 24h — standing aside")
    if inputs.news and inputs.news.get("critical_negative") and d > 0:
        fails.append("recent hack/insolvency news on this asset")

    # ---- trade plan (computed even if earlier gates fail, for transparency)
    entry_hi = price if d > 0 else price + 0.3 * atr
    entry_lo = price - 0.3 * atr if d > 0 else price
    entry = (entry_hi + entry_lo) / 2
    stop, stop_txt = _structural_stop(direction, entry, atr, p)
    risk = abs(entry - stop)
    if risk < 0.8 * atr:
        stop = entry - d * 0.8 * atr
        risk = 0.8 * atr
        stop_txt += "; widened to 0.8 ATR minimum (noise buffer)"
    if risk > 3.5 * atr:
        fails.append(f"structural stop {risk / atr:.1f} ATR away (> 3.5 ATR) — risk too wide")
    levels = [x["price"] for x in (p.resistances if d > 0 else p.supports)]
    h0 = highers[0] if highers else None
    if h0 is not None and h0.sufficient:
        levels += [x["price"] for x in (h0.resistances if d > 0 else h0.supports)]
    tps, tp_txt = _targets(direction, entry, risk, atr, levels)

    intervals = max(1.0, 24 * 60 / funding_interval_minutes)  # assume ~1 day holding
    costs = CostModel(settings.taker_fee, settings.maker_fee, settings.slippage_bps, settings.default_mmr)
    sim = simulate_trade(
        equity=equity or settings.paper_starting_equity, side=direction, entry=entry, stop=stop, targets=tps,
        leverage=settings.paper_leverage, sizing="risk", risk_pct=settings.risk_per_trade,
        funding_rate=funding_rate or 0.0, funding_intervals=intervals, costs=costs,
    )
    blended = (0.5 * sim.profit_at_targets[0] + 0.5 * sim.profit_at_targets[1]) / abs(sim.loss_at_stop)
    if blended < settings.min_rr:
        fails.append(f"net R:R {blended:.2f} (50/50 at TP1/TP2, after costs) < {settings.min_rr}")
    if sim.liquidation_before_stop:
        fails.append(f"estimated liquidation precedes stop at {settings.paper_leverage}x")

    opp.entry_zone = (min(entry_lo, entry_hi), max(entry_lo, entry_hi))
    opp.entry, opp.stop, opp.take_profits = entry, stop, tps
    opp.rr_gross = [abs(tp - entry) / risk for tp in tps]
    opp.rr_net_blended = blended
    opp.costs = {
        "entry_fee": sim.entry_fee, "exit_fee_at_stop": sim.exit_fee_at_stop,
        "funding_estimate": sim.funding_cost, "slippage_bps": settings.slippage_bps,
        "assumptions": f"taker {settings.taker_fee * 100:.3f}%, maker {settings.maker_fee * 100:.3f}%, "
                       f"funding {(funding_rate or 0) * 100:.4f}% × {intervals:.0f} intervals (~1 day hold)",
    }
    opp.simulation = sim.to_dict()
    opp.invalidation = [
        f"{ptf} close {'below' if d > 0 else 'above'} {stop:.6g} ({stop_txt})",
    ]
    if h0 is not None and h0.snapshot.get("ema50"):
        opp.invalidation.append(
            f"{h0.timeframe} close {'below' if d > 0 else 'above'} EMA50 ({h0.snapshot['ema50']:.6g}) — higher-TF trend shift")
    opp.invalidation.append(
        f"funding moves to crowded {'long' if d > 0 else 'short'} extreme or OI surges against price")
    opp.invalidation.append("unscheduled high-impact news (regulatory action, exchange failure, hack, geopolitical shock)")
    opp.scenario = (
        f"{word.capitalize()} scenario on {ptf}: {', '.join(opp.supporting[:3]) or 'limited evidence'}. "
        f"Stop {stop_txt}; {tp_txt}."
    )
    opp.gate_failures = fails
    if not fails:
        opp.status, opp.direction = "SIGNAL", direction
        opp.headline = f"{direction.upper()} setup — score {best.total:.0f}/100 (hypothetical, simulation only)"
        return opp
    # NO TRADE: never present levels as if they were actionable.
    opp.rejected_plan = {
        "direction_considered": direction, "entry": entry, "stop": stop, "take_profits": tps,
        "rr_net_blended": blended, "note": "diagnostic only — failed the gates listed in gate_failures",
    }
    opp.entry_zone = opp.entry = opp.stop = None
    opp.take_profits, opp.rr_gross, opp.rr_net_blended, opp.simulation = [], [], None, {}
    opp.invalidation = []
    return opp
