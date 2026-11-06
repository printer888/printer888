"""Risk engine. Pure functions with no I/O so every rule is unit-testable.

Principles:
* New risk (BUYs) must pass *every* check; any failure rejects the copy.
* Reducing risk (SELLs / exits) is never blocked by portfolio limits, only by
  execution feasibility, so a halted system can still get out of positions.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from ..schemas import Decision, Quote, RiskLimits, TokenMarket, TokenSafety


@dataclass
class PortfolioState:
    open_positions: int
    allocated_usd: float          # remaining cost basis of open positions
    realized_pnl_total_usd: float
    realized_pnl_today_usd: float
    unrealized_pnl_usd: float
    equity_peak_usd: float
    consecutive_failures: int
    emergency_stop: bool
    paused: bool
    holding_mint: bool = False    # already hold this token (add-on buy)

    def equity(self, capital: float) -> float:
        return capital + self.realized_pnl_total_usd + self.unrealized_pnl_usd


@dataclass
class BuyContext:
    token_mint: str
    trader_price_usd: float | None
    trader_notional_usd: float | None
    current_price_usd: float | None
    signal_age_sec: float | None
    market: TokenMarket | None
    safety: TokenSafety | None
    quote: Quote | None
    est_network_fee_usd: float  # one transaction
    now: datetime | None = None


def portfolio_halt_reasons(limits: RiskLimits, st: PortfolioState) -> list[str]:
    """Conditions under which *new* positions are not allowed."""
    r: list[str] = []
    if st.emergency_stop:
        r.append("emergency stop active")
    if st.paused:
        r.append("copying paused")
    daily = st.realized_pnl_today_usd + min(0.0, st.unrealized_pnl_usd)
    if daily <= -limits.max_daily_loss_usd:
        r.append(f"daily loss limit hit ({daily:.2f} <= -{limits.max_daily_loss_usd:.2f} USD)")
    equity = st.equity(limits.total_capital_usd)
    peak = max(st.equity_peak_usd, limits.total_capital_usd)
    dd = 100.0 * (peak - equity) / peak if peak > 0 else 0.0
    if dd >= limits.max_drawdown_pct:
        r.append(f"max drawdown hit ({dd:.1f}% >= {limits.max_drawdown_pct:.1f}%)")
    if st.consecutive_failures >= limits.max_consecutive_failures:
        r.append(f"{st.consecutive_failures} consecutive execution failures")
    return r


def size_buy(limits: RiskLimits, st: PortfolioState, trader_notional_usd: float | None) -> Decision:
    d = Decision(approved=True)
    if limits.sizing_mode == "proportional":
        if not trader_notional_usd:
            return d.reject("proportional sizing needs the trader's trade value, which is unknown")
        size = trader_notional_usd * limits.proportional_ratio
    else:
        size = limits.fixed_position_usd
    size = min(size, limits.max_position_usd)
    remaining = limits.max_allocated_usd - st.allocated_usd
    if remaining < size:
        size = max(0.0, remaining)
        d.checks["capped_by_allocation"] = True
    d.size_usd = round(size, 2)
    d.checks["size_usd"] = d.size_usd
    if size < limits.min_position_usd:
        d.reject(f"position size {size:.2f} USD below minimum {limits.min_position_usd:.2f} "
                 f"(allocation remaining {remaining:.2f})")
    if not st.holding_mint and st.open_positions >= limits.max_open_positions:
        d.reject(f"max open positions reached ({st.open_positions})")
    return d


def check_buy(limits: RiskLimits, st: PortfolioState, ctx: BuyContext, size_usd: float) -> Decision:
    d = Decision(approved=True, size_usd=size_usd)
    for r in portfolio_halt_reasons(limits, st):
        d.reject(r)
    now = ctx.now or datetime.now(timezone.utc)

    # Signal freshness: a delayed signal is a different trade.
    if ctx.signal_age_sec is None:
        d.reject("trader transaction time unknown")
    else:
        d.checks["signal_age_sec"] = round(ctx.signal_age_sec, 1)
        if ctx.signal_age_sec > limits.max_signal_age_sec:
            d.reject(f"signal too old ({ctx.signal_age_sec:.0f}s > {limits.max_signal_age_sec}s)")

    # Market quality
    m = ctx.market
    if m is None:
        d.reject("no market data for token")
    else:
        d.checks.update(liquidity_usd=m.liquidity_usd, volume_24h_usd=m.volume_24h_usd)
        if (m.liquidity_usd or 0) < limits.min_liquidity_usd:
            d.reject(f"liquidity {m.liquidity_usd or 0:,.0f} USD < {limits.min_liquidity_usd:,.0f}")
        if (m.volume_24h_usd or 0) < limits.min_volume_24h_usd:
            d.reject(f"24h volume {m.volume_24h_usd or 0:,.0f} USD < {limits.min_volume_24h_usd:,.0f}")
        if m.pair_created_at is not None:
            age_h = (now - m.pair_created_at).total_seconds() / 3600
            d.checks["pair_age_hours"] = round(age_h, 2)
            if age_h < limits.min_pair_age_hours:
                d.reject(f"pool only {age_h:.2f}h old (< {limits.min_pair_age_hours}h)")

    # Token contract
    s = ctx.safety
    if s is None or s.error:
        d.reject(f"token contract could not be verified ({s.error if s else 'no data'})")
    else:
        if limits.require_mint_authority_revoked and s.mint_authority:
            d.reject("mint authority not revoked (supply can be inflated)")
        if limits.require_freeze_authority_revoked and s.freeze_authority:
            d.reject("freeze authority not revoked (holders can be frozen)")
        if s.is_token_2022 and not limits.allow_token_2022:
            d.reject("Token-2022 mint not allowed by policy")
        if s.risky_extensions:
            d.reject(f"risky token extensions: {', '.join(s.risky_extensions)}")
        if s.top10_holder_pct is not None:
            d.checks["top10_holder_pct"] = round(s.top10_holder_pct, 1)
            if s.top10_holder_pct > limits.max_top10_holder_pct:
                d.reject(f"top-10 holders own {s.top10_holder_pct:.1f}% (> {limits.max_top10_holder_pct}%)")

    # Price movement since the trader's entry
    if ctx.current_price_usd is None:
        d.reject("current price unavailable")
    elif ctx.trader_price_usd:
        drift = 100.0 * (ctx.current_price_usd - ctx.trader_price_usd) / ctx.trader_price_usd
        d.checks["entry_drift_pct"] = round(drift, 2)
        if drift > limits.max_entry_drift_pct:
            d.reject(f"price already moved +{drift:.1f}% since trader entry (> {limits.max_entry_drift_pct}%)")
    else:
        d.checks["entry_drift_pct"] = None

    # Executable depth for *our* size
    q = ctx.quote
    if q is None:
        d.reject("no executable route/quote for this size")
    else:
        d.checks["price_impact_pct"] = round(q.price_impact_pct, 3)
        if q.price_impact_pct > limits.max_price_impact_pct:
            d.reject(f"price impact {q.price_impact_pct:.2f}% > {limits.max_price_impact_pct}%")
        if q.slippage_bps > limits.max_slippage_bps:
            d.reject(f"slippage tolerance {q.slippage_bps}bps > {limits.max_slippage_bps}bps")

    # Round-trip cost estimate: 2 network fees + impact in and out.
    if size_usd > 0:
        impact = (q.price_impact_pct if q else 0.0) / 100.0
        est = 2 * ctx.est_network_fee_usd + 2 * impact * size_usd
        pct = 100.0 * est / size_usd
        d.checks["est_round_trip_cost_usd"] = round(est, 4)
        d.checks["est_round_trip_cost_pct"] = round(pct, 3)
        if pct > limits.max_round_trip_cost_pct:
            d.reject(f"estimated round-trip cost {pct:.2f}% > {limits.max_round_trip_cost_pct}%")
    return d


def exit_reason(limits: RiskLimits, *, entry_price: float | None, price: float | None,
                peak_price: float | None, opened_at: datetime, now: datetime,
                trader_last_activity: datetime | None) -> str | None:
    """Independent exit protection for a copied position (trader has NOT sold)."""
    if price is None or not entry_price:
        return None
    chg = 100.0 * (price - entry_price) / entry_price
    if limits.stop_loss_pct is not None and chg <= -limits.stop_loss_pct:
        return f"stop_loss ({chg:.1f}%)"
    if limits.take_profit_pct is not None and chg >= limits.take_profit_pct:
        return f"take_profit (+{chg:.1f}%)"
    if limits.trailing_stop_pct is not None and peak_price and peak_price > entry_price:
        from_peak = 100.0 * (price - peak_price) / peak_price
        if from_peak <= -limits.trailing_stop_pct:
            return f"trailing_stop ({from_peak:.1f}% from peak)"
    if limits.max_hold_hours is not None:
        held_h = (now - opened_at).total_seconds() / 3600
        if held_h >= limits.max_hold_hours:
            return f"max_hold_time ({held_h:.1f}h)"
    return None
