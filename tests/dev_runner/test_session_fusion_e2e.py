"""T4 E2E: session_id 파이프라인 검증 (TestClient + fakeredis)

검증 범위:
- POST /api/v1/dev-runner/run → session_id 응답 포함
- 명시적 session_id 유지
- INFO 로그에 [session] 패턴 포함

※ main 머지 후 /merge-test에서 실행. 워크트리에서는 작성만.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, patch

import fakeredis
import fakeredis.aioredis
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

pytestmark = pytest.mark.e2e

BASE_URL = "/api/v1/dev-runner"
RUNNER_KEY_PREFIX = "plan-runner:runners"
SESSION_ID_PREFIX = "plan-runner:session:"

_UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE,
)


@pytest.fixture(autouse=True)
def _plan_runner_redis_db_guard(monkeypatch):
    monkeypatch.setenv("PLAN_RUNNER_REDIS_DB", "15")


@pytest.fixture
def fake_server():
    return fakeredis.FakeServer()


@pytest.fixture
def fake_sync(fake_server):
    return fakeredis.FakeRedis(server=fake_server, decode_responses=True)


@pytest.fixture
def fake_async(fake_server):
    return fakeredis.aioredis.FakeRedis(server=fake_server, decode_responses=True)


@pytest.fixture
def api_client(fake_sync, fake_async):
    """dev-runner 라우터만 포함한 격리 TestClient"""
    from app.modules.dev_runner.routes import router as dev_runner_router
    from app.modules.dev_runner.services.executor_service import executor_service

    original_sync = executor_service.redis_client
    original_async = executor_service.async_redis
    executor_service.redis_client = fake_sync
    executor_service.async_redis = fake_async

    app = FastAPI()
    app.include_router(dev_runner_router)

    with TestClient(app) as client:
        yield client, fake_sync, fake_async

    executor_service.redis_client = original_sync
    executor_service.async_redis = original_async


def _setup_heartbeat(fake_sync):
    fake_sync.set("plan-runner:listener:heartbeat", datetime.now().isoformat())


def _mock_start(fake_async, runner_id_ref: list):
    """executor_service._send_command를 mock해 실제 listener 없이 start 테스트."""
    async def _mock_send(cmd):
        rid = cmd["runner_id"]
        runner_id_ref.append(rid)
        return {"success": True, "runner_id": rid, "status": "running"}

    return patch(
        "app.modules.dev_runner.services.executor_service.executor_service._send_command",
        side_effect=_mock_send,
    )


def _mock_fields(pid=None, plan_file=None, start_time=None, execution_count=None):
    async def _mock(*args, **kwargs):
        return {"pid": pid, "plan_file": plan_file, "start_time": start_time, "execution_count": execution_count}
    return patch(
        "app.modules.dev_runner.services.executor_service.executor_service._get_runner_fields",
        side_effect=_mock,
    )


class TestSessionFusionE2E:
    def test_e2e_run_includes_session_id_in_status(self, api_client):
        """T4 R: POST /run 응답에 UUID 형식 session_id 포함"""
        client, fake_sync, fake_async = api_client
        _setup_heartbeat(fake_sync)
        runner_id_ref = []

        with _mock_start(fake_async, runner_id_ref), _mock_fields():
            resp = client.post(f"{BASE_URL}/run", json={"plan_file": "test.md"})

        assert resp.status_code == 200, resp.text
        data = resp.json()
        sid = data.get("session_id")
        assert sid is not None
        assert _UUID_RE.match(sid), f"UUID 형식 아님: {sid}"

    def test_e2e_explicit_session_id_preserved(self, api_client):
        """T4 R: 명시적 session_id → 응답에 동일값 유지"""
        client, fake_sync, fake_async = api_client
        _setup_heartbeat(fake_sync)
        explicit_sid = str(uuid.uuid4())
        runner_id_ref = []

        with _mock_start(fake_async, runner_id_ref), _mock_fields():
            resp = client.post(
                f"{BASE_URL}/run",
                json={"plan_file": "test.md", "session_id": explicit_sid},
            )

        assert resp.status_code == 200, resp.text
        assert resp.json().get("session_id") == explicit_sid

    def test_e2e_session_id_in_log_line(self, api_client, caplog):
        """T4 Re: INFO 로그에 '[session] runner_id=... session_id=...' 패턴 포함"""
        import logging
        client, fake_sync, fake_async = api_client
        _setup_heartbeat(fake_sync)
        runner_id_ref = []

        with _mock_start(fake_async, runner_id_ref), _mock_fields():
            with caplog.at_level(logging.INFO):
                resp = client.post(f"{BASE_URL}/run", json={"plan_file": "test.md"})

        assert resp.status_code == 200
        session_logs = [r for r in caplog.records if "[session]" in r.getMessage()]
        assert session_logs, "INFO 로그에 [session] 패턴 없음"
        msg = session_logs[0].getMessage()
        assert "session_id=" in msg
