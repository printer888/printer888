from helpers import OTHER, TOKEN, TOKEN2, TRADER, buy_with_sol, make_tx, sell_for_sol

from fomo_copytrader.chain.parser import parse_transaction
from fomo_copytrader.constants import USDC_MINT, WSOL_MINT
from fomo_copytrader.schemas import EventKind


def test_buy_with_sol_detects_token_amount_and_price():
    tx = buy_with_sol(2.0, tokens_out=120_000 * 10**6)
    [ev] = parse_transaction(tx, TRADER)
    assert ev.kind == EventKind.BUY
    assert ev.token_mint == TOKEN and ev.quote_mint == WSOL_MINT
    assert ev.token_amount == 120_000
    assert abs(ev.quote_amount - 2.0) < 1e-9          # fee excluded from trade amount
    assert abs(ev.price_in_quote - 2.0 / 120_000) < 1e-15
    assert ev.fee_sol == 5000 / 1e9


def test_pool_accounts_are_ignored():
    tx = buy_with_sol(1.0, tokens_out=10**6)
    [ev] = parse_transaction(tx, TRADER)
    assert ev.token_amount == 1.0  # pool's opposite movement did not leak in


def test_buy_with_usdc_prefers_stable_quote():
    tx = make_tx(tokens=[(USDC_MINT, 6, 500 * 10**6, 400 * 10**6), (TOKEN, 6, None, 40_000 * 10**6)])
    [ev] = parse_transaction(tx, TRADER)
    assert ev.kind == EventKind.BUY and ev.quote_mint == USDC_MINT
    assert ev.quote_amount == 100 and ev.price_in_quote == 100 / 40_000


def test_partial_sell_fraction_from_onchain_balances():
    tx = sell_for_sol(1.0, pre_tokens=100 * 10**6, tokens_in=50 * 10**6)
    [ev] = parse_transaction(tx, TRADER)
    assert ev.kind == EventKind.SELL_PARTIAL
    assert ev.token_pre_balance == 100 and ev.token_post_balance == 50
    assert abs(ev.sell_fraction - 0.5) < 1e-12
    assert abs(ev.quote_amount - 1.0) < 1e-9


def test_full_sell_and_dust_counts_as_full():
    [ev] = parse_transaction(sell_for_sol(1.0, pre_tokens=10**9, tokens_in=10**9), TRADER)
    assert ev.kind == EventKind.SELL_FULL
    [ev2] = parse_transaction(sell_for_sol(1.0, pre_tokens=10**9, tokens_in=10**9 - 10), TRADER)
    assert ev2.kind == EventKind.SELL_FULL  # 10 raw units of dust left


def test_failed_transaction():
    tx = make_tx(err={"InstructionError": [2, {"Custom": 6001}]}, tokens=[(TOKEN, 6, 5, 5)])
    [ev] = parse_transaction(tx, TRADER)
    assert ev.kind == EventKind.FAILED and "6001" in ev.error


def test_transfer_out_without_quote_is_not_a_sell():
    tx = make_tx(tokens=[(TOKEN, 6, 100 * 10**6, 40 * 10**6)])
    [ev] = parse_transaction(tx, TRADER)
    assert ev.kind == EventKind.TRANSFER_OUT


def test_token_to_token_emits_sell_then_buy():
    tx = make_tx(tokens=[(TOKEN, 6, 100 * 10**6, 0), (TOKEN2, 6, None, 7 * 10**6)])
    evs = parse_transaction(tx, TRADER)
    assert [e.kind for e in evs] == [EventKind.SELL_FULL, EventKind.BUY]
    assert all(e.price_in_quote is None for e in evs)


def test_wallet_not_fee_payer_and_json_encoding():
    lam = 3 * 10**9
    tx = make_tx(fee_payer=False, sol_pre=10 * 10**9, sol_post=10 * 10**9 - lam,
                 tokens=[(TOKEN, 6, None, 9 * 10**6)], encoding="json")
    [ev] = parse_transaction(tx, TRADER)
    assert ev.kind == EventKind.BUY and abs(ev.quote_amount - 3.0) < 1e-9


def test_unrelated_wallet_produces_other():
    tx = buy_with_sol(1.0, tokens_out=10**6)
    assert parse_transaction(tx, OTHER) == [] or parse_transaction(tx, OTHER)[0].kind == EventKind.OTHER
