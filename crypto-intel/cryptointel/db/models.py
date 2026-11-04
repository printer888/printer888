"""ORM models (SQLAlchemy 2.x). PostgreSQL in production, SQLite for development.

See db/schema.sql for the equivalent PostgreSQL DDL.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Float, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

JSONType = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    pass


class Candle(Base):
    __tablename__ = "candles"
    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32))
    category: Mapped[str] = mapped_column(String(16))
    timeframe: Mapped[str] = mapped_column(String(4))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float)
    turnover: Mapped[float] = mapped_column(Float)
    __table_args__ = (UniqueConstraint("symbol", "category", "timeframe", "ts", name="uq_candle"),)


class MarketSnapshot(Base):
    __tablename__ = "market_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    price: Mapped[float | None] = mapped_column(Float)
    funding_rate: Mapped[float | None] = mapped_column(Float)
    open_interest_value: Mapped[float | None] = mapped_column(Float)
    turnover_24h: Mapped[float | None] = mapped_column(Float)
    spread_bps: Mapped[float | None] = mapped_column(Float)
    data: Mapped[dict] = mapped_column(JSONType, default=dict)


class OpportunityRow(Base):
    __tablename__ = "opportunities"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(16))
    direction: Mapped[str | None] = mapped_column(String(8))
    score: Mapped[float] = mapped_column(Float)
    timeframe: Mapped[str] = mapped_column(String(4))
    price: Mapped[float | None] = mapped_column(Float)
    entry: Mapped[float | None] = mapped_column(Float)
    stop: Mapped[float | None] = mapped_column(Float)
    rr_net: Mapped[float | None] = mapped_column(Float)
    payload: Mapped[dict] = mapped_column(JSONType)


class NewsEventRow(Base):
    __tablename__ = "news_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uid: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(64))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    importance: Mapped[str] = mapped_column(String(8))
    confirmation: Mapped[str] = mapped_column(String(64))
    sentiment: Mapped[float] = mapped_column(Float)
    payload: Mapped[dict] = mapped_column(JSONType)


class PaperTradeRow(Base):
    __tablename__ = "paper_trades"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    side: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(8), index=True)
    leverage: Mapped[float] = mapped_column(Float)
    entry_price: Mapped[float] = mapped_column(Float)
    entry_time: Mapped[str] = mapped_column(String(40))
    realized_pnl: Mapped[float] = mapped_column(Float, default=0)
    exit_reason: Mapped[str | None] = mapped_column(String(64))
    closed_at: Mapped[str | None] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSONType)


class PaperAccount(Base):
    __tablename__ = "paper_account"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    balance: Mapped[float] = mapped_column(Float)
    starting_equity: Mapped[float] = mapped_column(Float)


class BacktestRun(Base):
    __tablename__ = "backtest_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    kind: Mapped[str] = mapped_column(String(16))  # single | walk_forward | holdout
    strategy: Mapped[str] = mapped_column(String(64))
    symbol: Mapped[str] = mapped_column(String(32))
    timeframe: Mapped[str] = mapped_column(String(4))
    params: Mapped[dict] = mapped_column(JSONType)
    result: Mapped[dict] = mapped_column(JSONType)


class AlertRow(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    type: Mapped[str] = mapped_column(String(32))
    symbol: Mapped[str | None] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(Text)
    sent: Mapped[bool] = mapped_column(Boolean)
    payload: Mapped[dict] = mapped_column(JSONType)


Index("ix_opp_symbol_created", OpportunityRow.symbol, OpportunityRow.created_at)
