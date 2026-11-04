"""Orchestrates data collection, analysis, persistence, paper trading and alerts."""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

import pandas as pd

from ..alerts import rules
from ..alerts.rules import AlertManager
from ..alerts.telegram import TelegramNotifier
from ..analysis import market as mkt
from ..analysis.derivatives import analyze_derivatives
from ..analysis.macro import load_calendar
from ..analysis.news import asset_news_assessment, fetch_all, providers_from_settings
from ..analysis.onchain import analyze_onchain, fetch_stablecoin_supply
from ..analysis.opportunity import build_opportunity
from ..analysis.scoring import ScoringInputs
from ..analysis.sentiment import analyze_sentiment, fetch_fear_greed
from ..analysis.timeframe import analyze_timeframe
from ..config import Settings
from ..data.bybit_client import BybitClient, parse_ticker
from ..data.bybit_ws import BybitPublicWS, build_topics
from ..data.freshness import TIMEFRAME_SECONDS, humanize_age, utcnow
from ..db.repository import Repository, _clean
from ..paper.engine import PaperBroker
from ..risk.leverage import CostModel
from ..universe import UniverseResult, select_universe

log = logging.getLogger(__name__)


class IntelligenceService:
    def __init__(self, settings: Settings, client: BybitClient | None = None, repo: Repository | None = None,
                 notifier: TelegramNotifier | None = None):
        self.s = settings
        self.client = client or BybitClient(settings.bybit_rest_url, settings.http_timeout,
                                            settings.max_requests_per_second)
        self.repo = repo or Repository(settings.database_url)
        self.alerts = AlertManager(notifier or TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id),
                                   settings.alert_cooldown_minutes,
                                   sink=lambda a, sent: self.repo.save_alert(a.to_dict(), sent))
        self.costs = CostModel(settings.taker_fee, settings.maker_fee, settings.slippage_bps, settings.default_mmr)
        self.broker = PaperBroker(settings.paper_starting_equity, self.costs, settings.max_open_paper_trades)
        acct = self.repo.paper_account()
        self.broker.load(self.repo.paper_trades(), acct["balance"] if acct else None)

        self.universe: UniverseResult | None = None
        self.universe_at: float = 0
        self.tickers: dict[str, dict] = {}
        self.tickers_at: datetime | None = None
        self.analyses: dict[str, dict] = {}
        self.opportunities: dict[str, dict] = {}
        self.overview: dict = {}
        self.news: list = []
        self.news_at: float = 0
        self.fng = None
        self.fng_at: float = 0
        self.stables = None
        self.stables_at: float = 0
        self.calendar = load_calendar(settings.calendar_path)
        self.kline_cache: dict[tuple[str, str], tuple[float, pd.DataFrame]] = {}
        self.pending_funding: dict[str, tuple[int, float]] = {}
        self.last_paper_bar: dict[str, pd.Timestamp] = {}
        self.ws: BybitPublicWS | None = None
        self.errors: list[dict] = []
        self.last_scan_at: datetime | None = None
        self.scan_duration: float | None = None
        self._prev_fng: int | None = None

    # ------------------------------------------------------------------ helpers
    def _err(self, where: str, e: Exception) -> None:
        log.warning("%s failed: %s", where, e)
        self.errors = (self.errors + [{"at": utcnow().isoformat(), "where": where, "error": str(e)[:300]}])[-50:]

    def klines(self, symbol: str, tf: str, limit: int | None = None) -> pd.DataFrame:
        key = (symbol, tf)
        now = time.time()
        cached = self.kline_cache.get(key)
        ttl = max(min(TIMEFRAME_SECONDS[tf], 900), 55)
        if cached and now - cached[0] < ttl and (limit is None or len(cached[1]) >= min(limit, 999)):
            return cached[1]
        df = self.client.klines(symbol, tf, limit=limit or self.s.kline_limit)
        self.kline_cache[key] = (now, df)
        return df

    # ------------------------------------------------------------------ refreshers
    def refresh_universe(self, force: bool = False) -> None:
        if not force and self.universe and time.time() - self.universe_at < 3600:
            return
        inst = self.client.instruments("linear")
        tick = self.client.tickers("linear")
        self.universe = select_universe(inst, tick, self.s)
        self.universe_at = time.time()
        log.info("universe: %d members, %d rejected", len(self.universe.members), len(self.universe.rejected))

    def refresh_tickers(self) -> list[dict]:
        raw = self.client.tickers("linear")
        self.tickers = {t["symbol"]: parse_ticker(t) for t in raw}
        self.tickers_at = utcnow()
        return raw

    def refresh_context(self) -> None:
        now = time.time()
        if now - self.fng_at > 3600:
            fng = fetch_fear_greed(30)
            if fng:
                if self.fng and self.fng.value:
                    self._prev_fng = self.fng.value[-1]["value"]
                self.fng = fng
            self.fng_at = now
        if now - self.stables_at > 6 * 3600:
            self.stables = fetch_stablecoin_supply() or self.stables
            self.stables_at = now
        if now - self.news_at > self.s.news_interval_seconds:
            events = fetch_all(providers_from_settings(self.s.news_feeds))
            if events:
                known = {e.uid for e in self.news}
                fresh = [e for e in events if e.uid not in known]
                self.news = events
                try:
                    self.repo.save_news([e.to_dict() for e in events])
                except Exception as e:
                    self._err("save_news", e)
                if known:  # don't alert on the initial backlog
                    for ev in fresh:
                        a = rules.news_alert(ev.to_dict())
                        if a:
                            self.alerts.emit(a, key_extra=ev.uid)
            self.news_at = now
        self.calendar = load_calendar(self.s.calendar_path)

    # ------------------------------------------------------------------ analysis
    def analyze_symbol(self, symbol: str, member=None, sentiment=None, onchain=None) -> dict:
        now = utcnow()
        tfas = {}
        for tf in self.s.timeframes:
            try:
                tfas[tf] = analyze_timeframe(self.klines(symbol, tf), tf, now)
            except Exception as e:
                self._err(f"klines {symbol} {tf}", e)
        ticker = self.tickers.get(symbol)
        primary = self.kline_cache.get((symbol, self.s.primary_timeframe), (0, pd.DataFrame()))[1]
        funding_hist = oi = ls = book = None
        try:
            funding_hist = self.client.funding_history(symbol, 200)
        except Exception as e:
            self._err(f"funding {symbol}", e)
        try:
            oi = self.client.open_interest(symbol, "1h", 48)
        except Exception as e:
            self._err(f"open_interest {symbol}", e)
        try:
            ls = self.client.long_short_ratio(symbol, "1h", 24)
        except Exception as e:
            self._err(f"long_short {symbol}", e)
        try:
            book = self.client.orderbook(symbol, "linear", 50)
        except Exception as e:
            self._err(f"orderbook {symbol}", e)
        h1 = self.kline_cache.get((symbol, "1h"), (0, pd.DataFrame()))[1]
        deriv = analyze_derivatives(
            ticker=ticker, funding_hist=funding_hist,
            funding_interval_minutes=member.funding_interval_minutes if member else 480,
            open_interest=oi, price=h1["close"] if len(h1) else None, ls_ratio=ls, book=book,
            liquidations=self.ws.liquidations.summary(symbol, 3600) if self.ws else None,
            trade_flow=self.ws.trade_flow.delta(symbol, 900) if self.ws else None,
        )
        base = symbol.replace("USDT", "")
        news_ok = bool(self.news) and time.time() - self.news_at < 2 * self.s.news_interval_seconds + 600
        news = asset_news_assessment(self.news, base, 72) if news_ok else None
        cal = self.calendar.event_risk(24, 2) if self.calendar.loaded else None
        inputs = ScoringInputs(
            timeframes=tfas, primary_tf=self.s.primary_timeframe, derivatives=deriv,
            liquidity={"turnover_24h": ticker["turnover_24h"] if ticker else None,
                       "spread_bps": ticker["spread_bps"] if ticker else None},
            news=news, calendar_risk=cal, sentiment=sentiment, onchain=onchain, use_ml=False,
        )
        price = ticker["last_price"] if ticker and self.tickers_at and (now - self.tickers_at).total_seconds() < 300 else None
        opp = build_opportunity(symbol, inputs, self.s, price, ticker["funding_rate"] if ticker else None,
                                member.funding_interval_minutes if member else 480, self.broker.equity())
        result = {
            "symbol": symbol, "as_of": now.isoformat(), "price": price,
            "ticker": ticker, "timeframes": {tf: a.to_dict() for tf, a in tfas.items()},
            "derivatives": deriv.to_dict(), "news": news, "opportunity": opp.to_dict(),
            "flags": member.flags if member else [],
        }
        return _clean(result)

    def scan(self) -> None:
        t0 = time.time()
        try:
            self.refresh_universe()
            raw_tickers = self.refresh_tickers()
        except Exception as e:
            self._err("universe/tickers", e)
            return
        try:
            self.refresh_context()
        except Exception as e:
            self._err("context", e)
        btc_d = None
        try:
            btc_d = self.klines("BTCUSDT", "1d")
        except Exception as e:
            self._err("btc daily", e)
        btc_t = self.tickers.get("BTCUSDT", {})
        oi_btc = None
        try:
            oi_series = self.client.open_interest("BTCUSDT", "1h", 30)
            if len(oi_series) > 24:
                oi_btc = float((oi_series.iloc[-1] / oi_series.iloc[-25] - 1) * 100)
        except Exception as e:
            self._err("btc oi", e)
        sentiment = analyze_sentiment(self.fng, btc_d, oi_btc, btc_t.get("change_24h_pct"))
        onchain = analyze_onchain(self.stables)
        a = rules.sentiment_shift_alert(self._prev_fng, sentiment.fear_greed, sentiment.fear_greed_label)
        if a:
            self.alerts.emit(a)
            self._prev_fng = sentiment.fear_greed

        members = self.universe.members if self.universe else []
        for m in members:
            try:
                res = self.analyze_symbol(m.symbol, m, sentiment, onchain)
            except Exception as e:
                self._err(f"analyze {m.symbol}", e)
                continue
            self.analyses[m.symbol] = res
            opp = res["opportunity"]
            prev = self.opportunities.get(m.symbol)
            self.opportunities[m.symbol] = opp
            try:
                opp_id = self.repo.save_opportunity(opp)
                self.repo.save_snapshot(m.symbol, res["ticker"] or {}, {"score_long": opp["score_long"],
                                                                         "score_short": opp["score_short"]})
            except Exception as e:
                self._err("persist opportunity", e)
                opp_id = None
            for tf in ("15m", "1h"):
                tfa = self._tfa(res, tf)
                if tfa:
                    al = rules.breakout_alert(m.symbol, tfa)
                    if al:
                        self.alerts.emit(al, key_extra=tf)
            for tf in ("5m", "15m", "1h"):
                tfa = self._tfa(res, tf)
                if tfa:
                    al = rules.unusual_volume_alert(m.symbol, tfa)
                    if al:
                        self.alerts.emit(al, key_extra=tf)
            tfa = self._tfa(res, "1h")
            if tfa:
                al = rules.volatility_alert(m.symbol, tfa)
                if al:
                    self.alerts.emit(al)
            if opp["status"] == "SIGNAL":
                is_new = not prev or prev.get("status") != "SIGNAL" or prev.get("direction") != opp["direction"]
                if is_new:
                    self.alerts.emit(rules.signal_alert(opp), key_extra=opp["direction"])
                if self.s.paper_auto_trade and opp.get("price"):
                    t = self.broker.open(symbol=m.symbol, side=opp["direction"], price=opp["price"], stop=opp["stop"],
                                         take_profits=opp["take_profits"], leverage=self.s.paper_leverage,
                                         risk_pct=self.s.risk_per_trade, score=opp["score"], opportunity_id=opp_id)
                    if t:
                        self.last_paper_bar[m.symbol] = pd.Timestamp(t.entry_time).floor("1min")
                        self._persist_trade(t.to_dict())

        self.update_paper()
        self.overview = self.build_overview(raw_tickers, btc_d, sentiment, onchain)
        self.last_scan_at = utcnow()
        self.scan_duration = time.time() - t0
        log.info("scan complete in %.1fs (%d symbols, %d signals)", self.scan_duration, len(members),
                 sum(1 for o in self.opportunities.values() if o["status"] == "SIGNAL"))

    @staticmethod
    def _tfa(res: dict, tf: str):
        from ..analysis.timeframe import TimeframeAnalysis

        d = res["timeframes"].get(tf)
        if not d or not d.get("sufficient"):
            return None
        d = dict(d)
        d["last_close_time"] = None
        return TimeframeAnalysis(**d)

    # ------------------------------------------------------------------ paper trading
    def _persist_trade(self, t: dict) -> None:
        try:
            self.repo.upsert_paper_trade(t)
            self.repo.save_paper_account(self.broker.balance, self.broker.starting_equity)
        except Exception as e:
            self._err("persist paper trade", e)

    def update_paper(self) -> None:
        now_ms = int(utcnow().timestamp() * 1000)
        for t in self.broker.open_trades():
            sym = t.symbol
            tick = self.tickers.get(sym)
            # funding settlement
            if tick and tick.get("next_funding_ms"):
                pend = self.pending_funding.get(sym)
                if pend and now_ms >= pend[0]:
                    self.broker.apply_funding(sym, pend[1], datetime.fromtimestamp(pend[0] / 1000, tz=timezone.utc))
                self.pending_funding[sym] = (tick["next_funding_ms"], tick["funding_rate"])
            # replay closed 1m candles since the last processed bar (captures intrabar wicks)
            try:
                df = self.client.klines(sym, "1m", limit=200)
            except Exception as e:
                self._err(f"paper klines {sym}", e)
                continue
            start = self.last_paper_bar.get(sym, pd.Timestamp(t.entry_time).floor("1min"))
            new = df[df.index > start]
            for ts, r in new.iterrows():
                for ev in self.broker.on_bar(sym, r.open, r.high, r.low, r.close, ts.to_pydatetime()):
                    self.alerts.emit(rules.paper_event_alert(ev), key_extra=f"{ev['trade_id']}{ev['reason']}")
                self.last_paper_bar[sym] = ts
            if tick and tick.get("last_price"):
                self.broker.marks[sym] = tick["last_price"]
            self._persist_trade(self.broker.trades[t.id].to_dict())
        perf = self.broker.performance()
        al = rules.drawdown_alert(perf.get("current_drawdown_pct", 0), self.s.drawdown_alert_pct)
        if al:
            self.alerts.emit(al)

    async def on_ws_message(self, topic: str, msg: dict) -> None:
        if not topic.startswith("tickers."):
            return
        sym = topic.split(".", 1)[1]
        lp = (self.ws.last_ticker.get(sym) or {}).get("lastPrice") if self.ws else None
        if lp and any(t.symbol == sym for t in self.broker.open_trades()):
            p = float(lp)
            for ev in self.broker.on_bar(sym, p, p, p, p):
                self.alerts.emit(rules.paper_event_alert(ev), key_extra=f"{ev['trade_id']}{ev['reason']}")
                self._persist_trade(self.broker.trades[ev["trade_id"]].to_dict())

    # ------------------------------------------------------------------ overview
    def build_overview(self, raw_tickers, btc_d, sentiment, onchain) -> dict:
        syms = self.universe.symbols() if self.universe else []
        idx = mkt.universe_index(raw_tickers, syms)
        now = utcnow()

        def px(sym):
            t = self.tickers.get(sym) or {}
            return {"price": t.get("last_price"), "change_24h_pct": t.get("change_24h_pct"),
                    "turnover_24h": t.get("turnover_24h"), "funding_rate": t.get("funding_rate"),
                    "open_interest_value": t.get("open_interest_value")}

        return _clean({
            "as_of": now.isoformat(),
            "prices_age": humanize_age((now - self.tickers_at).total_seconds()) if self.tickers_at else None,
            "btc": px("BTCUSDT"), "eth": px("ETHUSDT"),
            "market_index": idx, "direction": mkt.market_direction(btc_d, idx),
            "btc_realised_vol": mkt.realised_volatility(btc_d),
            "sentiment": sentiment.to_dict(), "onchain": onchain,
            "upcoming_events": [e.to_dict(now) for e in self.calendar.upcoming(7, now)],
            "calendar": {"loaded": self.calendar.loaded, "path": self.calendar.path, "errors": self.calendar.errors[:5]},
            "universe": self.universe.to_dict() if self.universe else None,
            "signals": sum(1 for o in self.opportunities.values() if o["status"] == "SIGNAL"),
            "scan_duration_s": self.scan_duration,
            "websocket": {"enabled": self.ws is not None,
                          "last_message": self.ws.last_message_at.isoformat() if self.ws and self.ws.last_message_at else None},
            "news_age": humanize_age(time.time() - self.news_at) if self.news_at else None,
        })

    # ------------------------------------------------------------------ runner
    async def run_forever(self) -> None:
        if self.s.enable_websocket:
            try:
                await asyncio.to_thread(self.refresh_universe)
                syms = self.universe.symbols() if self.universe else self.s.core_symbols
                self.ws = BybitPublicWS(self.s.bybit_ws_linear, build_topics(syms))
                self.ws.add_handler(self.on_ws_message)
                asyncio.create_task(self.ws.run_forever())
            except Exception as e:
                self._err("websocket start", e)
        while True:
            try:
                await asyncio.to_thread(self.scan)
            except Exception as e:
                self._err("scan", e)
            await asyncio.sleep(self.s.scan_interval_seconds)
