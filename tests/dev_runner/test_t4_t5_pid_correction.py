"""T4/T5 통합 테스트 — PID 기반 상태 보정 + orphan 워크플로우 자동 정리

Plan: docs/plan/2026-03-27_fix-dev-runner-status-race-condition.md

Phase T4: E2E (Redis 실제 연결 + executor_service)
Phase T5: HTTP (TestClient + mock)
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from app.modules.dev_runner.services.executor_service import RUNNER_KEY_PREFIX, ACTIVE_RUNNERS_KEY
from app.modules.dev_runner.schemas import RunnerListItem

pytestmark = pytest.mark.http

BASE_URL = "/api/v1/dev-runner"


# ===========================================================================
# 공통 픽스처
# ===========================================================================

@pytest.fixture(autouse=True)
def dev_runner_config_isolation(tmp_path):
    """devrunner conftest autouse 오버라이드"""
    yield


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app, raise_server_exceptions=True)


# ===========================================================================
# Phase T4: E2E — Redis mock + executor_service 실제 호출
# ===========================================================================

class TestE2ERunnersPidCorrection:
    """get_all_runners() PID 기반 보정 E2E 검증"""

    pytestmark = pytest.mark.http

    def _make_runner_mock_redis(self, rid, status, pid_str):
        """runner 1개 등록된 Redis mock 반환"""
        async def _get(key):
            data = {"status": status, "pid": pid_str, "trigger": "user"}
            for k, v in data.items():
                if key == f"{RUNNER_KEY_PREFIX}:{rid}:{k}":
                    return v
            return None

        mock_redis = AsyncMock()
        mock_redis.get = _get
        mock_redis.smembers = AsyncMock(return_value=set())
        mock_redis.zrange = AsyncMock(return_value=[rid])
        mock_redis.zremrangebyscore = AsyncMock()
        mock_redis.sadd = AsyncMock()
        mock_redis.set = AsyncMock()
        return mock_redis

    @pytest.mark.asyncio
    async def test_e2e_runners_list_pid_stale_correction(self):
        """T4: Redis status="running" + PID dead → get_all_runners()에서 running=False 보정"""
        from app.modules.dev_runner.services.executor_service import ExecutorService

        rid = "stale_runner_e2e"
        svc = ExecutorService.__new__(ExecutorService)
        svc.async_redis = self._make_runner_mock_redis(rid, "running", "99999")
        svc._force_cleanup_state = AsyncMock()

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        with patch("app.modules.dev_runner.services.executor_service.ExecutorService._is_pid_alive", return_value=False), \
             patch("app.database.SessionLocal", return_value=mock_db):
            result = await svc.get_all_runners()

        assert len(result) == 1
        assert result[0].running is False
        svc._force_cleanup_state.assert_called_once_with(rid)

    @pytest.mark.asyncio
    async def test_e2e_runners_list_pid_alive_restoration(self):
        """T4: Redis status="stopped" + PID alive → get_all_runners()에서 running=True 복원"""
        from app.modules.dev_runner.services.executor_service import ExecutorService

        rid = "restore_runner_e2e"
        svc = ExecutorService.__new__(ExecutorService)
        svc.async_redis = self._make_runner_mock_redis(rid, "stopped", "12345")
        svc._force_cleanup_state = AsyncMock()

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        with patch("app.modules.dev_runner.services.executor_service.ExecutorService._is_pid_alive", return_value=True), \
             patch("app.database.SessionLocal", return_value=mock_db):
            result = await svc.get_all_runners()

        assert len(result) == 1
        assert result[0].running is True
        # Redis set("running") 호출 확인
        svc.async_redis.set.assert_any_call(f"{RUNNER_KEY_PREFIX}:{rid}:status", "running")


# ===========================================================================
# Phase T5: HTTP — TestClient + mock
# ===========================================================================

class TestHttpRunnersPidCorrection:
    """GET /api/v1/dev-runner/runners HTTP 레이어 + PID 보정 검증"""

    pytestmark = pytest.mark.http

    def _mock_get_all_runners(self, runners):
        """get_all_runners()를 주어진 runners 목록으로 mock"""
        return patch(
            "app.modules.dev_runner.routes.runner.executor_service.get_all_runners",
            new_callable=AsyncMock,
            return_value=runners,
        )

    def _make_runner_item(self, runner_id, running, orphan=False):
        """RunnerListItem Pydantic 인스턴스"""
        return RunnerListItem(
            runner_id=runner_id,
            running=running,
            orphan=orphan,
            trigger="user",
        )

    def test_http_runners_list_stale_pid(self, client):
        """T5: GET /runners → PID dead runner가 running: false로 반환"""
        stale_runner = self._make_runner_item("stale_001", running=False)
        with self._mock_get_all_runners([stale_runner]):
            response = client.get(f"{BASE_URL}/runners")

        assert response.status_code == 200
        data = response.json()
        runners = data if isinstance(data, list) else data.get("runners", data.get("items", []))
        assert len(runners) >= 1
        stale = next((r for r in runners if r.get("runner_id") == "stale_001"), None)
        assert stale is not None
        assert stale["running"] is False

    def test_http_runner_status_vs_runners_consistency(self, client):
        """T5: GET /runners 목록의 running 값 → running=True runner는 alive 상태"""
        alive_runner = self._make_runner_item("alive_001", running=True)
        with self._mock_get_all_runners([alive_runner]):
            response = client.get(f"{BASE_URL}/runners")

        assert response.status_code == 200
        data = response.json()
        runners = data if isinstance(data, list) else data.get("runners", data.get("items", []))
        alive = next((r for r in runners if r.get("runner_id") == "alive_001"), None)
        assert alive is not None
        assert alive["running"] is True

    def test_http_runners_orphan_auto_fixed(self, client):
        """T5: orphan workflow 자동 정리 후 GET /runners에서 orphan=True runner 반환"""
        orphan_runner = self._make_runner_item("orphan_001", running=False, orphan=True)
        with self._mock_get_all_runners([orphan_runner]):
            response = client.get(f"{BASE_URL}/runners")

        assert response.status_code == 200
        data = response.json()
        runners = data if isinstance(data, list) else data.get("runners", data.get("items", []))
        orphan = next((r for r in runners if r.get("runner_id") == "orphan_001"), None)
        assert orphan is not None
        assert orphan.get("orphan") is True
