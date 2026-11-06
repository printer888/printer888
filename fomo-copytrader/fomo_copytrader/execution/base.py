from __future__ import annotations

from typing import Protocol

from ..schemas import ExecutionResult


class Executor(Protocol):
    mode: str  # "paper" | "live"

    async def buy(self, mint: str, decimals: int, usd_amount: float, slippage_bps: int) -> ExecutionResult: ...

    async def sell(self, mint: str, decimals: int, amount_raw: int, slippage_bps: int) -> ExecutionResult: ...
