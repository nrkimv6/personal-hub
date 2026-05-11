from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.claude_worker.routes import profile_routes

pytestmark = pytest.mark.http


class _FakeRedis:
    def __init__(self, result: dict | None = None):
        self.payloads: list[str] = []
        self.result = result

    async def lpush(self, key: str, payload: str) -> int:
        assert key == "worker:launch-cli"
        self.payloads.append(payload)
        return 1

    async def lindex(self, key: str, index: int):
        assert key.startswith("worker:launch-cli:results:")
        assert index == 0
        if self.result is None:
            return None
        return json.dumps(self.result, ensure_ascii=False)

    async def brpop(self, *_args, **_kwargs):
        raise AssertionError("launch-cli route must not wait with BRPOP")


def _client() -> TestClient:
    app = FastAPI()
    app.dependency_overrides[profile_routes.require_admin] = lambda: object()
    app.include_router(profile_routes.router, prefix="/api/v1/llm")
    return TestClient(app)


def _profiles() -> dict:
    return {
        "selected": {"claude": "default"},
        "profiles": [
            {
                "engine": "claude",
                "name": "default",
                "config_dir": None,
                "extra_env": {},
                "enabled": True,
                "priority": 0,
                "capacity": 1,
            }
        ],
    }


def test_launch_cli_returns_accepted_without_brpop_R(monkeypatch):
    fake_redis = _FakeRedis()

    async def get_client():
        return fake_redis

    monkeypatch.setattr(
        "app.modules.claude_worker.services.profile_store.load_profiles",
        _profiles,
    )
    monkeypatch.setattr(
        "app.shared.redis.client.RedisClient.get_client",
        staticmethod(get_client),
    )

    with _client() as client:
        resp = client.post("/api/v1/llm/profiles/claude/default/launch-cli")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "accepted"
    assert body["command_id"]
    assert body["result_key"].endswith(body["command_id"])
    payload = json.loads(fake_redis.payloads[0])
    assert payload["command_id"] == body["command_id"]
    assert payload["result_key"] == body["result_key"]


def test_launch_cli_result_pending_without_blocking_R(monkeypatch):
    fake_redis = _FakeRedis()

    async def get_client():
        return fake_redis

    monkeypatch.setattr(
        "app.shared.redis.client.RedisClient.get_client",
        staticmethod(get_client),
    )

    with _client() as client:
        resp = client.get("/api/v1/llm/profiles/claude/default/launch-cli/commands/abc")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pending"
    assert body["command_id"] == "abc"
