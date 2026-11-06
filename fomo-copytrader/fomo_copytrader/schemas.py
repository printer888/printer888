"""Shared value objects (pydantic models and dataclasses)."""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class Side(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"


class EventKind(str, enum.Enum):
    BUY = "BUY"                    # new position or add to position
    SELL_PARTIAL = "SELL_PARTIAL"
    SELL_FULL = "SELL_FULL"
    FAILED = "FAILED"              # landed on-chain with an error
    TRANSFER_IN = "TRANSFER_IN"    # balance change without a quote leg
    TRANSFER_OUT = "TRANSFER_OUT"
    OTHER = "OTHER"


class RiskLimits(BaseModel):
    """Operator-editable risk policy. Persisted in the DB as JSON."""

    total_capital_usd: float = Field(1000.0, gt=0)
    max_allocation_pct: float = Field(50.0, gt=0, le=100)
    max_open_positions: int = Field(5, ge=1, le=100)
    sizing_mode: Literal["fixed", "proportional"] = "fixed"
    fixed_position_usd: float = Field(25.0, gt=0)
    proportional_ratio: float = Field(0.01, gt=0, le=10, description="my_usd = trader_usd * ratio")
    min_position_usd: float = Field(5.0, ge=0)
    max_position_usd: float = Field(50.0, gt=0)

    max_slippage_bps: int = Field(300, ge=1, le=5000)
    max_exit_slippage_bps: int = Field(1000, ge=1, le=5000, description="exits get more room: getting out matters more")
    max_price_impact_pct: float = Field(3.0, gt=0, le=50)
    max_entry_drift_pct: float = Field(10.0, gt=0, le=500, description="max price rise since trader's entry")
    max_signal_age_sec: int = Field(120, ge=5, description="skip BUYs older than this")
    max_round_trip_cost_pct: float = Field(4.0, gt=0, le=50)

    max_daily_loss_usd: float = Field(50.0, gt=0)
    max_drawdown_pct: float = Field(20.0, gt=0, le=100)
    max_consecutive_failures: int = Field(3, ge=1)

    min_liquidity_usd: float = Field(50_000.0, ge=0)
    min_volume_24h_usd: float = Field(100_000.0, ge=0)
    min_pair_age_hours: float = Field(1.0, ge=0)
    require_mint_authority_revoked: bool = True
    require_freeze_authority_revoked: bool = True
    allow_token_2022: bool = False
    max_top10_holder_pct: float = Field(60.0, gt=0, le=100)

    # Independent exit protection (applies even if the trader never sells)
    stop_loss_pct: float | None = Field(25.0, gt=0, le=100)
    take_profit_pct: float | None = Field(None, gt=0)
    trailing_stop_pct: float | None = Field(None, gt=0, le=100)
    max_hold_hours: float | None = Field(None, gt=0)

    trader_inactive_hours: float = Field(24.0, gt=0)
    price_move_alert_pct: float = Field(15.0, gt=0)

    @model_validator(mode="after")
    def _check(self) -> "RiskLimits":
        if self.min_position_usd > self.max_position_usd:
            raise ValueError("min_position_usd must be <= max_position_usd")
        return self

    @property
    def max_allocated_usd(self) -> float:
        return self.total_capital_usd * self.max_allocation_pct / 100.0


@dataclass
class TokenDelta:
    mint: str
    decimals: int
    pre_raw: int
    post_raw: int

    @property
    def delta_raw(self) -> int:
        return self.post_raw - self.pre_raw

    def ui(self, raw: int) -> float:
        return raw / (10 ** self.decimals)

    @property
    def pre_ui(self) -> float:
        return self.ui(self.pre_raw)

    @property
    def post_ui(self) -> float:
        return self.ui(self.post_raw)

    @property
    def delta_ui(self) -> float:
        return self.ui(self.delta_raw)


@dataclass
class SwapEvent:
    """A trader action derived from one confirmed on-chain transaction."""

    signature: str
    wallet: str
    slot: int
    block_time: datetime | None
    kind: EventKind
    token_mint: str | None = None
    token_decimals: int | None = None
    token_amount: float = 0.0          # absolute amount bought / sold (UI units)
    token_pre_balance: float = 0.0     # trader balance before the tx
    token_post_balance: float = 0.0    # trader balance after the tx
    quote_mint: str | None = None
    quote_amount: float = 0.0          # absolute quote spent / received (UI units)
    price_in_quote: float | None = None
    fee_sol: float = 0.0
    error: str | None = None
    raw_deltas: list[TokenDelta] = field(default_factory=list)

    @property
    def sell_fraction(self) -> float:
        if self.token_pre_balance <= 0:
            return 1.0
        return min(1.0, self.token_amount / self.token_pre_balance)


@dataclass
class TokenMarket:
    mint: str
    symbol: str | None
    price_usd: float | None
    liquidity_usd: float | None
    volume_24h_usd: float | None
    pair_address: str | None = None
    dex: str | None = None
    pair_created_at: datetime | None = None
    price_change_h1_pct: float | None = None


@dataclass
class Quote:
    input_mint: str
    output_mint: str
    in_amount_raw: int
    out_amount_raw: int
    price_impact_pct: float
    slippage_bps: int
    route_labels: list[str] = field(default_factory=list)
    raw: dict | None = None


@dataclass
class TokenSafety:
    mint: str
    decimals: int | None
    program: str | None
    mint_authority: str | None
    freeze_authority: str | None
    top10_holder_pct: float | None
    is_token_2022: bool = False
    risky_extensions: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class ExecutionResult:
    success: bool
    side: Side
    input_mint: str
    output_mint: str
    in_amount_ui: float = 0.0
    out_amount_ui: float = 0.0
    price_usd: float | None = None        # USD per token actually achieved
    notional_usd: float = 0.0             # USD value of the trade
    network_fee_usd: float = 0.0
    platform_fee_usd: float = 0.0
    slippage_cost_usd: float = 0.0        # vs mid/reference price
    signature: str | None = None
    simulated: bool = True
    error: str | None = None
    out_amount_raw: int = 0
    in_amount_raw: int = 0

    @property
    def total_cost_usd(self) -> float:
        return self.network_fee_usd + self.platform_fee_usd + self.slippage_cost_usd


@dataclass
class Decision:
    approved: bool
    reasons: list[str] = field(default_factory=list)
    size_usd: float = 0.0
    checks: dict = field(default_factory=dict)

    def reject(self, reason: str) -> "Decision":
        self.approved = False
        self.reasons.append(reason)
        return self
