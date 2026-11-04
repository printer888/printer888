"""Command-line interface.

  python -m cryptointel.cli serve                       # API + dashboard + background monitor
  python -m cryptointel.cli scan                        # one scan, print opportunities
  python -m cryptointel.cli backtest BTCUSDT --tf 1h --strategy trend_pullback --mode walk_forward --days 365
  python -m cryptointel.cli backtest BTCUSDT --csv data.csv ...   # offline OHLCV (ts,open,high,low,close,volume)
  python -m cryptointel.cli ml BTCUSDT --tf 1h
  python -m cryptointel.cli leverage --entry 100 --stop 97 --targets 106 109
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta

import pandas as pd

from .config import get_settings
from .data.freshness import utcnow
from .db.repository import _clean
from .logging_setup import setup_logging


def _print(obj) -> None:
    print(json.dumps(_clean(obj), indent=2, default=str))


def cmd_serve(a) -> None:
    import uvicorn

    uvicorn.run("cryptointel.api.main:app", host=a.host, port=a.port, log_level="info")


def cmd_scan(a) -> None:
    from .services.monitor import IntelligenceService

    svc = IntelligenceService(get_settings())
    svc.scan()
    rows = sorted(svc.opportunities.values(), key=lambda o: (o["status"] != "SIGNAL", -o["score"]))
    for o in rows:
        print(f"{o['symbol']:<12} {o['status']:<9} long {o['score_long']:5.1f}  short {o['score_short']:5.1f}  "
              f"{o['headline']}")
        for g in o["gate_failures"][:3]:
            print(f"{'':14}- {g}")
    if svc.errors:
        print("\nErrors:", *[f"  {e['where']}: {e['error']}" for e in svc.errors[-10:]], sep="\n")


def _load(a, settings) -> tuple[pd.DataFrame, pd.Series | None]:
    if a.csv:
        df = pd.read_csv(a.csv, parse_dates=["ts"]).set_index("ts")
        df.index = pd.to_datetime(df.index, utc=True)
        return df[["open", "high", "low", "close", "volume"]].astype(float), None
    from .data.bybit_client import BybitClient

    c = BybitClient(settings.bybit_rest_url, settings.http_timeout, settings.max_requests_per_second)
    end = utcnow()
    start = end - timedelta(days=a.days)
    df = c.klines_range(a.symbol, a.tf, int(start.timestamp() * 1000), int(end.timestamp() * 1000))
    funding = None
    try:
        frames, cursor = [], int(end.timestamp() * 1000)
        while cursor > start.timestamp() * 1000:
            f = c.funding_history(a.symbol, 200, int(start.timestamp() * 1000), cursor)
            if f.empty:
                break
            frames.append(f)
            cursor = int(f.index[0].timestamp() * 1000) - 1
        funding = pd.concat(frames).sort_index() if frames else None
    except Exception as e:
        print(f"funding history unavailable ({e}); using constant assumption", file=sys.stderr)
    return df, funding


def cmd_backtest(a) -> None:
    from .backtest.engine import BacktestConfig, run_backtest
    from .backtest.strategies import PARAM_GRIDS, STRATEGIES
    from .backtest.walkforward import holdout_test, walk_forward

    s = get_settings()
    df, funding = _load(a, s)
    print(f"{len(df)} bars {df.index[0]} → {df.index[-1]}", file=sys.stderr)
    cfg = BacktestConfig(timeframe=a.tf, initial_equity=s.paper_starting_equity, risk_per_trade=s.risk_per_trade,
                         max_leverage=s.paper_leverage, taker_fee=s.taker_fee, maker_fee=s.maker_fee,
                         slippage_bps=s.slippage_bps, funding_series=funding)
    cls = STRATEGIES[a.strategy]
    if a.mode == "single":
        res = run_backtest(df, cls(), cfg, trade_start=250).summary()
    elif a.mode == "walk_forward":
        n = len(df)
        train = max(int((n - 250) * 0.5), 300)
        res = walk_forward(df, cls, PARAM_GRIDS[a.strategy], cfg, train, max(int((n - 250 - train) / 4), 100))
        res.pop("oos_equity", None)
    else:
        res = holdout_test(df, cls, PARAM_GRIDS[a.strategy], cfg)
    res.pop("trades", None)
    _print(res)


def cmd_ml(a) -> None:
    from .data.bybit_client import BybitClient
    from .ml.model import evaluate

    s = get_settings()
    df = BybitClient(s.bybit_rest_url).klines(a.symbol, a.tf, limit=1000)
    _print(evaluate(df, horizon=a.horizon, cost=2 * (s.taker_fee + s.slippage_bps / 1e4)))


def cmd_leverage(a) -> None:
    from .risk.leverage import CostModel, compare_leverage

    s = get_settings()
    r = compare_leverage(equity=a.equity, side=a.side, entry=a.entry, stop=a.stop, targets=a.targets,
                         risk_pct=a.risk, funding_rate=a.funding, funding_intervals=a.intervals,
                         costs=CostModel(s.taker_fee, s.maker_fee, s.slippage_bps, s.default_mmr))
    print(f"{'lev':>4} {'mode':>7} {'notional':>11} {'margin':>9} {'liq':>11} {'loss@stop':>10} {'RR':>12}  status")
    for mode in ("fixed_risk", "fixed_margin"):
        for x in r[mode]:
            rr = "/".join(f"{v:.2f}" for v in x["rr_at_targets"])
            st = "LIQ BEFORE STOP" if x["liquidation_before_stop"] else "ok"
            print(f"{x['leverage']:>4}x {mode[6:]:>7} {x['notional']:>11.2f} {x['margin']:>9.2f} "
                  f"{x['liquidation_price']:>11.4f} {x['loss_at_stop']:>10.2f} {rr:>12}  {st}")
    print(*["- " + l for l in r["lessons"]], sep="\n")


def main(argv=None) -> None:
    setup_logging(get_settings().log_level)
    p = argparse.ArgumentParser(prog="cryptointel")
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("serve")
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=8000)
    sp.set_defaults(fn=cmd_serve)
    sub.add_parser("scan").set_defaults(fn=cmd_scan)
    bp = sub.add_parser("backtest")
    bp.add_argument("symbol")
    bp.add_argument("--tf", default="1h", choices=["15m", "1h", "4h", "1d"])
    bp.add_argument("--strategy", default="trend_pullback",
                    choices=["trend_pullback", "donchian_breakout", "bollinger_reversion"])
    bp.add_argument("--mode", default="walk_forward", choices=["single", "walk_forward", "holdout"])
    bp.add_argument("--days", type=int, default=365)
    bp.add_argument("--csv", help="offline OHLCV CSV instead of Bybit download")
    bp.set_defaults(fn=cmd_backtest)
    mp = sub.add_parser("ml")
    mp.add_argument("symbol")
    mp.add_argument("--tf", default="1h")
    mp.add_argument("--horizon", type=int, default=12)
    mp.set_defaults(fn=cmd_ml)
    lp = sub.add_parser("leverage")
    lp.add_argument("--equity", type=float, default=10_000)
    lp.add_argument("--side", default="long", choices=["long", "short"])
    lp.add_argument("--entry", type=float, required=True)
    lp.add_argument("--stop", type=float, required=True)
    lp.add_argument("--targets", type=float, nargs="+", required=True)
    lp.add_argument("--risk", type=float, default=0.01)
    lp.add_argument("--funding", type=float, default=0.0001)
    lp.add_argument("--intervals", type=float, default=3)
    lp.set_defaults(fn=cmd_leverage)
    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
