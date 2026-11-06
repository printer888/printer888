from datetime import datetime, timedelta, timezone

from helpers import TOKEN, safe_token

from fomo_copytrader.risk.engine import BuyContext, PortfolioState, check_buy, exit_reason, size_buy
from fomo_copytrader.schemas import Quote, RiskLimits, TokenMarket, TokenSafety

NOW = datetime(2026, 11, 5, 12, tzinfo=timezone.utc)


def st(**kw):
    base = dict(open_positions=0, allocated_usd=0, realized_pnl_total_usd=0, realized_pnl_today_usd=0,
                unrealized_pnl_usd=0, equity_peak_usd=1000, consecutive_failures=0, emergency_stop=False, paused=False)
    base.update(kw)
    return PortfolioState(**base)


def ctx(**kw):
    base = dict(token_mint=TOKEN, trader_price_usd=0.0025, trader_notional_usd=300, current_price_usd=0.0026,
                signal_age_sec=8, market=TokenMarket(TOKEN, "T", 0.0026, 400_000, 3_000_000,
                                                      pair_created_at=NOW - timedelta(days=3)),
                safety=safe_token(TOKEN), quote=Quote("a", TOKEN, 1, 1, 0.4, 300), est_network_fee_usd=0.016, now=NOW)
    base.update(kw)
    return BuyContext(**base)


L = RiskLimits()


def test_fixed_sizing_and_caps():
    assert size_buy(L, st(), None).size_usd == 25
    d = size_buy(L.model_copy(update={"sizing_mode": "proportional", "proportional_ratio": 0.5}), st(), 1000)
    assert d.size_usd == 50  # capped by max_position_usd


def test_allocation_cap_and_min_size():
    d = size_buy(L, st(allocated_usd=497), None)  # 500 max allocation, 3 left
    assert not d.approved and "below minimum" in d.reasons[0]
    d = size_buy(L, st(allocated_usd=480), None)
    assert d.approved and d.size_usd == 20


def test_max_open_positions():
    assert not size_buy(L, st(open_positions=5), None).approved
    assert size_buy(L, st(open_positions=5, holding_mint=True), None).approved  # add-on is ok


def test_happy_path_approves():
    d = check_buy(L, st(), ctx(), 25)
    assert d.approved, d.reasons
    assert d.checks["entry_drift_pct"] == 4.0


def test_rejections():
    cases = {
        "signal too old": ctx(signal_age_sec=600),
        "liquidity": ctx(market=TokenMarket(TOKEN, "T", 0.0026, 10_000, 3_000_000)),
        "24h volume": ctx(market=TokenMarket(TOKEN, "T", 0.0026, 400_000, 5_000)),
        "price already moved": ctx(current_price_usd=0.0030),
        "price impact": ctx(quote=Quote("a", TOKEN, 1, 1, 7.5, 300)),
        "no executable route": ctx(quote=None),
        "mint authority": ctx(safety=TokenSafety(TOKEN, 6, "p", "SomeAuth", None, 10)),
        "freeze authority": ctx(safety=TokenSafety(TOKEN, 6, "p", None, "SomeAuth", 10)),
        "top-10 holders": ctx(safety=TokenSafety(TOKEN, 6, "p", None, None, 95)),
        "could not be verified": ctx(safety=TokenSafety(TOKEN, None, None, None, None, None, error="rpc down")),
        "pool only": ctx(market=TokenMarket(TOKEN, "T", 0.0026, 400_000, 3_000_000,
                                            pair_created_at=NOW - timedelta(minutes=10))),
        "round-trip cost": ctx(est_network_fee_usd=1.0),
    }
    for needle, c in cases.items():
        d = check_buy(L, st(), c, 25)
        assert not d.approved, needle
        assert any(needle in r for r in d.reasons), (needle, d.reasons)


def test_portfolio_halts():
    for needle, s in {"emergency": st(emergency_stop=True), "paused": st(paused=True),
                      "daily loss": st(realized_pnl_today_usd=-51),
                      "drawdown": st(realized_pnl_total_usd=-250, equity_peak_usd=1100),
                      "consecutive": st(consecutive_failures=3)}.items():
        d = check_buy(L, s, ctx(), 25)
        assert not d.approved and any(needle in r for r in d.reasons), needle


def test_unrealized_losses_count_toward_daily_limit():
    assert not check_buy(L, st(realized_pnl_today_usd=-20, unrealized_pnl_usd=-31), ctx(), 25).approved


def test_exit_rules():
    lim = RiskLimits(stop_loss_pct=20, take_profit_pct=100, trailing_stop_pct=30, max_hold_hours=24)
    kw = dict(opened_at=NOW - timedelta(hours=1), now=NOW, trader_last_activity=None)
    assert exit_reason(lim, entry_price=1, price=0.79, peak_price=1, **kw).startswith("stop_loss")
    assert exit_reason(lim, entry_price=1, price=2.1, peak_price=2.1, **kw).startswith("take_profit")
    assert exit_reason(lim, entry_price=1, price=1.3, peak_price=1.9, **kw).startswith("trailing_stop")
    assert exit_reason(lim, entry_price=1, price=1.0, peak_price=1, opened_at=NOW - timedelta(hours=25),
                       now=NOW, trader_last_activity=None).startswith("max_hold")
    assert exit_reason(lim, entry_price=1, price=1.05, peak_price=1.1, **kw) is None
