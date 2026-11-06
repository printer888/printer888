"""Command line tools.

  python -m fomo_copytrader.cli analyze <WALLET> [--max-tx 300]   read-only trader evaluation (needs RPC access)
  python -m fomo_copytrader.cli simulate [--out report.md]        offline scenario test of every flow
  python -m fomo_copytrader.cli report                            performance report from the configured DB
"""
from __future__ import annotations

import argparse
import html
import re
import asyncio
import json
import os
import random
import tempfile
import time

from .config import Settings, get_settings


async def cmd_analyze(wallet: str, max_tx: int) -> None:
    from .chain.rpc import SolanaRpc
    from .market.dexscreener import DexScreener
    from .market.jupiter import Jupiter
    from .market.provider import LiveMarketData
    from .trader.analytics import analyse
    from .trader.monitor import fetch_history

    s = get_settings()
    rpc = SolanaRpc(s.solana_rpc_url)
    md = LiveMarketData(DexScreener(s.dexscreener_base_url), Jupiter(s.jupiter_base_url, s.jupiter_api_key))
    events = await fetch_history(rpc, wallet, max_tx=max_tx)
    quotes = {m: await md.price_usd(m) for m in {e.quote_mint for e in events if e.quote_mint}}
    print(json.dumps(analyse(wallet, events, {k: v for k, v in quotes.items() if v}).to_dict(), indent=2, default=str))
    await rpc.close()


async def cmd_report() -> None:
    from .engine.metrics import performance_report_md
    from .runtime import Runtime

    rt = Runtime(get_settings(), enable_ws=False)
    await rt.init()
    lim = await rt.state.limits()
    print(await performance_report_md(rt.sm, lim.total_capital_usd, await rt.engine.est_network_fee_usd(),
                                      rt.executor.mode))
    await rt.db_engine.dispose()


async def cmd_simulate(out: str | None, seed: int) -> str:
    """Drive the real engine through every scenario with a deterministic market."""
    from .engine.metrics import performance_report_md
    from .notify.telegram import Notifier
    from .runtime import Runtime
    from .schemas import RiskLimits
    from .sim import TOKEN, TOKEN2, TRADER, FakeMarket, FakeRpc, buy_with_sol, make_tx, safe_token, sell_for_sol

    rnd = random.Random(seed)
    tmp = tempfile.mkdtemp()
    s = Settings(_env_file=None, app_env="test", database_url=f"sqlite+aiosqlite:///{tmp}/sim.db")
    mk = FakeMarket()
    mk.add_token(TOKEN, 0.0025, symbol="ALPHA")
    mk.add_token(TOKEN2, 1.20, symbol="BETA")
    TOKEN3 = "GAMMAmintZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZ"[:44]
    mk.add_token(TOKEN3, 0.05, symbol="THIN", liquidity=9_000)

    async def safety(m):
        return safe_token(m)

    rpc = FakeRpc()
    rt = Runtime(s, market=mk, rpc=rpc, notifier=Notifier(None, None), safety_inspector=safety, enable_ws=False)
    await rt.init()
    await rt.state.set_limits(RiskLimits(total_capital_usd=1000, fixed_position_usd=25, stop_loss_pct=30))
    await rt.set_trader(TRADER, label="Simulated trader")
    await rt.state.update_status(monitoring=True, copying=True)
    log: list[str] = []

    async def step(desc, tx=None):
        if tx:
            rpc.push(tx)
            await rt.monitor.poll_once()
        await rt.positions.run_once()
        log.append(desc)

    await step("trader buys ALPHA for 2 SOL", buy_with_sol(2.0, 120_000 * 10**6))
    await step("duplicate delivery of the same tx (websocket + poll)")
    rt.monitor._seen.clear()
    await rt.monitor.process_signature(rpc.order[-1])
    for _ in range(5):
        mk.set_price(TOKEN, mk.prices[TOKEN] * (1 + rnd.uniform(-0.03, 0.08)))
        await step(f"ALPHA price tick -> {mk.prices[TOKEN]:.6f}")
    await step("trader sells 50% of ALPHA", sell_for_sol(1.2, 120_000 * 10**6, 60_000 * 10**6))
    await step("trader buys BETA", buy_with_sol(2.0, 250 * 10**6, mint=TOKEN2))
    await step("trader buys THIN (insufficient liquidity)", buy_with_sol(1.0, 3000 * 10**6, mint=TOKEN3))
    await step("delayed BETA signal (15 min old)", buy_with_sol(1.0, 125 * 10**6, mint=TOKEN2,
                                                               block_time=time.time() - 900))
    mk.set_price(TOKEN2, 1.6)
    await step("BETA moved +33% then trader adds (price-drift rejection)", buy_with_sol(1.0, 125 * 10**6, mint=TOKEN2,
                                                                                         pre_tokens=250 * 10**6))
    mk.set_price(TOKEN2, 0.80)
    await step("BETA drops -33% from entry: stop-loss without trader exit")
    await step("trader fails a transaction", make_tx(err={"InstructionError": [2, {"Custom": 6001}]}))
    mk.quote_fail.add(TOKEN)
    await step("trader closes ALPHA but our exit route fails",
               sell_for_sol(1.5, 60_000 * 10**6, 60_000 * 10**6))
    mk.quote_fail.discard(TOKEN)
    await step("route recovers: exit retried by position monitor")
    await step("trader buys ALPHA again", buy_with_sol(2.0, 120_000 * 10**6))
    await rt.engine.emergency_stop(flatten=True, reason="simulation drill")
    await step("emergency stop with flatten")
    await step("signal after emergency stop", buy_with_sol(2.0, 250 * 10**6, mint=TOKEN2))

    lim = await rt.state.limits()
    md = await performance_report_md(rt.sm, lim.total_capital_usd, await rt.engine.est_network_fee_usd(), "simulation")
    md += "\n\n## Scenario steps\n" + "\n".join(f"{i+1}. {d}" for i, d in enumerate(log))
    md += "\n\n## Notifications sent\n" + "\n\n".join(
        "```\n" + html.unescape(re.sub(r"</?[bi]>", "", m)) + "\n```"
        for m in rt.notifier.sent)
    md += ("\n\n_Synthetic market data, deterministic seed. This validates system behaviour, "
           "not trading performance._\n")
    await rt.shutdown()
    if out:
        with open(out, "w", encoding="utf-8") as f:
            f.write(md)
    return md


def main() -> None:
    p = argparse.ArgumentParser(prog="fomo_copytrader")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("analyze")
    a.add_argument("wallet")
    a.add_argument("--max-tx", type=int, default=300)
    sm = sub.add_parser("simulate")
    sm.add_argument("--out")
    sm.add_argument("--seed", type=int, default=7)
    sub.add_parser("report")
    args = p.parse_args()
    if args.cmd == "analyze":
        asyncio.run(cmd_analyze(args.wallet, args.max_tx))
    elif args.cmd == "report":
        asyncio.run(cmd_report())
    else:
        md = asyncio.run(cmd_simulate(args.out, args.seed))
        if not args.out:
            print(md)


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    main()
