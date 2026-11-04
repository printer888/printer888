"""Educational leverage & liquidation simulator for USDT-margined linear perpetuals.

Liquidation estimate (isolated margin, no extra margin added):
  At liquidation, position equity = maintenance margin (+ estimated fee to close).
    Long : E/L + (P − E) = P·(MMR + fee)   →  P = E·(1 − 1/L) / (1 − MMR − fee)
    Short: E/L + (E − P) = P·(MMR + fee)   →  P = E·(1 + 1/L) / (1 + MMR + fee)

This is an approximation. Actual Bybit liquidation depends on the symbol's
risk-limit tier (MMR grows with position size), margin mode (cross margin uses the
whole available balance), unified-account settings, mark price (not last price),
fees reserved at entry and any added margin. Verify on Bybit before relying on it.

Key lesson encoded here: with fixed-fractional risk sizing, the loss at the stop is
the same at every leverage; leverage only reduces the margin posted and moves the
liquidation price closer. With fixed-margin sizing, leverage multiplies both gains
and losses. Higher leverage never makes a setup better.
"""
from __future__ import annotations

from dataclasses import dataclass, field

LEVERAGE_LEVELS = [1, 2, 3, 5, 10, 20]


@dataclass
class CostModel:
    taker_fee: float = 0.00055
    maker_fee: float = 0.0002
    slippage_bps: float = 3.0
    mmr: float = 0.005


def liquidation_price(entry: float, side: str, leverage: float, mmr: float = 0.005, fee: float = 0.00055) -> float:
    if leverage <= 0:
        raise ValueError("leverage must be > 0")
    if side == "long":
        p = entry * (1 - 1 / leverage) / (1 - mmr - fee)
        return max(p, 0.0)
    if side == "short":
        return entry * (1 + 1 / leverage) / (1 + mmr + fee)
    raise ValueError("side must be 'long' or 'short'")


