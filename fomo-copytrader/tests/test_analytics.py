from datetime import datetime, timedelta, timezone

from helpers import TOKEN, TOKEN2, TRADER

from fomo_copytrader.constants import WSOL_MINT
from fomo_copytrader.schemas import EventKind, SwapEvent
from fomo_copytrader.trader.analytics import analyse, build_round_trips, max_drawdown

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
n = 0


def ev(kind, mint, amt, sol, minutes, pre=0.0, post=0.0):
    global n
    n += 1
    return SwapEvent(signature=f"s{n}", wallet=TRADER, slot=n, block_time=T0 + timedelta(minutes=minutes),
                     kind=kind, token_mint=mint, token_amount=amt, token_pre_balance=pre, token_post_balance=post,
                     quote_mint=WSOL_MINT, quote_amount=sol, price_in_quote=sol / amt)


def test_round_trips_with_partial_exits():
    evs = [ev(EventKind.BUY, TOKEN, 100, 1.0, 0), ev(EventKind.SELL_PARTIAL, TOKEN, 50, 1.0, 30, 100, 50),
           ev(EventKind.SELL_FULL, TOKEN, 50, 0.25, 60, 50, 0)]
    [t], open_ = build_round_trips(evs)
    assert not open_
    assert abs(t.pnl_quote - 0.25) < 1e-12 and abs(t.return_pct - 25) < 1e-9
    assert t.hold_seconds == 3600 and t.sells == 2


def test_sells_without_observed_entry_excluded():
    trips, _ = build_round_trips([ev(EventKind.SELL_FULL, TOKEN2, 10, 5, 0, 10, 0)])
    assert trips == []


def test_drawdown():
    assert max_drawdown([10, -4, -4, 5, -20, 30])[0] == 23


def test_report_metrics_and_flags():
    evs = []
    m = 0
    for i in range(12):  # 8 winners (+50%), 4 losers (-20%)
        win = i % 3 != 0
        evs.append(ev(EventKind.BUY, TOKEN, 100, 1.0, m))
        evs.append(ev(EventKind.SELL_FULL, TOKEN, 100, 1.5 if win else 0.8, m + 0.5, 100, 0))
        m += 120
    r = analyse(TRADER, evs, {WSOL_MINT: 150.0}, latency_penalty_pct=2)
    assert r.closed_trades == 12 and r.win_rate_pct == 66.7
    assert r.avg_win_pct == 50 and r.avg_loss_pct == -20
    assert r.largest_win_usd == 75 and r.largest_loss_usd == -30
    assert r.median_hold_minutes == 0.5
    assert any("small sample" in f for f in r.red_flags)
    assert any("median hold under 2 minutes" in f for f in r.red_flags)
    assert any("concentrated in one token" in f for f in r.red_flags)
    assert r.copyability["estimated_copy_avg_return_pct"] < r.copyability["trader_avg_return_pct"]
    assert 0 <= r.score <= 100
