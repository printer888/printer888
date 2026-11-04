"""End-to-end: full scan against a mocked Bybit API, then the REST API."""
import pytest
from fastapi.testclient import TestClient

from cryptointel.alerts.rules import Alert, AlertManager
from cryptointel.alerts.telegram import TelegramNotifier
from cryptointel.api.main import create_app
from cryptointel.config import Settings
from cryptointel.db.repository import Repository
from cryptointel.services import monitor


@pytest.fixture
def service(fake_bybit, tmp_path, monkeypatch):
    fb, client = fake_bybit
    monkeypatch.setattr(monitor, "fetch_fear_greed", lambda *a, **k: None)
    monkeypatch.setattr(monitor, "fetch_stablecoin_supply", lambda *a, **k: None)
    s = Settings(database_url=f"sqlite:///{tmp_path / 't.db'}", news_feeds=[], enable_websocket=False,
                 calendar_path=str(tmp_path / "none.json"), timeframes=["5m", "15m", "1h", "4h", "1d"])
    svc = monitor.IntelligenceService(s, client=client, repo=Repository(s.database_url),
                                      notifier=TelegramNotifier("", ""))
    return svc


def test_full_scan(service):
    service.scan()
    assert service.last_scan_at is not None
    assert set(service.opportunities) == {"BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"}
    for o in service.opportunities.values():
        assert 0 <= o["score"] <= 100
        assert o["status"] in ("SIGNAL", "NO_TRADE")
        if o["status"] == "NO_TRADE":
            assert o["gate_failures"] and o["entry"] is None
        # calendar/news/sentiment are not available in this test → must be listed as missing
        assert any("calendar" in m or "macro" in m for m in o["missing_data"])
        # news (15) + sentiment/on-chain (10) unavailable → those 25 points can never be earned
        assert o["score_long"] <= 75 and o["score_short"] <= 75
    assert service.overview["btc"]["price"] == 60000
    assert service.repo.recent_opportunities(10)


def test_api_endpoints(service):
    app = create_app(service=service, autostart=False, settings=service.s)
    with TestClient(app) as c:
        assert c.get("/api/health").json()["status"] == "ok"
        assert c.get("/api/overview").json()["ready"] is False
        assert c.post("/api/scan").json()["ok"]
        ov = c.get("/api/overview").json()
        assert ov["ready"] and "paper" in ov
        items = c.get("/api/opportunities").json()["items"]
        assert len(items) == 5
        a = c.get("/api/analysis/BTCUSDT").json()
        assert "1h" in a["timeframes"] and "opportunity" in a
        assert c.get("/api/analysis/NOPE").status_code == 404
        cd = c.get("/api/candles/BTCUSDT?tf=1h&limit=100").json()
        assert cd["closed_candles_only"] and 0 < len(cd["rows"]) <= 100
        lev = c.post("/api/leverage/simulate", json={"entry": 100, "stop": 97, "targets": [106]}).json()
        assert len(lev["fixed_risk"]) == 6
        bad = c.post("/api/leverage/simulate", json={"entry": 100, "stop": 103, "targets": [106]})
        assert bad.status_code == 422
        assert isinstance(c.get("/api/paper/trades").json(), list)
        assert "equity" in c.get("/api/paper/performance").json()
        cfg = c.get("/api/config").json()
        assert "database_url" in cfg
        assert c.get("/").status_code == 200  # dashboard served


def test_alert_cooldown_and_html_escaping():
    sent = []

    class N(TelegramNotifier):
        def send(self, text):
            sent.append(text)
            return True

    m = AlertManager(N("t", "c"), cooldown_minutes=60)
    a = Alert("x", "BTCUSDT", "<b>t</b>", ["e < f"], ["r"])
    assert m.emit(a) and not m.emit(a)
    assert "&lt;b&gt;t&lt;/b&gt;" in sent[0] and "not financial advice" in sent[0]


def test_settings_redaction():
    s = Settings(telegram_bot_token="123:secret", database_url="postgresql://u:pw@db/x")
    r = s.redacted()
    assert r["telegram_bot_token"] == "***" and "pw" not in r["database_url"]
