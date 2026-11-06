"""End-to-end copy-engine scenarios (paper executor, fake market + RPC)."""
import time
from datetime import datetime, timezone

import pytest
from helpers import TOKEN, TOKEN2, buy_with_sol, make_tx, sell_for_sol
from sqlalchemy import select

from fomo_copytrader.chain.parser import parse_transaction
from fomo_copytrader.constants import USDC_MINT
from fomo_copytrader.models import CopyOrder, Position, TraderEvent
from fomo_copytrader.schemas import ExecutionResult, Side

FEE_USD = 105_000 / 1e9 * 150  # base + priority lamports at $150/SOL


async def feed(rt, tx):
    rt.monitor.rpc.push(tx)
    return await rt.monitor.poll_once()


async def all_rows(rt, model):
    async with rt.sm() as s:
        return list((await s.execute(select(model).order_by(model.id))).scalars())


def sent(rt, title):
    return [m for m in rt.notifier.sent if f"<b>{title}</b>" in m]


async def test_buy_is_copied_with_costs_in_basis(rt):
    await feed(rt, buy_with_sol(2.0, 120_000 * 10**6))  # $300 at $0.0025
    [pos] = await all_rows(rt, Position)
    [order] = await all_rows(rt, CopyOrder)
    [ev] = await all_rows(rt, TraderEvent)
    assert ev.kind == "BUY" and ev.copy_status == "copied"
    assert abs(ev.price_usd - 0.0025) < 1e-12 and abs(ev.notional_usd - 300) < 1e-6
    assert order.status == "filled" and order.side == "BUY" and order.mode == "paper"
    impact = 25 / 250_000
    expected_tokens = 25 * (1 - impact) / 0.0025 * (1 - 0.005)
    assert abs(pos.my_amount - expected_tokens) < 1e-3
    assert abs(pos.my_cost_basis_usd - (25 + FEE_USD)) < 1e-9
    assert pos.my_entry_price_usd > 0.0025  # costs make our entry worse than the trader's
    assert pos.trader_current_amount == 120_000
    msg = sent(rt, "COPY TRADE ALERT")[0]
    assert "Original entry: $0.0025" in msg and "Execution difference: +" in msg


async def test_duplicate_delivery_executes_once(rt):
    tx = buy_with_sol(2.0, 120_000 * 10**6)
    await feed(rt, tx)
    # websocket redelivery + direct replay of the same parsed events
    rt.monitor._seen.clear()
    await rt.monitor.process_signature(tx["transaction"]["signatures"][0])
    for ev in parse_transaction(tx, rt.monitor.wallet):
        assert await rt.engine.handle_event(ev) is None
    assert len(await all_rows(rt, CopyOrder)) == 1
    assert len(await all_rows(rt, TraderEvent)) == 1


async def test_partial_then_full_sell_proportional_and_net_pnl(rt, market):
    await feed(rt, buy_with_sol(2.0, 120_000 * 10**6))
    [pos] = await all_rows(rt, Position)
    held_raw, basis = int(pos.my_amount_raw), pos.my_cost_basis_usd

    await feed(rt, sell_for_sol(1.0, pre_tokens=120_000 * 10**6, tokens_in=60_000 * 10**6))  # trader sells 50%
    [pos] = await all_rows(rt, Position)
    assert pos.status == "open"
    assert int(pos.my_amount_raw) == held_raw - int(held_raw * 0.5)
    sell1 = (await all_rows(rt, CopyOrder))[1]
    assert sell1.side == "SELL" and abs(sell1.requested_fraction - 0.5) < 1e-12
    # P/L = proceeds - exit network fee - half the basis (which already holds entry costs)
    assert abs(sell1.realized_pnl_usd - (sell1.notional_usd - FEE_USD - basis / 2)) < 1e-6
    assert sell1.realized_pnl_usd < 0  # flat price: costs make it a loss, never shown as profit

    market.set_price(TOKEN, 0.004)
    await feed(rt, sell_for_sol(1.6, pre_tokens=60_000 * 10**6, tokens_in=60_000 * 10**6))
    [pos] = await all_rows(rt, Position)
    assert pos.status == "closed" and pos.my_amount_raw == "0" and pos.exit_reason == "copy_sell"
    orders = await all_rows(rt, CopyOrder)
    assert abs(pos.realized_pnl_usd - sum(o.realized_pnl_usd for o in orders if o.side == "SELL")) < 1e-9
    assert pos.realized_pnl_usd > 0
    assert sent(rt, "COPY TRADE CLOSED")


async def test_delayed_signal_is_skipped(rt):
    await feed(rt, buy_with_sol(2.0, 120_000 * 10**6, block_time=time.time() - 900))
    [ev] = await all_rows(rt, TraderEvent)
    assert ev.copy_status == "skipped" and "signal too old" in ev.copy_note
    assert await all_rows(rt, CopyOrder) == []


