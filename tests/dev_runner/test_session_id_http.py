"""T5 HTTP: session_id 라운드트립 HTTP 통합 테스트

검증 범위:
- POST /api/v1/dev-runner/run 200 + body에 UUID session_id
- GET /api/v1/dev-runner/runners/{runner_id} → session_id 포함
- 명시적 session_id 유지
- 잘못된 타입 → 422
- fused_session=True → 응답 정상
- GET /runners 목록에 session_id 노출 (RunnerListItem 포함 시)

※ main 머지 후 /merge-test에서 실행. 워크트리에서는 작성만.
   plan-runner 간접 실행 모듈 (feedback_t5_indirect_module 적용 대상)
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from unittest.mock import patch

import fakeredis
import fakeredis.aioredis
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

pytestmark = pytest.mark.http

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


def _mock_start_send(fake_async, runner_id_ref: list):
    async def _mock(cmd):
        rid = cmd["runner_id"]
        runner_id_ref.append(rid)
        return {"success": True, "runner_id": rid, "status": "running"}
    return patch(
        "app.modules.dev_runner.services.executor_service.executor_service._send_command",
        side_effect=_mock,
    )


def _mock_fields_fn():
    async def _mock(*args, **kwargs):
        return {"pid": None, "plan_file": None, "start_time": None, "execution_count": None}
    return patch(
        "app.modules.dev_runner.services.executor_service.executor_service._get_runner_fields",
        side_effect=_mock,
    )


class TestSessionIdHTTP:
    def test_post_run_returns_session_id_http(self, api_client):
        """T5 R: POST /run 200 + body에 UUID4 session_id"""
        client, fake_sync, fake_async = api_client
        _setup_heartbeat(fake_sync)
        runner_id_ref = []

        with _mock_start_send(fake_async, runner_id_ref), _mock_fields_fn():
            resp = client.post(f"{BASE_URL}/run", json={"plan_file": "test.md", "test_source": "test_post_run_returns_session_id_http"})

        assert resp.status_code == 200, resp.text
        data = resp.json()
        sid = data.get("session_id")
        assert sid is not None
        assert _UUID_RE.match(sid), f"UUID 형식 아님: {sid}"
        uuid.UUID(sid, version=4)

    def test_get_run_status_includes_session_id_http(self, api_client):
        """T5 R: GET /runners/{runner_id} → session_id 포함"""
        client, fake_sync, fake_async = api_client
        runner_id = "t5-http-session-runner"

        # Redis에 runner 상태 + session_id 수동 세팅
        expected_sid = str(uuid.uuid4())
        fake_sync.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "completed")
        fake_sync.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:engine", "claude")
        fake_sync.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:start_time", datetime.now().isoformat())
        fake_sync.set(f"{SESSION_ID_PREFIX}{runner_id}", expected_sid)

        resp = client.get(f"{BASE_URL}/runners/{runner_id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data.get("session_id") == expected_sid

    def test_post_run_explicit_session_id_http(self, api_client):
        """T5 R: body 명시 session_id → 응답 동일"""
        client, fake_sync, fake_async = api_client
        _setup_heartbeat(fake_sync)
        explicit_sid = str(uuid.uuid4())
        runner_id_ref = []

        with _mock_start_send(fake_async, runner_id_ref), _mock_fields_fn():
            resp = client.post(
                f"{BASE_URL}/run",
                json={"plan_file": "test.md", "session_id": explicit_sid, "test_source": "test_post_run_explicit_session_id_http"},
            )

        assert resp.status_code == 200, resp.text
        assert resp.json().get("session_id") == explicit_sid

    def test_post_run_invalid_session_id_http(self, api_client):
        """T5 E: 잘못된 UUID 형식 session_id → 응답에 자동 재발급된 UUID"""
        client, fake_sync, fake_async = api_client
        _setup_heartbeat(fake_sync)
        runner_id_ref = []

        with _mock_start_send(fake_async, runner_id_ref), _mock_fields_fn():
            resp = client.post(
                f"{BASE_URL}/run",
                json={"plan_file": "test.md", "session_id": "not-a-uuid", "test_source": "test_post_run_invalid_session_id_http"},
            )

        assert resp.status_code == 200, resp.text
        sid = resp.json().get("session_id")
        assert sid != "not-a-uuid"
        uuid.UUID(sid, version=4)

    def test_post_run_fused_session_flag_http(self, api_client):
        """T5 R: fused_session=True → 응답 정상 + command dict에 fused_session"""
        client, fake_sync, fake_async = api_client
        _setup_heartbeat(fake_sync)
        runner_id_ref = []
        captured_cmd = {}

        async def _mock(cmd):
            runner_id_ref.append(cmd["runner_id"])
            captured_cmd.update(cmd)
            return {"success": True, "runner_id": cmd["runner_id"], "status": "running"}

        with patch(
            "app.modules.dev_runner.services.executor_service.executor_service._send_command",
            side_effect=_mock,
        ), _mock_fields_fn():
            resp = client.post(
                f"{BASE_URL}/run",
                json={"plan_file": "test.md", "fused_session": True, "test_source": "test_post_run_fused_session_flag_http"},
            )

        assert resp.status_code == 200, resp.text
        assert captured_cmd.get("fused_session") is True

    def test_get_runs_list_runner_id_visible_http(self, api_client):
        """T5 R: GET /runners 목록에 runner_id 포함"""
        client, fake_sync, fake_async = api_client
        runner_id = "t5-http-list-runner"

        fake_sync.sadd("plan-runner:active_runners", runner_id)
        fake_sync.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        fake_sync.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:engine", "claude")

        resp = client.get(f"{BASE_URL}/runners")
        assert resp.status_code == 200
        runners = resp.json()
        runner_ids = [r["runner_id"] for r in runners]
        assert runner_id in runner_ids

    def test_indirect_module_session_arg_propagated_http(self, api_client):
        """T5 Re: POST /run → command dict에 session_id 포함 (간접 실행 종단 검증)"""
        client, fake_sync, fake_async = api_client
        _setup_heartbeat(fake_sync)
        runner_id_ref = []
        captured_cmd = {}

        async def _mock(cmd):
            runner_id_ref.append(cmd["runner_id"])
            captured_cmd.update(cmd)
            return {"success": True, "runner_id": cmd["runner_id"], "status": "running"}

        with patch(
            "app.modules.dev_runner.services.executor_service.executor_service._send_command",
            side_effect=_mock,
        ), _mock_fields_fn():
            resp = client.post(f"{BASE_URL}/run", json={"plan_file": "test.md", "test_source": "test_indirect_module_session_arg_propagated_http"})

        assert resp.status_code == 200
        assert "session_id" in captured_cmd
        _UUID_RE.match(captured_cmd["session_id"])
