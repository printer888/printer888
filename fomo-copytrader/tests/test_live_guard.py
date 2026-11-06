import json

import pytest
from helpers import FakeMarket

from fomo_copytrader.config import LIVE_ACK_PHRASE, Settings
from fomo_copytrader.execution.live import LiveExecutor, LiveTradingNotAuthorised


def test_live_executor_refuses_without_full_authorisation(tmp_path):
    for kw in [dict(execution_mode="paper"), dict(execution_mode="live", live_trading_ack="yes"),
               dict(execution_mode="live", live_trading_ack=LIVE_ACK_PHRASE)]:
        with pytest.raises(LiveTradingNotAuthorised):
            LiveExecutor(Settings(_env_file=None, **kw), None, None, FakeMarket(), is_armed=lambda: True)


async def test_live_executor_requires_runtime_arming(tmp_path):
    from solders.keypair import Keypair
    kp = Keypair()
    path = tmp_path / "kp.json"
    path.write_text(json.dumps(list(bytes(kp))))
    s = Settings(_env_file=None, execution_mode="live", live_trading_ack=LIVE_ACK_PHRASE, wallet_keypair_path=str(path))
    ex = LiveExecutor(s, None, None, FakeMarket(), is_armed=lambda: False)
    assert ex.pubkey == str(kp.pubkey())
    with pytest.raises(LiveTradingNotAuthorised):
        await ex.buy("mint", 6, 10.0, 100)
    assert not hasattr(ex, "transfer") and not hasattr(ex, "withdraw")
