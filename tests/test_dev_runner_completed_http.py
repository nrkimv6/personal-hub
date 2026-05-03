"""HTTP contract for dev-runner log SSE completion frames."""

import pytest
from fastapi.testclient import TestClient


pytestmark = pytest.mark.http


class _OneShotCompletedPubSub:
    def __init__(self):
        self._sent = False

    async def subscribe(self, channel):
        self.channel = channel

    async def get_message(self, ignore_subscribe_messages=True, timeout=0.5):
        if self._sent:
            return None
        self._sent = True
        return {"type": "message", "data": "__COMPLETED::success__"}

    async def unsubscribe(self):
        return None

    async def punsubscribe(self):
        return None

    async def aclose(self):
        return None


class _CompletedRedis:
    async def ping(self):
        return True

    def pubsub(self):
        return _OneShotCompletedPubSub()


def test_dev_runner_log_stream_emits_completed_event(monkeypatch):
    """GET /logs/stream converts __COMPLETED into an SSE completed event."""
    from app.main import app
    from app.modules.dev_runner.routes import logs as logs_route

    monkeypatch.setattr(logs_route.log_service, "async_redis", _CompletedRedis())

    with TestClient(app) as client:
        with client.stream("GET", "/api/v1/dev-runner/logs/stream?runner_id=t5-completed") as response:
            body = "".join(response.iter_text())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: connected" in body
    assert "event: completed" in body
    assert "data: success" in body
