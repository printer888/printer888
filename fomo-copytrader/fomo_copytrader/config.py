"""Process-level configuration, loaded from environment variables / .env.

Risk limits that the operator may change at runtime live in the database
(see ``schemas.RiskLimits``); values here are only the initial defaults.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# The exact phrase that must be present in LIVE_TRADING_ACK before the live
# executor will ever sign a transaction.
LIVE_ACK_PHRASE = "I_UNDERSTAND_REAL_FUNDS_ARE_AT_RISK"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"

    # Storage
    database_url: str = "sqlite+aiosqlite:///./data/copytrader.db"
    redis_url: str | None = None

    # Solana access (use a dedicated RPC provider in production; the public
    # endpoint is heavily rate limited and does not guarantee websocket uptime).
    solana_rpc_url: str = "https://api.mainnet-beta.solana.com"
    solana_ws_url: str = "wss://api.mainnet-beta.solana.com"
    rpc_poll_interval_sec: float = 4.0
    rpc_timeout_sec: float = 15.0

    # Market data / routing (public, documented APIs)
    jupiter_base_url: str = "https://lite-api.jup.ag"
    jupiter_api_key: str | None = None  # set together with https://api.jup.ag
    dexscreener_base_url: str = "https://api.dexscreener.com"

    # Telegram
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    # Dashboard auth. Required in prod.
    dashboard_token: str | None = None

    # Execution. Paper is the default; live requires *all* of: mode=live,
    # the ack phrase, a keypair file, and arming from the dashboard at runtime.
    execution_mode: Literal["paper", "live"] = "paper"
    live_trading_ack: str = ""
    wallet_keypair_path: str | None = None  # JSON array keypair file (Docker secret)
    funding_mint: Literal["USDC", "SOL"] = "USDC"
    priority_fee_lamports: int = 100_000
    base_fee_lamports: int = 5_000

    # Paper simulation assumptions
    paper_extra_slippage_bps: int = 50  # latency slippage on top of the quote
    paper_starting_capital_usd: float = 1000.0

    # Background loops
    position_check_interval_sec: float = 15.0
    reconcile_interval_sec: float = 300.0
    watchdog_stale_sec: float = 120.0
    daily_report_hour_utc: int = 21

    initial_trader_wallet: str | None = Field(default=None, description="optional wallet to follow on boot")

    @property
    def live_execution_permitted(self) -> bool:
        return (
            self.execution_mode == "live"
            and self.live_trading_ack == LIVE_ACK_PHRASE
            and bool(self.wallet_keypair_path)
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
