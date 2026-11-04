import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from cryptointel.analysis.macro import load_calendar
from cryptointel.analysis.news import NewsEvent, asset_news_assessment, classify
from cryptointel.config import Settings
from cryptointel.data.bybit_client import BybitAPIError, BybitClient, parse_ticker
from cryptointel.data.bybit_ws import BybitPublicWS
from cryptointel.universe import select_universe


def test_klines_ascending_and_open_candle_dropped(fake_bybit):
    fb, client = fake_bybit
    df = client.klines("BTCUSDT", "1h", limit=100, now_ms=fb.now_ms)
    assert df.index.is_monotonic_increasing
    assert len(df) == 99  # the still-forming candle is removed
    assert list(df.columns) == ["open", "high", "low", "close", "volume", "turnover"]


def test_business_error_raises():
    t = httpx.MockTransport(lambda r: httpx.Response(200, json={"retCode": 10001, "retMsg": "params error"}))
    c = BybitClient(transport=t, max_requests_per_second=0)
    with pytest.raises(BybitAPIError):
        c.tickers("linear", "NOPE")


def test_retry_on_server_error(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    calls = {"n": 0}

    def h(r):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503)
        return httpx.Response(200, json={"retCode": 0, "result": {"list": []}})

    c = BybitClient(transport=httpx.MockTransport(h), max_requests_per_second=0)
    assert c.tickers() == [] and calls["n"] == 3


def test_parse_ticker_spread():
    t = parse_ticker({"symbol": "X", "bid1Price": "99.99", "ask1Price": "100.01", "price24hPcnt": "0.05"})
    assert t["spread_bps"] == pytest.approx(2.0, rel=1e-3) and t["change_24h_pct"] == pytest.approx(5)


def test_universe_filters_illiquid_and_records_reasons(fake_bybit):
    fb, client = fake_bybit
    u = select_universe(client.instruments(), client.tickers(), Settings())
    assert "SHITUSDT" not in u.symbols() and "BTCUSDT" in u.symbols()
    assert any("turnover" in r for r in u.rejected["SHITUSDT"])


def test_universe_rejects_new_listing_and_stablecoins():
    now = datetime.now(timezone.utc)
    inst = [{"symbol": "NEWUSDT", "contractType": "LinearPerpetual", "status": "Trading", "baseCoin": "NEW",
             "quoteCoin": "USDT", "launchTime": str(int((now - timedelta(days=5)).timestamp() * 1000))},
            {"symbol": "USDCUSDT", "contractType": "LinearPerpetual", "status": "Trading", "baseCoin": "USDC",
             "quoteCoin": "USDT", "launchTime": "1"}]
    tick = [{"symbol": s, "turnover24h": "1e10", "openInterestValue": "1e9", "bid1Price": "1", "ask1Price": "1.0001",
             "price24hPcnt": "0"} for s in ("NEWUSDT", "USDCUSDT")]
    u = select_universe(inst, tick, Settings())
    assert not u.members
    assert any("listed" in r for r in u.rejected["NEWUSDT"])
    assert any("stablecoin" in r for r in u.rejected["USDCUSDT"])


def _ev(title, official=False, hours_ago=1):
    now = datetime.now(timezone.utc)
    return classify(NewsEvent(title=title, url=f"https://x/{hash(title)}", source="T", official_source=official,
                              published_at=now - timedelta(hours=hours_ago), fetched_at=now))


def test_news_classification():
    e = _ev("Solana DeFi protocol exploited, $40M drained by attacker")
    assert "hack" in e.event_types and "SOL" in e.assets and e.importance == "high" and e.sentiment < 0
    f = _ev("Federal Reserve announces interest rate decision", official=True)
    assert "monetary_policy" in f.event_types and f.confirmation.startswith("confirmed") and f.market_wide
    r = _ev("SEC reportedly considering approval of XRP ETF")
    assert r.confirmation.startswith("unconfirmed")
    assert e.bullish_case and e.bearish_case and e.impact_duration != "unknown"


def test_asset_news_assessment_flags_shocks_and_ignores_old():
    evs = [_ev("Solana bridge hack: funds stolen"), _ev("Bitcoin ETF inflows hit record", hours_ago=200)]
    a = asset_news_assessment(evs, "SOL", 72)
    assert a["critical_negative"]
    assert asset_news_assessment(evs, "BTC", 72)["count"] == 0


def test_calendar_requires_source(tmp_path):
    p = tmp_path / "cal.json"
    future = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat()
    p.write_text(json.dumps({"events": [
        {"name": "Good", "time": future, "impact": "high", "source_url": "https://www.federalreserve.gov"},
        {"name": "NoSource", "time": future, "impact": "high"}]}))
    cal = load_calendar(str(p))
    assert len(cal.events) == 1 and cal.errors
    assert cal.event_risk(24)["high_impact_events"][0]["name"] == "Good"
    assert not load_calendar(str(tmp_path / "missing.json")).loaded


def test_ws_processing_liquidations_and_trades():
    ws = BybitPublicWS("wss://x", [])
    now = int(datetime.now(timezone.utc).timestamp() * 1000)
    ws.process("allLiquidation.BTCUSDT", {"topic": "allLiquidation.BTCUSDT", "ts": now,
                                          "data": [{"T": now, "s": "BTCUSDT", "S": "Sell", "v": "2", "p": "100"}]})
    ws.process("publicTrade.BTCUSDT", {"data": [{"T": now, "s": "BTCUSDT", "S": "Buy", "v": "3", "p": "100"},
                                                {"T": now, "s": "BTCUSDT", "S": "Sell", "v": "1", "p": "100"}]})
    liq = ws.liquidations.summary("BTCUSDT", 3600)
    assert liq["long_liquidations_usd"] == 200 and liq["complete"] is False  # window not yet fully observed
    d = ws.trade_flow.delta("BTCUSDT", 60)
    assert d["delta_ratio"] == pytest.approx(0.5)
    ws.process("tickers.BTCUSDT", {"ts": now, "data": {"lastPrice": "101"}})
    ws.process("tickers.BTCUSDT", {"ts": now, "data": {"fundingRate": "0.0001"}})
    assert ws.last_ticker["BTCUSDT"]["lastPrice"] == "101"
