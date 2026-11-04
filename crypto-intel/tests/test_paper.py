from datetime import datetime, timedelta, timezone

import pytest

from cryptointel.paper.engine import PaperBroker
from cryptointel.risk.leverage import CostModel

ZERO = CostModel(taker_fee=0, maker_fee=0, slippage_bps=0, mmr=0.005)


def broker(costs=ZERO):
    return PaperBroker(10_000, costs, max_open=2)


def test_open_sizes_by_risk_and_blocks_duplicates():
    b = broker()
    t = b.open(symbol="BTCUSDT", side="long", price=100, stop=95, take_profits=[110, 120], leverage=3, risk_pct=0.01)
    assert t.qty == pytest.approx(20)  # 100 USDT risk / 5 per unit
    assert b.open(symbol="BTCUSDT", side="long", price=100, stop=95, take_profits=[110], leverage=3, risk_pct=0.01) is None


def test_partial_tp_then_breakeven_stop():
    b = broker()
    b.open(symbol="X", side="long", price=100, stop=95, take_profits=[110, 120], leverage=3, risk_pct=0.01)
    ev = b.on_bar("X", 100, 111, 100, 110)
    assert ev[0]["reason"] == "TP1" and not ev[0]["closed"]
    t = b.open_trades()[0]
    assert t.stop == pytest.approx(100)
    ev = b.on_bar("X", 105, 106, 99, 100)
    assert ev[0]["reason"] == "breakeven stop" and ev[0]["closed"]
    assert b.balance == pytest.approx(10_000 + 10 * 10)  # half (10 units) made +10 each
    assert b.closed_trades()[0].r_multiple == pytest.approx(1.0)


def test_stop_first_when_both_levels_in_bar():
    b = broker()
    b.open(symbol="X", side="short", price=100, stop=105, take_profits=[90], leverage=3, risk_pct=0.01)
    ev = b.on_bar("X", 100, 106, 89, 95)
    assert ev[0]["reason"] == "stop"
    assert b.balance == pytest.approx(10_000 - 100)


def test_fees_and_funding_accounted():
    b = broker(CostModel(taker_fee=0.001, maker_fee=0.0005, slippage_bps=0))
    t = b.open(symbol="X", side="long", price=100, stop=95, take_profits=[110], leverage=3, risk_pct=0.01)
    b.apply_funding("X", 0.001, datetime.now(timezone.utc) + timedelta(hours=1))
    assert t.funding == pytest.approx(t.qty * 100 * 0.001)
    b.on_bar("X", 100, 111, 100, 110)
    closed = b.closed_trades()[0]
    expected = 10 * t.qty - 100 * t.qty * 0.001 - 110 * t.qty * 0.0005 - t.qty * 100 * 0.001
    assert closed.realized_pnl == pytest.approx(expected)
    assert b.balance == pytest.approx(10_000 + expected)


def test_liquidation_when_liq_precedes_stop():
    b = broker()
    t = b.open(symbol="X", side="long", price=100, stop=80, take_profits=[150], leverage=20, risk_pct=0.01)
    assert t.liq_price > 80
    ev = b.on_bar("X", 100, 100, 90, 92)
    assert "LIQUIDATION" in ev[0]["reason"]


def test_performance_report():
    b = broker()
    b.open(symbol="X", side="long", price=100, stop=95, take_profits=[110], leverage=3, risk_pct=0.01)
    b.on_bar("X", 100, 101, 94, 95)
    p = b.performance()
    assert p["n_trades"] == 1 and p["win_rate_pct"] == 0 and p["max_drawdown_pct"] < 0
    assert "sharpe" not in p
