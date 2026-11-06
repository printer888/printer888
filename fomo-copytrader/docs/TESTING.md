# Test plan and results

Run: `pip install -r requirements-dev.txt && pytest -q` (53 tests, ~5 s, fully offline).
Scenario run: `python -m fomo_copytrader.cli simulate --out docs/SIMULATION_REPORT.md`.

Test fixtures replicate the shape of real Solana `getTransaction` (jsonParsed and json) responses. They include
liquidity-pool token accounts, which must be ignored, fee-payer and non-fee-payer wallets, and address lookup tables.

| Requirement (spec §12) | Test(s) |
|---|---|
| Trader monitoring engine | `test_monitor_processes_in_order_and_retries_unavailable_tx` (ordering, cursor persistence, RPC lag retry) |
| Buy detection | `test_buy_with_sol_*`, `test_buy_with_usdc_prefers_stable_quote`, `test_wallet_not_fee_payer_and_json_encoding`, `test_pool_accounts_are_ignored` |
| Sell detection | `test_full_sell_and_dust_counts_as_full`, `test_token_to_token_emits_sell_then_buy` |
| Partial sell detection + proportional mirror | `test_partial_sell_fraction_from_onchain_balances`, `test_partial_then_full_sell_proportional_and_net_pnl` |
| Transaction failures (trader) | `test_failed_transaction`, `test_failed_trader_tx_recorded_not_copied` |
| Transaction failures (ours) | `test_execution_failures_suspend_copying`, `test_failed_exit_is_retried_by_position_monitor` |
| Delayed transactions | `test_delayed_signal_is_skipped` |
| Insufficient liquidity | `test_insufficient_liquidity_is_skipped`, risk rejections |
| Price differences | `test_price_moved_too_far_is_skipped`, execution-difference assertions |
| Duplicate event detection | `test_duplicate_delivery_executes_once`, `test_leader_lock_semantics` |
| Emergency shutdown | `test_emergency_stop_flattens_and_blocks`, `test_controls_and_emergency` |
| Risk limits | `test_risk.py` (sizing, allocation, 12 rejection reasons, halts, exit rules), `test_daily_loss_limit_blocks_new_entries`, `test_stop_loss_without_trader_exit` |
| Cost accounting | `test_buy_is_copied_with_costs_in_basis`, `test_partial_then_full_sell_proportional_and_net_pnl`, `test_report_contains_costs` |
| Live execution stays disabled | `test_live_guard.py`, `test_live_cannot_be_armed_in_paper_config` |
| Dashboard/API security | `test_auth_required`, `test_websocket_requires_token`, `test_prod_requires_token` |
| Trader evaluation | `test_analytics.py` |

## Paper trading with real-time market data

This **has not been run yet.** The build environment had no network access to Solana RPC, Jupiter or DexScreener.
Run it on your deployment before considering live mode:

1. Deploy with `EXECUTION_MODE=paper` (the default) and a dedicated RPC provider.
2. Analyse the candidate trader on the dashboard (**Analyse**) and review the red flags.
3. Select the trader → **Start copying**. Paper fills use live Jupiter quotes for your exact size, plus a latency
   slippage haircut (`PAPER_EXTRA_SLIPPAGE_BPS`) and real network-fee estimates.
4. Run for at least 2–4 weeks / 30+ copied round trips. Read `/api/report.md` (or **Performance report**).
5. Compare *your* net results with the trader's. Check the skip reasons too: a high share of
   "signal too old" or "price already moved" means the trader cannot be copied at your latency.

The simulated report in `SIMULATION_REPORT.md` validates **behaviour**, not profitability.
