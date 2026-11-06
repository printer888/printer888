import pytest
from fastapi.testclient import TestClient
from helpers import TRADER, FakeMarket, FakeRpc, safe_token

from fomo_copytrader.api.app import create_app
from fomo_copytrader.config import Settings
from fomo_copytrader.notify.telegram import Notifier
from fomo_copytrader.runtime import Runtime


async def _safe(m):
    return safe_token(m)


@pytest.fixture
def client(tmp_path):
    s = Settings(app_env="test", database_url=f"sqlite+aiosqlite:///{tmp_path}/api.db", dashboard_token="secret",
                 _env_file=None)
    rt = Runtime(s, market=FakeMarket(), rpc=FakeRpc(), notifier=Notifier(None, None),
                 safety_inspector=_safe, enable_ws=False)
    app = create_app(rt, s, start_background=False)
    with TestClient(app) as c:
        c.headers["Authorization"] = "Bearer secret"
        yield c


def test_auth_required(client):
    assert client.get("/api/status", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.get("/health").status_code == 200


def test_dashboard_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "Copy Trader Console" in r.text


def test_trader_selection_and_validation(client):
    assert client.post("/api/trader", json={"wallet": "not-a-real-address-but-long-enough-xxxxx"}).status_code == 422
    r = client.post("/api/trader", json={"wallet": TRADER, "label": "Alpha"})
    assert r.status_code == 200
    assert client.get("/api/status").json()["trader"]["label"] == "Alpha"


def test_risk_update_validation(client):
    r = client.get("/api/risk").json()
    r["max_position_usd"] = 10
    r["min_position_usd"] = 20
    assert client.put("/api/risk", json=r).status_code == 422
    r["min_position_usd"] = 5
    assert client.put("/api/risk", json=r).json()["max_position_usd"] == 10


def test_controls_and_emergency(client):
    assert client.post("/api/control/start_monitoring").status_code == 400  # no trader yet
    client.post("/api/trader", json={"wallet": TRADER})
    assert client.post("/api/control/start_copying").json()["status"]["copying"] is True
    client.post("/api/control/pause")
    assert client.get("/api/status").json()["status"]["paused"] is True
    client.post("/api/control/emergency_stop", json={"flatten": True})
    st = client.get("/api/status").json()["status"]
    assert st["emergency_stop"] and not st["copying"] and not st["live_armed"]
    assert client.post("/api/control/start_copying").status_code == 409
    client.post("/api/control/clear_emergency")
    assert client.post("/api/control/start_copying").status_code == 200
    client.post("/api/control/stop_monitoring")


def test_live_cannot_be_armed_in_paper_config(client):
    r = client.post("/api/control/arm_live", json={"confirm": "I_UNDERSTAND_REAL_FUNDS_ARE_AT_RISK"})
    assert r.status_code == 403


def test_reports(client):
    assert "performance report" in client.get("/api/report.md").text
    assert client.get("/api/report").json()["open_positions"] == 0


def test_websocket_requires_token(client):
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"token": "secret"})
        assert ws.receive_json()["topic"] == "status"


def test_prod_requires_token(tmp_path):
    s = Settings(app_env="prod", database_url=f"sqlite+aiosqlite:///{tmp_path}/p.db", dashboard_token=None,
                 _env_file=None)
    with pytest.raises(RuntimeError):
        create_app(settings=s)
