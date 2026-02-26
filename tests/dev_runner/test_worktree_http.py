"""Worktree API HTTP 통합 테스트 — FastAPI TestClient 기반 (dev-runner 라우터 직접 마운트)"""
import json
import pytest
import fakeredis
import fakeredis.aioredis
from unittest.mock import patch, AsyncMock
from fastapi import FastAPI
from fastapi.testclient import TestClient

pytestmark = pytest.mark.http

BASE_URL = "/api/v1/dev-runner"


@pytest.fixture
def fake_sync():
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def fake_async():
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.fixture
def api_client(fake_sync, fake_async):
    """dev-runner 라우터만 포함한 격리 TestClient"""
    from app.modules.dev_runner.routes import router as dev_runner_router
    from app.modules.dev_runner.services.executor_service import executor_service

    # fakeredis 주입
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


class TestWorktreeHTTP:
    def test_http_2_get_runners_has_worktree_fields(self, api_client):
        """HTTP-2: GET /runners → worktree_path, branch, merge_status 필드 존재"""
        client, fake_sync, fake_async = api_client

        # active runner 등록
        fake_sync.sadd("plan-runner:active_runners", "testrunner")
        fake_sync.set("plan-runner:runners:testrunner:status", "running")
        fake_sync.set("plan-runner:runners:testrunner:worktree_path", "/tmp/wt/testrunner")
        fake_sync.set("plan-runner:runners:testrunner:merge_status", "merged")

        response = client.get("/api/v1/dev-runner/runners")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        item = data[0]
        assert "worktree_path" in item
        assert "branch" in item
        assert "merge_status" in item
        assert item["worktree_path"] == "/tmp/wt/testrunner"
        assert item["merge_status"] == "merged"

    def test_http_3_retry_merge_sends_command(self, api_client):
        """HTTP-3: POST /runners/{runner_id}/retry-merge → 200"""
        client, fake_sync, fake_async = api_client

        with patch(
            "app.modules.dev_runner.services.executor_service.ExecutorService.send_runner_command",
            new_callable=AsyncMock,
            return_value={"success": True, "message": "retry queued"}
        ):
            response = client.post("/api/v1/dev-runner/runners/abc123/retry-merge")

        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True

    def test_http_4_delete_worktree_sends_command(self, api_client):
        """HTTP-4: DELETE /runners/{runner_id}/worktree → 200"""
        client, fake_sync, fake_async = api_client

        with patch(
            "app.modules.dev_runner.services.executor_service.ExecutorService.send_runner_command",
            new_callable=AsyncMock,
            return_value={"success": True, "message": "cleanup queued"}
        ):
            response = client.delete("/api/v1/dev-runner/runners/abc123/worktree")

        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True

    def test_http_5_over_limit_returns_429(self, api_client):
        """HTTP-5: MAX 초과 시 → 429"""
        client, fake_sync, fake_async = api_client

        with patch(
            "app.modules.dev_runner.services.executor_service.ExecutorService._check_redis_and_listener",
            new_callable=AsyncMock
        ):
            with patch("app.modules.dev_runner.services.executor_service.config") as mock_cfg:
                mock_cfg.MAX_CONCURRENT_RUNNERS = 3

                async def fake_scard(key):
                    return 3

                with patch.object(type(fake_async), "scard", side_effect=fake_scard):
                    response = client.post("/api/v1/dev-runner/run", json={})

        assert response.status_code == 429
        detail = response.json().get("detail", "")
        assert "3" in detail

    def test_http_1_post_run_returns_runner_id(self, api_client):
        """HTTP-1: POST /run → runner_id 포함 (mock Redis 응답)"""
        client, fake_sync, fake_async = api_client

        with patch(
            "app.modules.dev_runner.services.executor_service.ExecutorService._check_redis_and_listener",
            new_callable=AsyncMock
        ):
            with patch("app.modules.dev_runner.services.executor_service.config") as mock_cfg:
                mock_cfg.MAX_CONCURRENT_RUNNERS = 3

                async def fake_scard(key):
                    return 0

                async def fake_lpush(key, value):
                    return 1

                async def fake_brpop(key, timeout=0):
                    return (key, json.dumps({"success": True}))

                async def fake_get(key):
                    if ":pid" in key:
                        return "12345"
                    if ":plan_file" in key:
                        return "test.md"
                    if ":start_time" in key:
                        return "2026-02-26T00:00:00"
                    return None

                with patch.object(type(fake_async), "scard", side_effect=fake_scard), \
                     patch.object(type(fake_async), "lpush", side_effect=fake_lpush), \
                     patch.object(type(fake_async), "brpop", side_effect=fake_brpop), \
                     patch.object(type(fake_async), "get", side_effect=fake_get):
                    response = client.post("/api/v1/dev-runner/run", json={})

        assert response.status_code == 200
        data = response.json()
        assert "runner_id" in data
        assert data["running"] is True
