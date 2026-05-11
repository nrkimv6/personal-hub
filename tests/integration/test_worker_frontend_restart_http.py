"""Worker frontend restart Redis relay HTTP contract tests."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


class FakeRedis:
    def __init__(self, result: dict[str, Any] | None = None):
        self.commands: list[str] = []
        self.result = result or {"success": True, "message": "ok", "pid": None}

    async def delete(self, key: str) -> None:
        self.deleted_key = key

    async def lpush(self, key: str, value: str) -> None:
        self.command_key = key
        self.commands.append(value)

    async def brpop(self, key: str, timeout: int = 0):
        return key, json.dumps(self.result)


@pytest.fixture
def client():
    from app.main import app

    return TestClient(app)


def test_restart_frontend_endpoint_R_pushes_redis_command(client):
    """R: POST /worker/restart-frontend pushes restart-frontend command JSON."""
    fake = FakeRedis()

    with patch("app.shared.redis.client.RedisClient.get_client", return_value=fake):
        resp = client.post("/api/v1/worker/restart-frontend")

    assert resp.status_code == 200
    assert resp.json()["success"] is True
    payload = json.loads(fake.commands[0])
    assert fake.command_key == "worker:commands"
    assert payload["action"] == "restart-frontend"
    assert payload["public"] is False


def test_restart_frontend_endpoint_B_public_true_sets_payload(client):
    """B: public=true query is preserved in Redis command payload."""
    fake = FakeRedis()

    with patch("app.shared.redis.client.RedisClient.get_client", return_value=fake):
        resp = client.post("/api/v1/worker/restart-frontend?public=true")

    assert resp.status_code == 200
    payload = json.loads(fake.commands[0])
    assert payload["action"] == "restart-frontend"
    assert payload["public"] is True


def test_restart_frontend_endpoint_E_redis_missing_returns_manual_hint(client):
    """E: Redis unavailable response includes direct restart-frontend fallback hint."""
    with patch("app.shared.redis.client.RedisClient.get_client", return_value=None):
        resp = client.post("/api/v1/worker/restart-frontend?public=true")

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert "browser-workers.ps1 -Action restart-frontend -Public" in data["message"]
