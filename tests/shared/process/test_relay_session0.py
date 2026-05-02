import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.shared.process import relay
from app.shared.redis.queue import OPEN_APP_COMMAND_QUEUE


@pytest.mark.asyncio
async def test_relay_open_app_session0_pushes_worker_open_app_queue(monkeypatch):
    monkeypatch.setattr(relay.session, "is_session_0", lambda: True)

    client = MagicMock()
    client.lpush = AsyncMock()
    client.aclose = AsyncMock()
    monkeypatch.setattr(relay.aioredis, "Redis", MagicMock(return_value=client))

    result = await relay.relay_open_app("explorer", ["/select,", "D:\\work\\file.png"])

    assert result == {"via": "redis", "app": "explorer"}
    client.lpush.assert_awaited_once()
    queue_name, raw_payload = client.lpush.await_args.args
    assert queue_name == OPEN_APP_COMMAND_QUEUE
    assert json.loads(raw_payload) == {
        "app_name": "explorer",
        "args": ["/select,", "D:\\work\\file.png"],
    }


@pytest.mark.asyncio
async def test_relay_open_app_session0_redis_failure_does_not_popen(monkeypatch):
    monkeypatch.setattr(relay.session, "is_session_0", lambda: True)

    client = MagicMock()
    client.lpush = AsyncMock(side_effect=ConnectionError("redis down"))
    client.aclose = AsyncMock()
    monkeypatch.setattr(relay.aioredis, "Redis", MagicMock(return_value=client))
    mock_popen = MagicMock()
    monkeypatch.setattr(relay.subprocess, "Popen", mock_popen)

    with pytest.raises(relay.OpenAppRelayError):
        await relay.relay_open_app("explorer", ["D:\\work"])

    mock_popen.assert_not_called()
