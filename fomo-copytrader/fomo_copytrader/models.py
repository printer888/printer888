"""Persistent records. Every trader event, copy order, and position change is stored."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Trader(Base):
    __tablename__ = "traders"
    id: Mapped[int] = mapped_column(primary_key=True)
    wallet: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    label: Mapped[str | None] = mapped_column(String(128))
    fomo_profile: Mapped[str | None] = mapped_column(String(256))
    active: Mapped[bool] = mapped_column(Boolean, default=False)  # the one currently followed
    last_signature: Mapped[str | None] = mapped_column(String(128))  # polling cursor
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stats: Mapped[dict | None] = mapped_column(JSON)
    stats_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TraderEvent(Base):
    """One trader action derived from a confirmed transaction. (signature, mint, kind) is unique => dedupe."""
    __tablename__ = "trader_events"
    __table_args__ = (UniqueConstraint("signature", "token_mint", "kind", name="uq_event"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    trader_wallet: Mapped[str] = mapped_column(String(64), index=True)
    signature: Mapped[str] = mapped_column(String(128), index=True)
    slot: Mapped[int] = mapped_column(BigInteger)
    block_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    kind: Mapped[str] = mapped_column(String(24))
    token_mint: Mapped[str] = mapped_column(String(64), default="")
    token_symbol: Mapped[str | None] = mapped_column(String(32))
    token_amount: Mapped[float] = mapped_column(Float, default=0)
    token_pre_balance: Mapped[float] = mapped_column(Float, default=0)
    token_post_balance: Mapped[float] = mapped_column(Float, default=0)
    quote_mint: Mapped[str | None] = mapped_column(String(64))
    quote_amount: Mapped[float] = mapped_column(Float, default=0)
    price_usd: Mapped[float | None] = mapped_column(Float)
    notional_usd: Mapped[float | None] = mapped_column(Float)
    error: Mapped[str | None] = mapped_column(Text)
    copy_status: Mapped[str] = mapped_column(String(32), default="pending")  # pending/copied/skipped/failed/ignored
    copy_note: Mapped[str | None] = mapped_column(Text)
    latency_sec: Mapped[float | None] = mapped_column(Float)


class Position(Base):
    __tablename__ = "positions"
    id: Mapped[int] = mapped_column(primary_key=True)
    trader_wallet: Mapped[str] = mapped_column(String(64), index=True)
    token_mint: Mapped[str] = mapped_column(String(64), index=True)
    token_symbol: Mapped[str | None] = mapped_column(String(32))
    token_decimals: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)  # open/closed
    mode: Mapped[str] = mapped_column(String(8), default="paper")

    trader_entry_price_usd: Mapped[float | None] = mapped_column(Float)
    trader_initial_amount: Mapped[float] = mapped_column(Float, default=0)
    trader_current_amount: Mapped[float] = mapped_column(Float, default=0)
    trader_last_action: Mapped[str | None] = mapped_column(String(24))
    trader_last_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    my_amount: Mapped[float] = mapped_column(Float, default=0)
    my_amount_raw: Mapped[str] = mapped_column(String(40), default="0")
    my_entry_price_usd: Mapped[float | None] = mapped_column(Float)   # weighted average, incl. entry costs
    my_cost_basis_usd: Mapped[float] = mapped_column(Float, default=0)  # remaining basis, incl. entry costs
    my_invested_usd: Mapped[float] = mapped_column(Float, default=0)    # total ever invested
    realized_pnl_usd: Mapped[float] = mapped_column(Float, default=0)   # net of all costs
    fees_usd: Mapped[float] = mapped_column(Float, default=0)           # network + platform
    slippage_usd: Mapped[float] = mapped_column(Float, default=0)
    last_price_usd: Mapped[float | None] = mapped_column(Float)
    peak_price_usd: Mapped[float | None] = mapped_column(Float)
    last_liquidity_usd: Mapped[float | None] = mapped_column(Float)
    last_alert_price_usd: Mapped[float | None] = mapped_column(Float)
    exit_reason: Mapped[str | None] = mapped_column(String(64))
    pending_exit_fraction: Mapped[float | None] = mapped_column(Float)  # failed exit awaiting retry
    pending_exit_reason: Mapped[str | None] = mapped_column(String(64))
    exit_attempts: Mapped[int] = mapped_column(Integer, default=0)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class CopyOrder(Base):
    """Every attempted copy. ``idempotency_key`` is unique: a trader tx can never be executed twice."""
    __tablename__ = "copy_orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    position_id: Mapped[int | None] = mapped_column(ForeignKey("positions.id"))
    trader_signature: Mapped[str | None] = mapped_column(String(128))
    side: Mapped[str] = mapped_column(String(8))
    reason: Mapped[str] = mapped_column(String(64))  # copy_buy / copy_sell / stop_loss / emergency ...
    token_mint: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending/filled/failed/rejected
    mode: Mapped[str] = mapped_column(String(8), default="paper")
    requested_usd: Mapped[float | None] = mapped_column(Float)
    requested_fraction: Mapped[float | None] = mapped_column(Float)
    token_amount: Mapped[float | None] = mapped_column(Float)
    price_usd: Mapped[float | None] = mapped_column(Float)
    reference_price_usd: Mapped[float | None] = mapped_column(Float)  # trader's price
    notional_usd: Mapped[float | None] = mapped_column(Float)
    fees_usd: Mapped[float | None] = mapped_column(Float)
    slippage_usd: Mapped[float | None] = mapped_column(Float)
    price_impact_pct: Mapped[float | None] = mapped_column(Float)
    execution_diff_pct: Mapped[float | None] = mapped_column(Float)
    realized_pnl_usd: Mapped[float | None] = mapped_column(Float)  # SELLs: net of all costs
    signature: Mapped[str | None] = mapped_column(String(128))
    error: Mapped[str | None] = mapped_column(Text)
    risk_checks: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KV(Base):
    """Small key/value store for runtime state (risk limits, engine status, equity peak)."""
    __tablename__ = "kv"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    level: Mapped[str] = mapped_column(String(8), default="INFO")
    category: Mapped[str] = mapped_column(String(32))
    message: Mapped[str] = mapped_column(Text)
    data: Mapped[dict | None] = mapped_column(JSON)
