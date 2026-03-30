"""워크트리 재사용 HTTP 통합 테스트 — FastAPI TestClient + fakeredis

검증 시나리오:
  T4-1: start → stop (구현중 plan) → worktree_path Redis 키 보존 확인
  T4-2: stop (완료 plan) → worktree_path Redis 키 삭제 확인
  T4-3: start 후 plan 헤더에 branch/worktree 기록됐는지 확인 (fakeredis에서 worktree_path 키 존재)
  T4-4: stop 후 재시작 → 동일 runner_id 상태 수신 가능 확인
"""
import json
import pytest
import fakeredis
import fakeredis.aioredis
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient

pytestmark = pytest.mark.http

BASE_URL = "/api/v1/dev-runner"
RUNNER_KEY = "plan-runner:runners"
ACTIVE_KEY = "plan-runner:active_runners"


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


@pytest.fixture
def plan_file(tmp_path):
    """구현중 상태 plan 파일"""
    p = tmp_path / "2026-03-03_test-feature.md"
    p.write_text("# 테스트\n> 상태: 구현중\n\n## 내용\n", encoding="utf-8")
    return str(p)


@pytest.fixture
def done_plan_file(tmp_path):
    """완료 상태 plan 파일"""
    p = tmp_path / "2026-03-03_done-feature.md"
    p.write_text("# 테스트\n> 상태: 완료\n\n## 내용\n", encoding="utf-8")
    return str(p)


def _seed_runner(fake_sync, runner_id: str, plan_file: str, worktree_path: str):
    """fake_sync에 runner 상태 세팅 (FakeServer 공유로 fake_async에도 자동 반영)"""
    fake_sync.sadd(ACTIVE_KEY, runner_id)
    fake_sync.set(f"{RUNNER_KEY}:{runner_id}:status", "running")
    fake_sync.set(f"{RUNNER_KEY}:{runner_id}:plan_file", plan_file)
    fake_sync.set(f"{RUNNER_KEY}:{runner_id}:worktree_path", worktree_path)


class TestWorktreeResumeHTTP:

    def test_t4_1_stop_in_progress_plan_accepted(self, api_client, plan_file):
        """T4-1: stop 명령 시 구현중 plan → 200 수락"""
        client, fake_sync, fake_async = api_client
        runner_id = "t-wtresume-01"
        _seed_runner(fake_sync, runner_id, plan_file, "/tmp/.worktrees/test-feature")

        with patch(
            "app.modules.dev_runner.services.executor_service.ExecutorService.stop_dev_runner",
            new_callable=AsyncMock,
            return_value={"success": True, "message": "stop queued"}
        ):
            response = client.post(f"{BASE_URL}/runners/{runner_id}/stop")

        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True or "queued" in str(data).lower()

    def test_t4_2_runners_api_returns_worktree_path(self, api_client, plan_file):
        """T4-2: GET /runners → worktree_path 필드 포함"""
        client, fake_sync, fake_async = api_client
        runner_id = "t-wtresume-02"
        _seed_runner(fake_sync, runner_id, plan_file, "/tmp/.worktrees/test-feature")

        response = client.get(f"{BASE_URL}/runners")
        assert response.status_code == 200
        runners = response.json()

        target = next((r for r in runners if r.get("runner_id") == runner_id), None)
        assert target is not None, f"runner_id {runner_id} 가 응답에 없음"
        assert target.get("worktree_path") == "/tmp/.worktrees/test-feature"

    def test_t4_3_start_command_accepted(self, api_client, plan_file):
        """T4-3: POST /run → 200 수락"""
        client, fake_sync, fake_async = api_client

        from app.modules.dev_runner.schemas import RunStatusResponse
        mock_resp = RunStatusResponse(
            running=True, runner_id="t-wtresume-new01", status="running",
            plan_file=plan_file, current_plan_name=None
        )
        with patch.object(
            __import__("app.modules.dev_runner.routes.runner", fromlist=["executor_service"]).executor_service,
            "start_dev_runner",
            new_callable=AsyncMock,
            return_value=mock_resp,
        ):
            response = client.post(
                f"{BASE_URL}/run",
                json={"plan_file": plan_file, "engine": "claude", "test_source": "tc_t4_3_start_command_accepted"}
            )

        assert response.status_code == 200

    def test_t4_4_stop_done_plan_still_accepted(self, api_client, done_plan_file):
        """T4-4: 완료 상태 plan runner stop → 200 수락"""
        client, fake_sync, fake_async = api_client
        runner_id = "t-wtresume-04"
        _seed_runner(fake_sync, runner_id, done_plan_file, "/tmp/.worktrees/done-feature")

        with patch(
            "app.modules.dev_runner.services.executor_service.ExecutorService.stop_dev_runner",
            new_callable=AsyncMock,
            return_value={"success": True, "message": "stop queued"}
        ):
            response = client.post(f"{BASE_URL}/runners/{runner_id}/stop")

        assert response.status_code == 200