@dataclass
class TradeSimulation:
    side: str
    leverage: float
    sizing: str
    entry: float
    entry_fill: float
    stop: float
    stop_fill: float
    targets: list[float]
    qty: float
    notional: float
    margin: float
    margin_capped: bool
    liquidation_price: float
    liquidation_distance_pct: float
    stop_distance_pct: float
    liquidation_before_stop: bool
    entry_fee: float
    exit_fee_at_stop: float
    funding_cost: float
    loss_at_stop: float
    loss_at_stop_pct_equity: float
    loss_at_liquidation: float
    max_hypothetical_loss: float
    profit_at_targets: list[float]
    rr_at_targets: list[float]
    breakeven_price: float
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def simulate_trade(
    *,
    equity: float,
    side: str,
    entry: float,
    stop: float,
    targets: list[float],
    leverage: float,
    sizing: str = "risk",
    risk_pct: float = 0.01,
    margin_fraction: float = 0.10,
    funding_rate: float = 0.0001,
    funding_intervals: float = 3,
    costs: CostModel | None = None,
) -> TradeSimulation:
    """Simulate one hypothetical trade.

    sizing="risk"   → quantity chosen so the loss at the stop (incl. fees, slippage) ≈ risk_pct × equity
    sizing="margin" → margin_fraction × equity is posted as margin, position = margin × leverage
    funding_rate is per funding interval; positive means longs pay shorts.
    """
    costs = costs or CostModel()
    d = 1 if side == "long" else -1
    if d * (entry - stop) <= 0:
        raise ValueError("stop must be below entry for longs and above entry for shorts")
    slip = costs.slippage_bps / 1e4
    entry_fill = entry * (1 + d * slip)
    stop_fill = stop * (1 - d * slip)  # stops fill as market orders → adverse slippage
    fee = costs.taker_fee
    warnings: list[str] = []

    loss_per_unit = d * (entry_fill - stop_fill) + entry_fill * fee + stop_fill * fee
    if sizing == "risk":
        qty = equity * risk_pct / loss_per_unit
    elif sizing == "margin":
        qty = equity * margin_fraction * leverage / entry_fill
    else:
        raise ValueError("sizing must be 'risk' or 'margin'")
    notional = qty * entry_fill
    margin = notional / leverage
    margin_capped = False
    if margin > equity:
        margin_capped = True
        qty = equity * leverage / entry_fill
        notional, margin = qty * entry_fill, equity
        warnings.append(f"insufficient equity at {leverage}x: position reduced to use 100% of equity as margin")

    liq = liquidation_price(entry_fill, side, leverage, costs.mmr, fee)
    liq_dist = abs(entry_fill - liq) / entry_fill * 100
    stop_dist = abs(entry_fill - stop_fill) / entry_fill * 100
    liq_before_stop = (liq >= stop_fill) if side == "long" else (liq <= stop_fill)
    entry_fee = notional * fee
    exit_fee_stop = qty * stop_fill * fee
    funding_cost = d * notional * funding_rate * funding_intervals
    loss_at_stop = d * (stop_fill - entry_fill) * qty - entry_fee - exit_fee_stop - funding_cost
    loss_at_liq = -(margin + entry_fee + funding_cost)  # isolated: posted margin is lost
    if liq_before_stop:
        warnings.append(
            f"LIQUIDATION ({liq:.6g}) occurs BEFORE the stop ({stop:.6g}) at {leverage}x — the stop would never "
            "trigger; the whole isolated margin would be lost. Plan rejected at this leverage.")
    elif liq_dist < stop_dist * 1.5:
        warnings.append(f"liquidation is only {liq_dist:.2f}% away vs stop {stop_dist:.2f}% — thin buffer; "
                        "wicks on mark price or MMR tier changes could liquidate first")
    if liq_before_stop:
        max_loss = loss_at_liq
    else:
        max_loss = loss_at_stop  # worst *planned* loss with a working stop
        warnings.append("stops can slip in fast markets/gaps; realised loss may exceed the planned loss")

    profits, rrs = [], []
    for tp in targets:
        tp_fill = tp  # take-profit as resting limit → no slippage, maker fee
        gross = d * (tp_fill - entry_fill) * qty
        net = gross - entry_fee - qty * tp_fill * costs.maker_fee - funding_cost
        profits.append(net)
        rrs.append(net / abs(loss_at_stop) if loss_at_stop < 0 else float("inf"))
    breakeven = entry_fill * (1 + d * (fee + costs.maker_fee))
    return TradeSimulation(
        side=side, leverage=leverage, sizing=sizing, entry=entry, entry_fill=entry_fill, stop=stop,
        stop_fill=stop_fill, targets=list(targets), qty=qty, notional=notional, margin=margin,
        margin_capped=margin_capped, liquidation_price=liq, liquidation_distance_pct=liq_dist,
        stop_distance_pct=stop_dist, liquidation_before_stop=liq_before_stop, entry_fee=entry_fee,
        exit_fee_at_stop=exit_fee_stop, funding_cost=funding_cost, loss_at_stop=loss_at_stop,
        loss_at_stop_pct_equity=loss_at_stop / equity * 100, loss_at_liquidation=loss_at_liq,
        max_hypothetical_loss=max_loss, profit_at_targets=profits, rr_at_targets=rrs,
        breakeven_price=breakeven, warnings=warnings,
    )


def compare_leverage(levels: list[float] | None = None, **kwargs) -> dict:
    """Run the same trade at several leverage levels, in both sizing modes."""
    levels = levels or LEVERAGE_LEVELS
    out = {"fixed_risk": [], "fixed_margin": []}
    for lev in levels:
        out["fixed_risk"].append(simulate_trade(leverage=lev, sizing="risk", **kwargs).to_dict())
        out["fixed_margin"].append(simulate_trade(leverage=lev, sizing="margin", **kwargs).to_dict())
    eq = kwargs["equity"]
    move = abs(kwargs["entry"] - kwargs["stop"]) / kwargs["entry"] * 100
    out["lessons"] = [
        "Fixed-risk sizing: the loss at the stop stays ≈ constant; leverage only lowers posted margin and "
        "pulls the liquidation price closer.",
        f"Fixed-margin sizing: a {move:.2f}% adverse move costs {move:.2f}% of the position, i.e. "
        f"leverage × that share of posted margin — at 20x that is {min(move * 20, 100):.0f}% of the margin.",
        "Fees and funding are charged on the full position value, so they grow with leverage in fixed-margin mode.",
        "Higher leverage does not improve the probability or quality of a setup.",
        f"Results assume equity {eq:,.0f} USDT, isolated margin, MMR and fees as configured; Bybit's actual "
        "liquidation depends on risk-limit tiers, margin mode, mark price and account configuration.",
    ]
    return out
