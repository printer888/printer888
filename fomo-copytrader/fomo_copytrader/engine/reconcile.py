"""Transaction reconciliation.

* Internal: each open position's token amount must equal the sum of its
  filled order quantities.
* Stale orders: an order stuck in ``pending`` (e.g. the process died mid-send)
  is resolved from its on-chain signature status when one exists; otherwise
  it is marked ``unknown`` and an alert is raised. It is never resent blindly.
* Live wallet: on-chain balances of our wallet must cover recorded positions.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from ..models import CopyOrder, Position
from .copy_engine import CopyEngine, _aware

log = logging.getLogger(__name__)


async def reconcile(engine: CopyEngine, wallet_balances: dict[str, int] | None = None,
                    stale_after: timedelta = timedelta(minutes=5)) -> list[str]:
    issues: list[str] = []
    now = datetime.now(timezone.utc)
    async with engine.sm() as s:
        positions = list((await s.execute(select(Position).where(Position.status == "open"))).scalars())
        orders = list((await s.execute(select(CopyOrder))).scalars())
        for o in orders:
            created = _aware(o.created_at)
            if o.status == "pending" and created and now - created > stale_after:
                resolved = False
                if o.signature and engine.rpc and not o.signature.startswith("paper-"):
                    try:
                        st = (await engine.rpc.get_signature_statuses([o.signature]) or [None])[0]
                        if st and st.get("err") is None and st.get("confirmationStatus"):
                            o.status, o.error = "unknown", "confirmed on-chain but not booked; manual review"
                            resolved = True
                    except Exception as e:  # noqa: BLE001
                        log.warning("status lookup failed: %s", e)
                if not resolved:
                    o.status, o.error = "unknown", "stale pending order; outcome unknown, not retried"
                issues.append(f"order #{o.id} {o.side} {o.token_mint[:6]} was stale -> {o.status}")
        await s.commit()

    by_pos: dict[int, float] = {}
    for o in orders:
        if o.status == "filled" and o.position_id:
            q = o.token_amount or 0.0
            by_pos[o.position_id] = by_pos.get(o.position_id, 0.0) + (q if o.side == "BUY" else -q)
    for p in positions:
        booked = by_pos.get(p.id, 0.0)
        if abs(booked - p.my_amount) > max(1e-9, 1e-6 * max(abs(booked), abs(p.my_amount))):
            issues.append(f"position #{p.id} amount {p.my_amount} != orders {booked}")
        if wallet_balances is not None:
            onchain = wallet_balances.get(p.token_mint, 0)
            if onchain < int(p.my_amount_raw):
                issues.append(f"position #{p.id} {p.token_symbol or p.token_mint[:6]}: wallet holds {onchain} raw "
                              f"< recorded {p.my_amount_raw}")
    for i in issues:
        await engine.state.audit("reconcile", i, level="WARNING")
    if issues:
        await engine.notifier.send("RECONCILIATION ISSUES", [(f"#{n+1}", i) for n, i in enumerate(issues[:10])])
    return issues
