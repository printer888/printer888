"""Walk-forward optimisation and untouched out-of-sample holdout validation."""
from __future__ import annotations

import itertools
import math

import pandas as pd

from ..indicators.ta import PERIODS_PER_YEAR
from .engine import BIAS_NOTES, BacktestConfig, run_backtest
from .metrics import buy_and_hold, performance

WARMUP_BARS = 250  # enough history for EMA200/ADX before evaluation begins


def param_grid(space: dict[str, list]) -> list[dict]:
    keys = list(space)
    return [dict(zip(keys, vals)) for vals in itertools.product(*(space[k] for k in keys))]


def _objective(m: dict, min_trades: int) -> float:
    if m.get("n_trades", 0) < min_trades or m.get("sharpe") is None:
        return -math.inf
    return m["sharpe"]


def optimise(df: pd.DataFrame, strategy_cls, grid: list[dict], cfg: BacktestConfig, start: int, end: int,
             min_trades: int = 8) -> tuple[dict | None, dict | None, list[dict]]:
    w0 = max(0, start - WARMUP_BARS)
    sl = df.iloc[w0:end]
    table = []
    for params in grid:
        res = run_backtest(sl, strategy_cls(**params), cfg, trade_start=start - w0)
        table.append({"params": params, "metrics": res.metrics, "objective": _objective(res.metrics, min_trades)})
    table.sort(key=lambda r: r["objective"], reverse=True)
    if not table or table[0]["objective"] == -math.inf:
        return None, None, table
    return table[0]["params"], table[0]["metrics"], table


def walk_forward(df: pd.DataFrame, strategy_cls, space: dict[str, list], cfg: BacktestConfig,
                 train_bars: int = 2000, test_bars: int = 500, min_trades: int = 8) -> dict:
    grid = param_grid(space)
    folds, oos_trades, oos_parts = [], [], []
    start = WARMUP_BARS
    eq_level = cfg.initial_equity
    while start + train_bars + test_bars <= len(df):
        tr_s, tr_e, te_e = start, start + train_bars, start + train_bars + test_bars
        best, is_metrics, _ = optimise(df, strategy_cls, grid, cfg, tr_s, tr_e, min_trades)
        fold = {"train": [df.index[tr_s].isoformat(), df.index[tr_e - 1].isoformat()],
                "test": [df.index[tr_e].isoformat(), df.index[te_e - 1].isoformat()],
                "best_params": best, "in_sample": is_metrics}
        w0 = max(0, tr_e - WARMUP_BARS)
        if best is None:
            fold["out_of_sample"] = None
            fold["note"] = "no parameter set met the minimum-trade requirement in-sample; stayed flat"
            flat = pd.Series(eq_level, index=df.index[tr_e:te_e])
            oos_parts.append(flat)
        else:
            res = run_backtest(df.iloc[w0:te_e], strategy_cls(**best), cfg, trade_start=tr_e - w0)
            fold["out_of_sample"] = res.metrics
            oos_trades += res.trades
            part = res.equity / cfg.initial_equity * eq_level
            eq_level = float(part.iloc[-1])
            oos_parts.append(part)
        folds.append(fold)
        start += test_bars
    ppy = PERIODS_PER_YEAR.get(cfg.timeframe, 365)
    if not folds:
        return {"error": f"not enough data: need ≥ {WARMUP_BARS + train_bars + test_bars} bars, have {len(df)}"}
    oos_eq = pd.concat(oos_parts)
    oos_eq = oos_eq[~oos_eq.index.duplicated(keep="last")]
    oos_metrics = performance(oos_eq, oos_trades, ppy)
    first_test = WARMUP_BARS + train_bars
    bench = buy_and_hold(df.iloc[first_test: first_test + len(oos_eq)], cfg.initial_equity, cfg.taker_fee,
                         cfg.slippage_bps)
    is_sharpes = [f["in_sample"]["sharpe"] for f in folds if f.get("in_sample") and f["in_sample"].get("sharpe")]
    oos_sharpes = [f["out_of_sample"]["sharpe"] for f in folds if f.get("out_of_sample") and f["out_of_sample"].get("sharpe") is not None]
    profitable = sum(1 for f in folds if f.get("out_of_sample") and (f["out_of_sample"].get("total_return_pct") or 0) > 0)
    verdict = []
    if (oos_metrics.get("total_return_pct") or 0) <= 0:
        verdict.append("FAILED: strategy lost money out-of-sample after costs.")
    bm = performance(bench, [], ppy)
    if (oos_metrics.get("total_return_pct") or 0) < (bm.get("total_return_pct") or 0):
        verdict.append("Underperformed spot buy-and-hold over the same out-of-sample period.")
    if is_sharpes and oos_sharpes and sum(is_sharpes) / len(is_sharpes) > 0:
        ratio = (sum(oos_sharpes) / len(oos_sharpes)) / (sum(is_sharpes) / len(is_sharpes))
        if ratio < 0.5:
            verdict.append(f"OOS/IS Sharpe ratio {ratio:.2f} — strong degradation; likely overfit.")
    else:
        ratio = None
    if not verdict:
        verdict.append("Positive OOS result; still subject to regime change and the biases noted.")
    return {
        "strategy": strategy_cls.name, "parameter_combinations_tested_per_fold": len(grid),
        "folds": folds, "out_of_sample_metrics": oos_metrics, "benchmark_buy_and_hold": bm,
        "profitable_folds": f"{profitable}/{len(folds)}", "oos_is_sharpe_ratio": ratio,
        "verdict": verdict, "notes": BIAS_NOTES,
        "oos_equity": [{"t": t.isoformat(), "v": float(v)} for t, v in oos_eq.iloc[:: max(1, len(oos_eq) // 500)].items()],
        "trades": oos_trades[-200:],
    }


def holdout_test(df: pd.DataFrame, strategy_cls, space: dict[str, list], cfg: BacktestConfig,
                 holdout_frac: float = 0.3, min_trades: int = 8) -> dict:
    """Optimise on the first (1-holdout_frac) of data, evaluate ONCE on the untouched remainder."""
    split = int(len(df) * (1 - holdout_frac))
    if split - WARMUP_BARS < 500:
        return {"error": "not enough data for a meaningful in-sample period"}
    grid = param_grid(space)
    best, is_metrics, _ = optimise(df, strategy_cls, grid, cfg, WARMUP_BARS, split, min_trades)
    if best is None:
        return {"strategy": strategy_cls.name, "verdict": ["No parameter set produced enough in-sample trades."],
                "parameter_combinations_tested": len(grid)}
    w0 = max(0, split - WARMUP_BARS)
    res = run_backtest(df.iloc[w0:], strategy_cls(**best), cfg, trade_start=split - w0)
    verdict = []
    if (res.metrics.get("total_return_pct") or 0) <= 0:
        verdict.append("FAILED on untouched holdout after costs.")
    if (res.metrics.get("total_return_pct") or 0) < (res.benchmark_metrics.get("total_return_pct") or 0):
        verdict.append("Underperformed spot buy-and-hold on holdout.")
    return {
        "strategy": strategy_cls.name, "parameter_combinations_tested": len(grid), "best_params": best,
        "in_sample": is_metrics, "holdout": res.metrics, "benchmark_buy_and_hold": res.benchmark_metrics,
        "holdout_period": [df.index[split].isoformat(), df.index[-1].isoformat()],
        "verdict": verdict or ["Positive on holdout; not a guarantee of future performance."],
        "notes": BIAS_NOTES, "trades": res.trades[-200:],
    }
