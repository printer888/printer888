"""Turn a Solana ``getTransaction`` result into trader actions.

The approach is deliberately protocol-agnostic: instead of decoding each DEX
program's instructions (Raydium, Orca, Meteora, Pump.fun, Jupiter, whatever
FOMO routes through), we diff the *followed wallet's* balances before and after
the transaction, using ``meta.pre/postBalances`` and
``meta.pre/postTokenBalances``. These fields are produced by the validator and
are the most reliable public record of what a wallet actually gained and lost.

Limitations (documented, not hidden):
* SOL spent includes rent for any newly created token account (~0.002 SOL),
  so the derived entry price of a first buy is slightly overstated.
* Platform fees charged in SOL inside the same transaction are included in
  the trader's effective price, which is what we want for comparison.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..constants import LAMPORTS_PER_SOL, QUOTE_MINTS, SOL_DECIMALS, STABLE_MINTS, WSOL_MINT
from ..schemas import EventKind, SwapEvent, TokenDelta

# A trader position is considered fully closed when the remaining balance is
# below this fraction of the pre-sell balance (dust left by rounding).
DUST_FRACTION = 0.001
MIN_SOL_QUOTE_LAMPORTS = 100_000  # 0.0001 SOL: below this a SOL change is just fees


def _account_keys(tx: dict) -> list[str]:
    msg = tx["transaction"]["message"]
    keys: list[str] = []
    for k in msg.get("accountKeys", []):
        keys.append(k["pubkey"] if isinstance(k, dict) else k)
    # "json" encoding puts lookup-table addresses in meta.loadedAddresses
    loaded = (tx.get("meta") or {}).get("loadedAddresses") or {}
    if loaded and not any(isinstance(k, dict) for k in msg.get("accountKeys", [])):
        keys.extend(loaded.get("writable", []))
        keys.extend(loaded.get("readonly", []))
    return keys


def _token_balances(entries: list[dict] | None, owner: str) -> dict[str, tuple[int, int]]:
    """Return {mint: (raw_amount_sum, decimals)} for accounts owned by ``owner``."""
    out: dict[str, tuple[int, int]] = {}
    for e in entries or []:
        if e.get("owner") != owner:
            continue
        amt = e["uiTokenAmount"]
        raw = int(amt["amount"])
        dec = int(amt["decimals"])
        prev = out.get(e["mint"], (0, dec))
        out[e["mint"]] = (prev[0] + raw, dec)
    return out


def compute_deltas(tx: dict, wallet: str) -> tuple[list[TokenDelta], float]:
    """Return per-mint deltas for ``wallet`` (native SOL merged into WSOL) and the tx fee in SOL."""
    meta = tx.get("meta") or {}
    keys = _account_keys(tx)
    fee_lamports = int(meta.get("fee", 0))

    pre_t = _token_balances(meta.get("preTokenBalances"), wallet)
    post_t = _token_balances(meta.get("postTokenBalances"), wallet)
    deltas: dict[str, TokenDelta] = {}
    for mint in set(pre_t) | set(post_t):
        pre_raw, dec = pre_t.get(mint, (0, post_t.get(mint, (0, 0))[1]))
        post_raw, dec2 = post_t.get(mint, (0, dec))
        deltas[mint] = TokenDelta(mint=mint, decimals=dec or dec2, pre_raw=pre_raw, post_raw=post_raw)

    # Native SOL: excluding the tx fee when the wallet paid it.
    if wallet in keys:
        idx = keys.index(wallet)
        pre_l = int(meta["preBalances"][idx])
        post_l = int(meta["postBalances"][idx])
        if idx == 0:  # fee payer
            post_l += fee_lamports
        w = deltas.get(WSOL_MINT)
        if w is None:
            deltas[WSOL_MINT] = TokenDelta(WSOL_MINT, SOL_DECIMALS, pre_l, post_l)
        else:
            deltas[WSOL_MINT] = TokenDelta(WSOL_MINT, SOL_DECIMALS, w.pre_raw + pre_l, w.post_raw + post_l)

    return list(deltas.values()), fee_lamports / LAMPORTS_PER_SOL


def _block_time(tx: dict) -> datetime | None:
    bt = tx.get("blockTime")
    return datetime.fromtimestamp(bt, tz=timezone.utc) if bt else None


def _signature(tx: dict) -> str:
    return tx["transaction"]["signatures"][0]


def _significant_quote(d: TokenDelta) -> bool:
    if d.mint == WSOL_MINT:
        return abs(d.delta_raw) >= MIN_SOL_QUOTE_LAMPORTS
    return d.delta_raw != 0


def _pick_quote(quotes: list[TokenDelta], sign: int) -> TokenDelta | None:
    """Pick the quote leg moving in direction ``sign`` (-1 spent, +1 received); prefer stables."""
    cands = [q for q in quotes if (q.delta_raw > 0) == (sign > 0) and q.delta_raw != 0]
    if not cands:
        return None
    stables = [q for q in cands if q.mint in STABLE_MINTS]
    pool = stables or cands
    return max(pool, key=lambda q: abs(q.delta_ui))


def parse_transaction(tx: dict[str, Any], wallet: str) -> list[SwapEvent]:
    """Parse one transaction into zero or more trader events for ``wallet``."""
    if not tx or "transaction" not in tx:
        return []
    meta = tx.get("meta") or {}
    sig = _signature(tx)
    slot = int(tx.get("slot", 0))
    bt = _block_time(tx)
    base = dict(signature=sig, wallet=wallet, slot=slot, block_time=bt)

    if meta.get("err") is not None:
        return [SwapEvent(**base, kind=EventKind.FAILED, error=str(meta["err"]),
                          fee_sol=int(meta.get("fee", 0)) / LAMPORTS_PER_SOL)]

    deltas, fee_sol = compute_deltas(tx, wallet)
    tokens = [d for d in deltas if d.mint not in QUOTE_MINTS and d.delta_raw != 0]
    quotes = [d for d in deltas if d.mint in QUOTE_MINTS and _significant_quote(d)]

    events: list[SwapEvent] = []
    gained = [t for t in tokens if t.delta_raw > 0]
    lost = [t for t in tokens if t.delta_raw < 0]

    def mk(kind: EventKind, t: TokenDelta, q: TokenDelta | None) -> SwapEvent:
        amount = abs(t.delta_ui)
        q_amt = abs(q.delta_ui) if q else 0.0
        return SwapEvent(
            **base, kind=kind, token_mint=t.mint, token_decimals=t.decimals,
            token_amount=amount, token_pre_balance=t.pre_ui, token_post_balance=t.post_ui,
            quote_mint=q.mint if q else None, quote_amount=q_amt,
            price_in_quote=(q_amt / amount) if (q and amount > 0) else None,
            fee_sol=fee_sol, raw_deltas=deltas,
        )

    def sell_kind(t: TokenDelta) -> EventKind:
        if t.post_raw <= 0 or t.post_raw <= t.pre_raw * DUST_FRACTION:
            return EventKind.SELL_FULL
        return EventKind.SELL_PARTIAL

    # Standard swaps against a quote asset (SOL/USDC/USDT).
    if len(gained) == 1 and not lost:
        q = _pick_quote(quotes, -1)
        events.append(mk(EventKind.BUY if q else EventKind.TRANSFER_IN, gained[0], q))
    elif len(lost) == 1 and not gained:
        q = _pick_quote(quotes, +1)
        events.append(mk(sell_kind(lost[0]) if q else EventKind.TRANSFER_OUT, lost[0], q))
    elif gained or lost:
        # Token-to-token route or multi-leg tx: emit the sells first so exits
        # are processed before new entries. Prices are unknown (no quote leg).
        for t in lost:
            events.append(mk(sell_kind(t), t, None))
        for t in gained:
            events.append(mk(EventKind.BUY, t, None))
    else:
        events.append(SwapEvent(**base, kind=EventKind.OTHER, fee_sol=fee_sol, raw_deltas=deltas))
    return events
