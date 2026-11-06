import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from helpers import TOKEN, TOKEN2, TRADER, FakeMarket, FakeRpc, safe_token  # noqa: E402

from fomo_copytrader.config import Settings  # noqa: E402
from fomo_copytrader.notify.telegram import Notifier  # noqa: E402
from fomo_copytrader.runtime import Runtime  # noqa: E402
from fomo_copytrader.schemas import RiskLimits  # noqa: E402


@pytest.fixture
def market():
    m = FakeMarket()
    m.add_token(TOKEN, price=0.0025, symbol="BONKX")
    m.add_token(TOKEN2, price=1.2, symbol="WIFX")
    return m


@pytest.fixture
def settings(tmp_path):
    return Settings(app_env="test", database_url=f"sqlite+aiosqlite:///{tmp_path}/t.db",
                    telegram_bot_token=None, telegram_chat_id=None, paper_extra_slippage_bps=50,
                    _env_file=None)


@pytest.fixture
async def rt(settings, market):
    r = Runtime(settings, market=market, rpc=FakeRpc(), notifier=Notifier(None, None),
                safety_inspector=_safety, enable_ws=False)
    await r.init()
    await r.state.set_limits(RiskLimits(total_capital_usd=1000, fixed_position_usd=25, max_position_usd=50,
                                        min_liquidity_usd=50_000, min_volume_24h_usd=100_000))
    await r.set_trader(TRADER, label="Top FOMO Trader")
    await r.state.update_status(monitoring=True, copying=True)
    yield r
    await r.monitor.stop()
    await r.db_engine.dispose()


async def _safety(mint):
    return safe_token(mint)