async def test_insufficient_liquidity_is_skipped(rt, market):
    market.markets[TOKEN].liquidity_usd = 8_000
    await feed(rt, buy_with_sol(2.0, 120_000 * 10**6))
    [ev] = await all_rows(rt, TraderEvent)
    assert ev.copy_status == "skipped" and "liquidity" in ev.copy_note


async def test_price_moved_too_far_is_skipped(rt, market):
    market.set_price(TOKEN, 0.0031)  # +24% since trader's $0.0025 entry
    await feed(rt, buy_with_sol(2.0, 120_000 * 10**6))
    [ev] = await all_rows(rt, TraderEvent)
    assert ev.copy_status == "skipped" and "price already moved" in ev.copy_note


async def test_failed_trader_tx_recorded_not_copied(rt):
    await feed(rt, make_tx(err={"InstructionError": [3, "Custom"]}))
    [ev] = await all_rows(rt, TraderEvent)
    assert ev.kind == "FAILED" and ev.copy_status == "ignored"


async def test_sell_of_uncopied_token_is_ignored(rt):
    await feed(rt, sell_for_sol(1.0, pre_tokens=10**9, tokens_in=10**9, mint=TOKEN2))
    [ev] = await all_rows(rt, TraderEvent)
    assert ev.copy_status == "ignored" and "no copied position" in ev.copy_note


async def test_execution_failures_suspend_copying(rt):
    class FailingExec:
        mode = "paper"

        async def buy(self, *a):
            return ExecutionResult(False, Side.BUY, USDC_MINT, TOKEN, error="Blockhash not found")

        async def sell(self, *a):
            return ExecutionResult(False, Side.SELL, TOKEN, USDC_MINT, error="Blockhash not found")

    rt.engine.executor = FailingExec()  # e.g. RPC rejects every transaction
    for _ in range(3):
        await feed(rt, buy_with_sol(2.0, 120_000 * 10**6))
    st = await rt.state.status()
    assert st["paused"] and "consecutive" in st["suspended_reason"]
    assert [o.status for o in await all_rows(rt, CopyOrder)] == ["failed"] * 3
    assert len(sent(rt, "TRANSACTION FAILED")) == 3 and sent(rt, "COPY TRADING SUSPENDED")
    # 4th signal is not even attempted
    await feed(rt, buy_with_sol(2.0, 120_000 * 10**6))
    assert len(await all_rows(rt, CopyOrder)) == 3


async def test_paused_still_mirrors_exits(rt):
    await feed(rt, buy_with_sol(2.0, 120_000 * 10**6))
    await rt.state.update_status(paused=True)
    await feed(rt, buy_with_sol(2.0, 100 * 10**6, mint=TOKEN2))  # new entry blocked
    await feed(rt, sell_for_sol(1.0, pre_tokens=120_000 * 10**6, tokens_in=120_000 * 10**6))  # exit mirrored
    positions = await all_rows(rt, Position)
    assert len(positions) == 1 and positions[0].status == "closed"


async def test_failed_exit_is_retried_by_position_monitor(rt, market):
    await feed(rt, buy_with_sol(2.0, 120_000 * 10**6))
    market.quote_fail.add(TOKEN)
    await feed(rt, sell_for_sol(1.0, pre_tokens=120_000 * 10**6, tokens_in=120_000 * 10**6))
    [pos] = await all_rows(rt, Position)
    assert pos.status == "open" and pos.pending_exit_fraction == 1.0
    market.quote_fail.discard(TOKEN)
    await rt.positions.run_once()
    [pos] = await all_rows(rt, Position)
    assert pos.status == "closed"
    assert [o.status for o in await all_rows(rt, CopyOrder)] == ["filled", "failed", "filled"]


async def test_stop_loss_without_trader_exit(rt, market):
    await feed(rt, buy_with_sol(2.0, 120_000 * 10**6))
    market.set_price(TOKEN, 0.0015)  # -40%
    await rt.positions.run_once()
    [pos] = await all_rows(rt, Position)
    assert pos.status == "closed" and pos.exit_reason == "stop_loss" and pos.realized_pnl_usd < 0
    assert sent(rt, "RISK LIMIT REACHED")


async def test_price_move_alert(rt, market):
    await feed(rt, buy_with_sol(2.0, 120_000 * 10**6))
    market.set_price(TOKEN, 0.0030)
    await rt.positions.run_once()
    assert sent(rt, "SIGNIFICANT PRICE MOVE")


