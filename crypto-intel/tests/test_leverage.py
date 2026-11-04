import pytest

from cryptointel.risk.leverage import CostModel, compare_leverage, liquidation_price, simulate_trade

ZERO = CostModel(taker_fee=0, maker_fee=0, slippage_bps=0, mmr=0.005)


def test_liquidation_formula_matches_bybit_simplified():
    # Without fees, Bybit's isolated formula: long liq = E*(1 - 1/L + MMR) to first order.
    e, lev, mmr = 100.0, 10, 0.005
    p = liquidation_price(e, "long", lev, mmr, fee=0)
    assert p == pytest.approx(e * (1 - 1 / lev) / (1 - mmr))
    assert p == pytest.approx(e * (1 - 1 / lev + mmr), rel=1e-3)
    s = liquidation_price(e, "short", lev, mmr, fee=0)
    assert s == pytest.approx(e * (1 + 1 / lev) / (1 + mmr))
    assert liquidation_price(e, "long", 1, mmr, 0) == pytest.approx(0, abs=1e-9)


def test_higher_leverage_moves_liquidation_closer():
    dists = [abs(100 - liquidation_price(100, "long", L)) for L in (2, 5, 10, 20)]
    assert dists == sorted(dists, reverse=True)


def test_fixed_risk_loss_independent_of_leverage():
    kw = dict(equity=10_000, side="long", entry=100, stop=98, targets=[104], risk_pct=0.01, funding_rate=0,
              funding_intervals=0, costs=CostModel())
    losses = [simulate_trade(leverage=L, **kw).loss_at_stop for L in (1, 2, 3, 5)]
    assert all(l == pytest.approx(-100, rel=1e-6) for l in losses)


def test_fixed_margin_scales_with_leverage():
    kw = dict(equity=10_000, side="long", entry=100, stop=99, targets=[102], sizing="margin", margin_fraction=0.1,
              funding_rate=0, funding_intervals=0, costs=ZERO)
    a = simulate_trade(leverage=2, **kw)
    b = simulate_trade(leverage=10, **kw)
    assert b.loss_at_stop == pytest.approx(5 * a.loss_at_stop)
    assert b.profit_at_targets[0] == pytest.approx(5 * a.profit_at_targets[0])


def test_liquidation_before_stop_is_flagged():
    sim = simulate_trade(equity=10_000, side="long", entry=100, stop=90, targets=[120], leverage=20, costs=CostModel())
    assert sim.liquidation_before_stop
    assert sim.max_hypothetical_loss == pytest.approx(sim.loss_at_liquidation)
    assert any("LIQUIDATION" in w for w in sim.warnings)


def test_fees_and_funding_reduce_profit():
    base = dict(equity=10_000, side="long", entry=100, stop=98, targets=[104], leverage=3, risk_pct=0.01)
    free = simulate_trade(costs=ZERO, funding_rate=0, funding_intervals=0, **base)
    costly = simulate_trade(costs=CostModel(), funding_rate=0.0005, funding_intervals=6, **base)
    assert costly.rr_at_targets[0] < free.rr_at_targets[0]
    assert costly.funding_cost > 0  # longs pay positive funding


def test_short_side_and_validation():
    sim = simulate_trade(equity=1000, side="short", entry=100, stop=103, targets=[94], leverage=5)
    assert sim.liquidation_price > 100 and sim.profit_at_targets[0] > 0
    with pytest.raises(ValueError):
        simulate_trade(equity=1000, side="short", entry=100, stop=97, targets=[94], leverage=5)


def test_compare_leverage_contains_all_levels_and_lessons():
    r = compare_leverage(equity=10_000, side="long", entry=100, stop=97, targets=[106])
    assert [x["leverage"] for x in r["fixed_risk"]] == [1, 2, 3, 5, 10, 20]
    assert any("never" in l.lower() or "does not" in l.lower() for l in r["lessons"])
