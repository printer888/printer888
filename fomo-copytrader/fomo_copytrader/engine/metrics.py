"""Portfolio metrics and the performance report (all figures net of recorded costs)."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from ..models import CopyOrder, Position, TraderEvent


def _sig(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.6g}"


def position_dict(p: Position, est_exit_fee_usd: float = 0.0) -> dict:
    value = p.my_amount * p.last_price_usd if p.last_price_usd is not None else None
    unreal = (value - p.my_cost_basis_usd) if value is not None and p.status == "open" else None
    return dict(
        id=p.id, status=p.status, mode=p.mode, token_mint=p.token_mint, token_symbol=p.token_symbol,
        trader_wallet=p.trader_wallet,
        trader_entry_price_usd=p.trader_entry_price_usd, my_entry_price_usd=p.my_entry_price_usd,
        trader_initial_amount=p.trader_initial_amount, trader_current_amount=p.trader_current_amount,
        trader_last_action=p.trader_last_action,
        trader_last_action_at=p.trader_last_action_at.isoformat() if p.trader_last_action_at else None,
        my_amount=p.my_amount, my_cost_basis_usd=round(p.my_cost_basis_usd, 4),
        my_invested_usd=round(p.my_invested_usd, 4),
        current_price_usd=p.last_price_usd, value_usd=value,
        unrealized_pnl_usd=unreal,
        unrealized_net_est_usd=(unreal - est_exit_fee_usd) if unreal is not None else None,
        realized_pnl_usd=round(p.realized_pnl_usd, 4), fees_usd=round(p.fees_usd, 4),
        slippage_usd=round(p.slippage_usd, 4), liquidity_usd=p.last_liquidity_usd,
        pending_exit=p.pending_exit_fraction, exit_reason=p.exit_reason,
        opened_at=p.opened_at.isoformat() if p.opened_at else None,
        closed_at=p.closed_at.isoformat() if p.closed_at else None,
    )


async def portfolio_summary(sm: async_sessionmaker, capital: float, est_exit_fee_usd: float) -> dict:
    async with sm() as s:
        pos = list((await s.execute(select(Position))).scalars())
        orders = list((await s.execute(select(CopyOrder))).scalars())
    open_ = [p for p in pos if p.status == "open"]
    closed = [p for p in pos if p.status == "closed"]
    realized = sum(p.realized_pnl_usd for p in pos)
    unreal = sum((p.my_amount * p.last_price_usd - p.my_cost_basis_usd) for p in open_ if p.last_price_usd is not None)
    fees = sum(p.fees_usd for p in pos)
    slip = sum(p.slippage_usd for p in pos)
    daily: dict[str, float] = defaultdict(float)
    for o in orders:
        if o.side == "SELL" and o.status == "filled" and o.completed_at and o.realized_pnl_usd is not None:
            daily[o.completed_at.date().isoformat()] += o.realized_pnl_usd
    today = datetime.now(timezone.utc).date().isoformat()
    filled = [o for o in orders if o.status == "filled"]
    wins = [p for p in closed if p.realized_pnl_usd > 0]
    return dict(
        capital_usd=capital,
        allocated_usd=round(sum(p.my_cost_basis_usd for p in open_), 2),
        open_positions=len(open_), closed_positions=len(closed),
        realized_pnl_usd=round(realized, 4),
        unrealized_pnl_usd=round(unreal, 4),
        unrealized_net_est_usd=round(unreal - est_exit_fee_usd * len(open_), 4),
        total_fees_usd=round(fees, 4), total_slippage_usd=round(slip, 4),
        total_costs_usd=round(fees + slip, 4),
        equity_usd=round(capital + realized + unreal, 2),
        today_realized_pnl_usd=round(daily.get(today, 0.0), 4),
        daily_realized=[dict(date=d, pnl_usd=round(v, 4)) for d, v in sorted(daily.items())],
        orders_filled=len(filled), orders_failed=sum(1 for o in orders if o.status == "failed"),
        closed_win_rate_pct=round(100 * len(wins) / len(closed), 1) if closed else None,
        avg_execution_diff_pct=round(sum(o.execution_diff_pct for o in filled if o.execution_diff_pct is not None)
                                     / max(1, sum(1 for o in filled if o.execution_diff_pct is not None)), 3)
        if filled else None,
    )


async def performance_report_md(sm: async_sessionmaker, capital: float, est_exit_fee_usd: float, mode: str) -> str:
    summ = await portfolio_summary(sm, capital, est_exit_fee_usd)
    async with sm() as s:
        pos = list((await s.execute(select(Position).order_by(Position.id))).scalars())
        evs = list((await s.execute(select(TraderEvent))).scalars())
    lat = [e.latency_sec for e in evs if e.latency_sec is not None]
    status_counts: dict[str, int] = defaultdict(int)
    for e in evs:
        status_counts[e.copy_status] += 1
    lines = [
        f"# Copy trading performance report ({mode})",
        f"_Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')}_",
        "",
        "All P/L figures are net of entry fees, exit fees, network fees and slippage as recorded per fill.",
        "Unrealised figures are marks to the current price and are **not** profits until the position is sold.",
        "",
        "## Summary",
        "| Metric | Value |", "|---|---|",
    ]
    for k in ("capital_usd", "equity_usd", "realized_pnl_usd", "unrealized_pnl_usd", "unrealized_net_est_usd",
              "total_fees_usd", "total_slippage_usd", "total_costs_usd", "open_positions", "closed_positions",
              "closed_win_rate_pct", "orders_filled", "orders_failed", "avg_execution_diff_pct"):
        lines.append(f"| {k} | {summ[k]} |")
    lines += ["", "## Signal handling",
              f"- Trader events recorded: {len(evs)}",
              *[f"- {k}: {v}" for k, v in sorted(status_counts.items())],
              f"- Median detection latency: {sorted(lat)[len(lat)//2]:.1f}s" if lat else "- Latency: n/a",
              "", "## Positions",
              "| # | Token | Status | Trader entry | My entry (incl. costs) | Invested | Realised P/L | Fees | Slippage | Exit |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for p in pos:
        lines.append(f"| {p.id} | {p.token_symbol or p.token_mint[:6]} | {p.status} | {_sig(p.trader_entry_price_usd)} | "
                     f"{_sig(p.my_entry_price_usd)} | {p.my_invested_usd:.2f} | {p.realized_pnl_usd:+.4f} | "
                     f"{p.fees_usd:.4f} | {p.slippage_usd:.4f} | {p.exit_reason or ''} |")
    lines += ["", "## Daily realised P/L", "| Date | P/L |", "|---|---|"]
    lines += [f"| {d['date']} | {d['pnl_usd']:+.4f} |" for d in summ["daily_realized"]] or ["| - | - |"]
    lines += ["", "Past results, simulated or real, do not guarantee future results."]
    return "\n".join(lines)