async def test_emergency_stop_flattens_and_blocks(rt):
    await feed(rt, buy_with_sol(2.0, 120_000 * 10**6))
    await feed(rt, buy_with_sol(2.0, 250 * 10**6, mint=TOKEN2))  # $300 at $1.2
    assert len([p for p in await all_rows(rt, Position) if p.status == "open"]) == 2
    closed = await rt.engine.emergency_stop(flatten=True)
    assert closed == 2
    assert all(p.status == "closed" for p in await all_rows(rt, Position))
    await feed(rt, buy_with_sol(2.0, 120_000 * 10**6))
    ev = (await all_rows(rt, TraderEvent))[-1]
    assert ev.copy_status == "skipped" and "emergency stop" in ev.copy_note


async def test_daily_loss_limit_blocks_new_entries(rt, market):
    lim = await rt.state.limits()
    await rt.state.set_limits(lim.model_copy(update={"max_daily_loss_usd": 5, "stop_loss_pct": 50}))
    await feed(rt, buy_with_sol(2.0, 120_000 * 10**6))
    market.set_price(TOKEN, 0.0015)
    await feed(rt, sell_for_sol(1.0, pre_tokens=120_000 * 10**6, tokens_in=120_000 * 10**6))  # ~-40% => -$10
    market.set_price(TOKEN, 0.0025)
    await feed(rt, buy_with_sol(2.0, 120_000 * 10**6))
    ev = (await all_rows(rt, TraderEvent))[-1]
    assert ev.copy_status == "skipped" and "daily loss" in ev.copy_note


async def test_monitor_only_mode_records_but_does_not_copy(rt):
    await rt.state.update_status(copying=False)
    await feed(rt, buy_with_sol(2.0, 120_000 * 10**6))
    [ev] = await all_rows(rt, TraderEvent)
    assert ev.copy_status == "ignored" and await all_rows(rt, CopyOrder) == []
    assert sent(rt, "TRADER BUY")


async def test_monitor_processes_in_order_and_retries_unavailable_tx(rt):
    rpc = rt.monitor.rpc
    b = buy_with_sol(2.0, 120_000 * 10**6)
    s = sell_for_sol(1.0, pre_tokens=120_000 * 10**6, tokens_in=120_000 * 10**6)
    rpc.push(b)
    rpc.push(s)
    rpc.missing_once.add(b["transaction"]["signatures"][0])  # RPC lags behind the notification
    assert await rt.monitor.poll_once() == 2
    kinds = [e.kind for e in await all_rows(rt, TraderEvent)]
    assert kinds == ["BUY", "SELL_FULL"]
    assert (await all_rows(rt, Position))[0].status == "closed"
    assert await rt.monitor.poll_once() == 0  # cursor persisted


async def test_reconcile_detects_stale_pending_order(rt):
    from datetime import timedelta

    from fomo_copytrader.engine.reconcile import reconcile
    async with rt.sm() as s:
        s.add(CopyOrder(idempotency_key="x", side="BUY", reason="copy_buy", token_mint=TOKEN, status="pending",
                        created_at=datetime.now(timezone.utc) - timedelta(minutes=30)))
        await s.commit()
    issues = await reconcile(rt.engine)
    assert any("stale" in i for i in issues)
    assert (await all_rows(rt, CopyOrder))[0].status == "unknown"


async def test_report_contains_costs(rt, market):
    from fomo_copytrader.engine.metrics import performance_report_md, portfolio_summary
    await feed(rt, buy_with_sol(2.0, 120_000 * 10**6))
    market.set_price(TOKEN, 0.003)
    await feed(rt, sell_for_sol(1.0, pre_tokens=120_000 * 10**6, tokens_in=120_000 * 10**6))
    summ = await portfolio_summary(rt.sm, 1000, FEE_USD)
    assert summ["closed_positions"] == 1 and summ["total_fees_usd"] == pytest.approx(2 * FEE_USD)
    md = await performance_report_md(rt.sm, 1000, FEE_USD, "paper")
    assert "net of entry fees" in md and "BONKX" in md


async def test_leader_lock_semantics():
    from fomo_copytrader.coordination import Coordinator

    class FakeRedis:
        def __init__(self):
            self.kv = {}

        async def set(self, k, v, nx=False, px=None, ex=None):
            if nx and k in self.kv:
                return None
            self.kv[k] = v
            return True

        async def eval(self, script, n, key, ident, *a):
            if "pexpire" in script:
                return 1 if self.kv.get(key) == ident else 0
            if self.kv.get(key) == ident:
                del self.kv[key]
            return 1

        async def delete(self, k):
            self.kv.pop(k, None)

        async def aclose(self):
            pass

    shared = FakeRedis()
    a, b = Coordinator(None), Coordinator(None)
    for c in (a, b):
        c.redis, c.is_leader = shared, False
    assert await a.acquire_or_renew() is True
    assert await b.acquire_or_renew() is False      # second replica stays on standby
    assert await a.acquire_or_renew() is True       # renewal
    assert await a.first_seen("sig1") and not await b.first_seen("sig1")
    await a.close()
    assert await b.acquire_or_renew() is True       # failover after release
