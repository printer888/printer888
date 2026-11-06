"""Trader evaluation from on-chain history.

Total profit alone is a poor selection criterion (one lucky trade, wash
trading, or untradeable sniping can all look like "profit"). This module
reconstructs round trips per token (FIFO) and reports consistency, risk and
copyability, plus red flags.

Caveats surfaced in the report:
* P/L is computed in the quote asset of each trade and converted with the
  *current* quote price (historical SOL/USD is not on-chain), so USD figures
  are approximate. Percentage returns are exact for the observed fills.
* Positions opened before the analysed window have no observed entry and
  are excluded from round-trip statistics.
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from ..schemas import EventKind, SwapEvent


@dataclass
class RoundTrip:
    mint: str
    quote_mint: str
    opened_at: datetime | None
    closed_at: datetime | None
    cost_quote: float
    proceeds_quote: float
    hold_seconds: float | None
    buys: int
    sells: int

    @property
    def pnl_quote(self) -> float:
        return self.proceeds_quote - self.cost_quote

    @property
    def return_pct(self) -> float:
        return 100.0 * self.pnl_quote / self.cost_quote if self.cost_quote else 0.0


@dataclass
class TraderReport:
    wallet: str
    window_start: str | None
    window_end: str | None
    transactions_analysed: int
    buys: int
    sells: int
    failed_tx: int
    closed_trades: int
    open_positions: list[dict]
    win_rate_pct: float | None
    avg_win_pct: float | None
    avg_loss_pct: float | None
    avg_profit_usd: float | None
    avg_loss_usd: float | None
    total_pnl_usd: float | None
    profit_factor: float | None
    largest_win_usd: float | None
    largest_loss_usd: float | None
    max_drawdown_usd: float | None
    max_drawdown_pct_of_peak: float | None
    trades_per_day: float | None
    avg_hold_minutes: float | None
    median_hold_minutes: float | None
    distinct_tokens: int
    top_tokens: list[dict]
    recent_activity: list[dict]
    red_flags: list[str] = field(default_factory=list)
    copyability: dict = field(default_factory=dict)
    score: float = 0.0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def build_round_trips(events: list[SwapEvent]) -> tuple[list[RoundTrip], dict[str, dict]]:
    """FIFO per mint. A round trip runs from the first observed buy to the sell that empties it."""
    open_: dict[str, dict] = {}
    trips: list[RoundTrip] = []
    for ev in sorted(events, key=lambda e: (e.slot, e.signature)):
        if not ev.token_mint or ev.price_in_quote is None or not ev.quote_mint:
            continue
        if ev.kind == EventKind.BUY:
            o = open_.setdefault(ev.token_mint, dict(qty=0.0, cost=0.0, proceeds=0.0, opened=ev.block_time,
                                                     quote=ev.quote_mint, buys=0, sells=0))
            o["qty"] += ev.token_amount
            o["cost"] += ev.quote_amount
            o["buys"] += 1
        elif ev.kind in (EventKind.SELL_FULL, EventKind.SELL_PARTIAL):
            o = open_.get(ev.token_mint)
            if not o or o["qty"] <= 0:
                continue  # entry happened before the analysed window
            sold = min(ev.token_amount, o["qty"])
            frac = sold / o["qty"]
            # realise the matching slice of cost
            cost_slice = o["cost"] * frac
            o["qty"] -= sold
            o["cost"] -= cost_slice
            o.setdefault("realised_cost", 0.0)
            o["realised_cost"] += cost_slice
            o["proceeds"] += ev.quote_amount * (sold / ev.token_amount if ev.token_amount else 1)
            o["sells"] += 1
            if ev.kind == EventKind.SELL_FULL or o["qty"] <= 1e-12:
                hold = ((ev.block_time - o["opened"]).total_seconds()
                        if ev.block_time and o["opened"] else None)
                trips.append(RoundTrip(ev.token_mint, o["quote"], o["opened"], ev.block_time,
                                       o["realised_cost"], o["proceeds"], hold, o["buys"], o["sells"]))
                del open_[ev.token_mint]
    return trips, open_


def max_drawdown(pnls: list[float]) -> tuple[float, float | None]:
    eq, peak, mdd = 0.0, 0.0, 0.0
    for p in pnls:
        eq += p
        peak = max(peak, eq)
        mdd = max(mdd, peak - eq)
    return mdd, (100.0 * mdd / peak if peak > 0 else None)


def analyse(wallet: str, events: list[SwapEvent], quote_usd: dict[str, float],
            latency_penalty_pct: float = 2.0, round_trip_cost_pct: float = 1.0) -> TraderReport:
    buys = [e for e in events if e.kind == EventKind.BUY]
    sells = [e for e in events if e.kind in (EventKind.SELL_FULL, EventKind.SELL_PARTIAL)]
    failed = [e for e in events if e.kind == EventKind.FAILED]
    times = [e.block_time for e in events if e.block_time]
    trips, still_open = build_round_trips(events)

    def usd(t: RoundTrip) -> float | None:
        px = quote_usd.get(t.quote_mint)
        return t.pnl_quote * px if px else None

    pnl_usd = [usd(t) for t in trips]
    known = [p for p in pnl_usd if p is not None]
    wins = [t for t in trips if t.pnl_quote > 0]
    losses = [t for t in trips if t.pnl_quote <= 0]
    win_usd = [p for p in known if p > 0]
    loss_usd = [p for p in known if p <= 0]
    holds = [t.hold_seconds / 60 for t in trips if t.hold_seconds is not None]
    span_days = ((max(times) - min(times)).total_seconds() / 86400) if len(times) > 1 else None
    mdd, mdd_pct = max_drawdown(known) if known else (None, None)

    token_counts: dict[str, int] = defaultdict(int)
    for e in buys:
        token_counts[e.token_mint] += 1

    flags: list[str] = []
    n = len(trips)
    if n < 20:
        flags.append(f"small sample: only {n} completed round trips observed")
    if n and len(wins) / n > 0.9 and n >= 10:
        flags.append("win rate above 90%: verify it is not driven by wash trades or unrealised losers left open")
    if win_usd and sum(win_usd) > 0 and max(win_usd) / sum(win_usd) > 0.5:
        flags.append("over half of gross profit comes from a single trade (outlier-driven)")
    if holds and statistics.median(holds) < 2:
        flags.append("median hold under 2 minutes: sniping/scalping that copy latency cannot replicate")
    same_slot = sum(1 for t in trips if t.hold_seconds is not None and t.hold_seconds <= 1)
    if same_slot >= 3:
        flags.append(f"{same_slot} round trips opened and closed within ~1 second (possible wash/bundled trades)")
    if events and len(failed) / max(1, len(events)) > 0.3:
        flags.append("more than 30% of transactions failed")
    losing_open = len(still_open)
    if losing_open > max(5, n):
        flags.append(f"{losing_open} positions still open vs {n} closed: may be holding losers (bag holding)")
    if token_counts and max(token_counts.values()) / max(1, len(buys)) > 0.5 and len(buys) >= 10:
        flags.append("activity concentrated in one token")

    # Copyability: assume we enter `latency_penalty_pct` worse and exit equally worse, plus costs.
    pen = latency_penalty_pct / 100
    copied = [((1 + t.return_pct / 100) * (1 - pen) / (1 + pen) - 1) * 100 - round_trip_cost_pct for t in trips]
    copy = {
        "assumed_entry_exit_penalty_pct": latency_penalty_pct,
        "assumed_round_trip_cost_pct": round_trip_cost_pct,
        "trader_avg_return_pct": round(statistics.mean([t.return_pct for t in trips]), 2) if trips else None,
        "estimated_copy_avg_return_pct": round(statistics.mean(copied), 2) if copied else None,
        "estimated_copy_win_rate_pct": round(100 * sum(1 for c in copied if c > 0) / len(copied), 1) if copied else None,
    }

    # Composite score (0-100): rewards consistency and sample size, penalises drawdown and flags.
    score = 0.0
    if n:
        wr = len(wins) / n
        pf = (sum(win_usd) / abs(sum(loss_usd))) if loss_usd and sum(loss_usd) != 0 else (3.0 if win_usd else 0.0)
        score += 30 * min(1.0, wr / 0.6)
        score += 25 * min(1.0, pf / 2.0)
        score += 15 * min(1.0, n / 50)
        if copy["estimated_copy_avg_return_pct"] is not None and copy["estimated_copy_avg_return_pct"] > 0:
            score += 20
        if mdd_pct is not None:
            score += 10 * max(0.0, 1 - mdd_pct / 50)
        score -= 8 * len(flags)
    score = max(0.0, min(100.0, score))

    recent = [dict(time=e.block_time.isoformat() if e.block_time else None, kind=e.kind.value,
                   token=e.token_mint, amount=e.token_amount, quote=e.quote_mint, quote_amount=e.quote_amount,
                   signature=e.signature) for e in sorted(events, key=lambda e: e.slot, reverse=True)[:20]]
    return TraderReport(
        wallet=wallet,
        window_start=min(times).isoformat() if times else None,
        window_end=max(times).isoformat() if times else None,
        transactions_analysed=len({e.signature for e in events}),
        buys=len(buys), sells=len(sells), failed_tx=len(failed), closed_trades=n,
        open_positions=[dict(token=m, qty=o["qty"], cost_quote=o["cost"], quote=o["quote"],
                             opened=o["opened"].isoformat() if o["opened"] else None) for m, o in still_open.items()],
        win_rate_pct=round(100 * len(wins) / n, 1) if n else None,
        avg_win_pct=round(statistics.mean([t.return_pct for t in wins]), 2) if wins else None,
        avg_loss_pct=round(statistics.mean([t.return_pct for t in losses]), 2) if losses else None,
        avg_profit_usd=round(statistics.mean(win_usd), 2) if win_usd else None,
        avg_loss_usd=round(statistics.mean(loss_usd), 2) if loss_usd else None,
        total_pnl_usd=round(sum(known), 2) if known else None,
        profit_factor=round(sum(win_usd) / abs(sum(loss_usd)), 2) if loss_usd and sum(loss_usd) != 0 else None,
        largest_win_usd=round(max(win_usd), 2) if win_usd else None,
        largest_loss_usd=round(min(loss_usd), 2) if loss_usd else None,
        max_drawdown_usd=round(mdd, 2) if mdd is not None else None,
        max_drawdown_pct_of_peak=round(mdd_pct, 1) if mdd_pct is not None else None,
        trades_per_day=round(len(buys) / span_days, 2) if span_days else None,
        avg_hold_minutes=round(statistics.mean(holds), 1) if holds else None,
        median_hold_minutes=round(statistics.median(holds), 1) if holds else None,
        distinct_tokens=len(token_counts),
        top_tokens=[dict(token=m, buys=c) for m, c in sorted(token_counts.items(), key=lambda x: -x[1])[:10]],
        recent_activity=recent, red_flags=flags, copyability=copy, score=round(score, 1),
        notes=["USD values use current quote-asset prices (approximate).",
               "Positions opened before the analysed window are excluded from round-trip stats.",
               f"Generated {datetime.now(timezone.utc).isoformat()}"],
    )
