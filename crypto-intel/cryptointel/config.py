"""Central configuration loaded from environment variables.

No credentials are stored in code. Copy `.env.example` to `.env` and fill values.
Public Bybit market data needs no API key at all.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (does not override variables already set)."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _get(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _get_float(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


def _get_int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


def _get_bool(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _get_list(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name)
    if raw is None:
        return list(default)
    return [x.strip() for x in raw.split(",") if x.strip()]


DEFAULT_NEWS_FEEDS = [
    # (source name, url, is_official_source)
    "CoinDesk|https://www.coindesk.com/arc/outboundfeeds/rss/|0",
    "Cointelegraph|https://cointelegraph.com/rss|0",
    "CNBC Markets|https://www.cnbc.com/id/10000664/device/rss/rss.html|0",
    "Federal Reserve|https://www.federalreserve.gov/feeds/press_all.xml|1",
    "European Central Bank|https://www.ecb.europa.eu/rss/press.html|1",
    "Bank of England|https://www.bankofengland.co.uk/rss/news|1",
]

def _resolve(path: str) -> str:
    p = Path(path)
    return str(p if p.is_absolute() else PROJECT_ROOT / p)


TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d", "1w"]


@dataclass(frozen=True)
class Settings:
    # --- Bybit (public endpoints) ---
    bybit_rest_url: str = "https://api.bybit.com"
    bybit_ws_linear: str = "wss://stream.bybit.com/v5/public/linear"
    bybit_ws_spot: str = "wss://stream.bybit.com/v5/public/spot"
    # Optional READ-ONLY key. Not required by any feature in this project.
    bybit_api_key: str = ""
    bybit_api_secret: str = ""
    http_timeout: float = 10.0
    max_requests_per_second: float = 8.0

    # --- Storage ---
    database_url: str = f"sqlite:///{PROJECT_ROOT / 'cryptointel.db'}"

    # --- Telegram ---
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    alert_cooldown_minutes: int = 60

    # --- Universe filter ---
    core_symbols: list[str] = field(
        default_factory=lambda: ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
    )
    extra_symbols: list[str] = field(default_factory=list)
    max_universe: int = 20
    min_turnover_24h_usd: float = 20_000_000.0
    min_open_interest_usd: float = 5_000_000.0
    max_spread_bps: float = 10.0
    min_listing_days: int = 60
    max_abs_24h_change_pct: float = 40.0

    # --- Analysis ---
    timeframes: list[str] = field(default_factory=lambda: list(TIMEFRAMES))
    primary_timeframe: str = "1h"
    kline_limit: int = 300
    min_score: float = 70.0
    min_rr: float = 2.0
    min_technical_points: float = 12.0
    min_structure_points: float = 10.0
    use_ml_in_score: bool = False

    # --- Costs (verify against Bybit's current fee schedule for your VIP tier) ---
    taker_fee: float = 0.00055
    maker_fee: float = 0.0002
    spot_taker_fee: float = 0.001
    slippage_bps: float = 3.0
    default_mmr: float = 0.005  # tier-1 maintenance margin rate used for estimates

    # --- Risk / paper trading ---
    paper_starting_equity: float = 10_000.0
    risk_per_trade: float = 0.01
    paper_leverage: float = 3.0
    paper_auto_trade: bool = True
    max_open_paper_trades: int = 5
    drawdown_alert_pct: float = 10.0

    # --- Service ---
    scan_interval_seconds: int = 120
    news_interval_seconds: int = 600
    news_feeds: list[str] = field(default_factory=lambda: list(DEFAULT_NEWS_FEEDS))
    calendar_path: str = str(PROJECT_ROOT / "config" / "economic_calendar.json")
    enable_websocket: bool = True
    log_level: str = "INFO"

    @classmethod
    def from_env(cls, dotenv: bool = True) -> "Settings":
        if dotenv:
            _load_dotenv(PROJECT_ROOT / ".env")
        d = cls()
        return cls(
            bybit_rest_url=_get("BYBIT_REST_URL", d.bybit_rest_url),
            bybit_ws_linear=_get("BYBIT_WS_LINEAR", d.bybit_ws_linear),
            bybit_ws_spot=_get("BYBIT_WS_SPOT", d.bybit_ws_spot),
            bybit_api_key=_get("BYBIT_API_KEY", ""),
            bybit_api_secret=_get("BYBIT_API_SECRET", ""),
            http_timeout=_get_float("HTTP_TIMEOUT", d.http_timeout),
            max_requests_per_second=_get_float("MAX_REQUESTS_PER_SECOND", d.max_requests_per_second),
            database_url=_get("DATABASE_URL", d.database_url),
            telegram_bot_token=_get("TELEGRAM_BOT_TOKEN", ""),
            telegram_chat_id=_get("TELEGRAM_CHAT_ID", ""),
            alert_cooldown_minutes=_get_int("ALERT_COOLDOWN_MINUTES", d.alert_cooldown_minutes),
            core_symbols=_get_list("CORE_SYMBOLS", d.core_symbols),
            extra_symbols=_get_list("EXTRA_SYMBOLS", d.extra_symbols),
            max_universe=_get_int("MAX_UNIVERSE", d.max_universe),
            min_turnover_24h_usd=_get_float("MIN_TURNOVER_24H_USD", d.min_turnover_24h_usd),
            min_open_interest_usd=_get_float("MIN_OPEN_INTEREST_USD", d.min_open_interest_usd),
            max_spread_bps=_get_float("MAX_SPREAD_BPS", d.max_spread_bps),
            min_listing_days=_get_int("MIN_LISTING_DAYS", d.min_listing_days),
            max_abs_24h_change_pct=_get_float("MAX_ABS_24H_CHANGE_PCT", d.max_abs_24h_change_pct),
            timeframes=_get_list("TIMEFRAMES", d.timeframes),
            primary_timeframe=_get("PRIMARY_TIMEFRAME", d.primary_timeframe),
            kline_limit=_get_int("KLINE_LIMIT", d.kline_limit),
            min_score=_get_float("MIN_SCORE", d.min_score),
            min_rr=_get_float("MIN_RR", d.min_rr),
            min_technical_points=_get_float("MIN_TECHNICAL_POINTS", d.min_technical_points),
            min_structure_points=_get_float("MIN_STRUCTURE_POINTS", d.min_structure_points),
            use_ml_in_score=_get_bool("USE_ML_IN_SCORE", d.use_ml_in_score),
            taker_fee=_get_float("TAKER_FEE", d.taker_fee),
            maker_fee=_get_float("MAKER_FEE", d.maker_fee),
            spot_taker_fee=_get_float("SPOT_TAKER_FEE", d.spot_taker_fee),
            slippage_bps=_get_float("SLIPPAGE_BPS", d.slippage_bps),
            default_mmr=_get_float("DEFAULT_MMR", d.default_mmr),
            paper_starting_equity=_get_float("PAPER_STARTING_EQUITY", d.paper_starting_equity),
            risk_per_trade=_get_float("RISK_PER_TRADE", d.risk_per_trade),
            paper_leverage=_get_float("PAPER_LEVERAGE", d.paper_leverage),
            paper_auto_trade=_get_bool("PAPER_AUTO_TRADE", d.paper_auto_trade),
            max_open_paper_trades=_get_int("MAX_OPEN_PAPER_TRADES", d.max_open_paper_trades),
            drawdown_alert_pct=_get_float("DRAWDOWN_ALERT_PCT", d.drawdown_alert_pct),
            scan_interval_seconds=_get_int("SCAN_INTERVAL_SECONDS", d.scan_interval_seconds),
            news_interval_seconds=_get_int("NEWS_INTERVAL_SECONDS", d.news_interval_seconds),
            news_feeds=_get_list("NEWS_FEEDS", d.news_feeds),
            calendar_path=_resolve(_get("CALENDAR_PATH", d.calendar_path)),
            enable_websocket=_get_bool("ENABLE_WEBSOCKET", d.enable_websocket),
            log_level=_get("LOG_LEVEL", d.log_level),
        )

    def redacted(self) -> dict:
        """Settings safe to display (secrets masked)."""
        out = {}
        for k, v in self.__dict__.items():
            if any(s in k for s in ("key", "secret", "token")) and v:
                out[k] = "***"
            elif k == "database_url" and "@" in str(v):
                out[k] = str(v).split("@")[0].split("://")[0] + "://***@" + str(v).split("@")[1]
            else:
                out[k] = v
        return out


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings.from_env()
    return _settings
