import pandas as pd
import pytest

from cryptointel.backtest.engine import BacktestConfig, Order, run_backtest
from cryptointel.backtest.metrics import buy_and_hold, max_drawdown, performance
from cryptointel.backtest.strategies import PARAM_GRIDS, STRATEGIES, DonchianBreakout, TrendPullback
from cryptointel.backtest.walkforward import holdout_test, param_grid, walk_forward


class Never:
    name, params = "never", {}

    def prepare(self, df):
        return df

    def signal(self, df, i):
        return None


class OnceAt:
    """Go long at bar k with fixed stop/target; records how much data it saw."""

    name, params = "once", {}

    def __init__(self, k, stop, target):
        self.k, self.stop, self.target, self.seen = k, stop, target, []

    def prepare(self, df):
        return df

    def signal(self, df, i):
        self.seen.append(len(df))
        return Order("long", self.stop, self.target) if i == self.k else None


def _bars(rows):
    idx = pd.date_range("2025-01-01", periods=len(rows), freq="h", tz="UTC")
    return pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"], index=idx)


def test_no_trades_keeps_equity_flat(synth):
    r = run_backtest(synth(300), Never(), BacktestConfig())
    assert r.metrics["n_trades"] == 0
    assert r.equity.iloc[-1] == pytest.approx(10_000)


def test_strategy_only_sees_past_rows(synth):
    s = OnceAt(-1, 0, 0)
    run_backtest(synth(100), s, BacktestConfig())
    assert all(seen == i + 1 for i, seen in enumerate(s.seen))


def test_fill_next_open_and_stop_first_when_ambiguous():
    rows = [[100, 101, 99, 100, 1]] * 3 + [[102, 103, 101, 102, 1], [102, 120, 80, 100, 1], [100, 101, 99, 100, 1]]
    cfg = BacktestConfig(taker_fee=0, maker_fee=0, slippage_bps=0, funding_rate_per_interval=0)
    r = run_backtest(_bars(rows), OnceAt(2, 95, 110), cfg)
    t = r.trades[0]
    assert t["entry"] == pytest.approx(102)  # next bar open, not signal-bar close
    assert t["exit_reason"] == "stop"  # bar 4 touched both 95 and 110 → pessimistic
    assert t["exit"] == pytest.approx(95)


def test_gap_through_stop_fills_at_open():
    rows = [[100, 101, 99, 100, 1]] * 3 + [[100, 101, 99, 100, 1], [90, 91, 89, 90, 1], [90, 91, 89, 90, 1]]
    cfg = BacktestConfig(taker_fee=0, maker_fee=0, slippage_bps=0, funding_rate_per_interval=0)
    r = run_backtest(_bars(rows), OnceAt(2, 95, 110), cfg)
    assert r.trades[0]["exit"] == pytest.approx(90) and r.trades[0]["exit_reason"] == "stop (gap)"


def test_risk_sizing_and_costs():
    rows = [[100, 101, 99, 100, 1]] * 3 + [[100, 101, 99.5, 100, 1], [100, 111, 99.5, 110, 1], [110, 111, 109, 110, 1]]
    cfg = BacktestConfig(taker_fee=0.001, maker_fee=0.0005, slippage_bps=0, funding_rate_per_interval=0,
                         max_leverage=100)
    r = run_backtest(_bars(rows), OnceAt(2, 95, 110), cfg)
    t = r.trades[0]
    per_unit = 5 + (100 + 95) * 0.001
    assert t["qty"] == pytest.approx(100 / per_unit)
    expected = (110 - 100) * t["qty"] - 100 * t["qty"] * 0.001 - 110 * t["qty"] * 0.0005
    assert t["pnl"] == pytest.approx(expected)
    assert r.equity.iloc[-1] == pytest.approx(10_000 + expected)


def test_funding_charged_for_longs():
    rows = [[100, 100.5, 99.5, 100, 1]] * 40
    cfg = BacktestConfig(taker_fee=0, maker_fee=0, slippage_bps=0, funding_rate_per_interval=0.001,
                         max_bars_in_trade=30)
    r = run_backtest(_bars(rows), OnceAt(2, 90, 120), cfg)
    assert r.trades[0]["funding"] > 0
    assert r.trades[0]["pnl"] < 0


def test_no_lookahead_by_perturbing_future(synth):
    df = synth(1200, seed=3)
    cfg = BacktestConfig()
    a = run_backtest(df, TrendPullback(), cfg)
    df2 = df.copy()
    df2.iloc[900:, :4] = df2.iloc[900:, :4] * 0.7
    b = run_backtest(df2, TrendPullback(), cfg)
    cut = df.index[899].isoformat()
    ta_ = [t for t in a.trades if t["exit_time"] <= cut]
    tb_ = [t for t in b.trades if t["exit_time"] <= cut]
    assert ta_ == tb_


def test_metrics_basic():
    idx = pd.date_range("2025", periods=5, freq="D", tz="UTC")
    eq = pd.Series([100, 110, 99, 120, 108], index=idx, dtype=float)
    assert max_drawdown(eq) == pytest.approx(-10.0)
    m = performance(eq, [{"pnl": 10, "r_multiple": 1}, {"pnl": -5, "r_multiple": -0.5}], 365)
    assert m["win_rate_pct"] == 50 and m["profit_factor"] == pytest.approx(2.0) and m["expectancy"] == 2.5


def test_benchmark_costs(synth):
    df = synth(10)
    bh = buy_and_hold(df, 1000, 0.001, 0)
    gross = 1000 * df.close.iloc[-1] / df.open.iloc[0]
    assert bh.iloc[-1] < gross


def test_strategies_run_and_grids_small(synth):
    df = synth(1500, seed=7)
    for name, cls in STRATEGIES.items():
        r = run_backtest(df, cls(), BacktestConfig())
        assert "total_return_pct" in r.metrics
        assert len(param_grid(PARAM_GRIDS[name])) <= 16


def test_walk_forward_and_holdout_report_honestly(synth):
    df = synth(2400, seed=11, drift=0.0)
    wf = walk_forward(df, DonchianBreakout, PARAM_GRIDS["donchian_breakout"], BacktestConfig(), 1000, 350, 3)
    assert wf["folds"] and wf["verdict"] and "benchmark_buy_and_hold" in wf
    assert wf["parameter_combinations_tested_per_fold"] == 16
    ho = holdout_test(df, TrendPullback, PARAM_GRIDS["trend_pullback"], BacktestConfig(), 0.3, 3)
    assert "verdict" in ho
    assert any("Survivorship" in n for n in wf["notes"])
