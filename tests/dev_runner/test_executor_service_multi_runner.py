"""멀티 runner 지원: ExecutorService 테스트 (Right-BICEP)

Phase 3 구현 검증: runner_id 생성, 409 제거, get_all_runners, stop_dev_runner
"""
import json
import uuid
import asyncio
from datetime import datetime
from unittest.mock import MagicMock, patch, AsyncMock

import pytest
import redis as redis_module

from app.modules.dev_runner.services.executor_service import ExecutorService, RUNNER_KEY_PREFIX, ACTIVE_RUNNERS_KEY
from app.modules.dev_runner.schemas import RunRequest, RunStatusResponse, RunnerListItem


@pytest.fixture(autouse=True)
def dev_runner_config_isolation(tmp_path):
    """devrunner conftest autouse 오버라이드 — plan_service 의존성 없음"""
    yield


def _make_sync_redis_mock(**key_values):
    """동기 Redis mock 헬퍼"""
    r = MagicMock()
    r.ping = MagicMock()
    r.set = MagicMock()
    r.delete = MagicMock()
    r.sadd = MagicMock()
    r.srem = MagicMock()
    r.smembers = MagicMock(return_value=set())
    r.get = MagicMock(side_effect=lambda k: key_values.get(k))
    return r


def _make_async_redis_mock(**key_values):
    """비동기 Redis mock 헬퍼"""
    r = AsyncMock()
    r.ping = AsyncMock()
    r.get = AsyncMock(side_effect=lambda k: key_values.get(k))
    r.lpush = AsyncMock()
    r.scard = AsyncMock(return_value=0)
    r.brpop = AsyncMock(return_value=(b"key", json.dumps({"success": True, "message": "ok"}).encode()))
    return r


@pytest.fixture
def executor():
    """테스트용 ExecutorService (Redis 클라이언트 mock)"""
    svc = ExecutorService.__new__(ExecutorService)
    svc.redis_client = _make_sync_redis_mock()
    svc.async_redis = _make_async_redis_mock()
    return svc


class TestStartDevRunnerRight:
    """TC-Right: start_dev_runner() 기본 동작"""

    @pytest.mark.asyncio
    async def test_runner_id_is_8char_hex(self, executor):
        """start 반환값의 runner_id가 8자리 hex 문자열"""
        executor.async_redis.get = AsyncMock(return_value="active")
        executor.async_redis.brpop = AsyncMock(
            return_value=(b"key", json.dumps({"success": True}).encode())
        )
        # per-runner 키 응답 설정
        runner_id_holder = {}

        async def mock_get(key):
            # runner_id를 알 수 없으므로 패턴 기반 반환
            if ":pid" in key:
                return "1234"
            if ":plan_file" in key:
                return "test.md"
            if ":start_time" in key:
                return datetime.now().isoformat()
            return None

        executor.async_redis.get = mock_get

        with patch.object(executor, "_check_redis_and_listener", new_callable=AsyncMock):
            request = RunRequest(plan_file="test.md", engine="claude")
            result = await executor.start_dev_runner(request)

        assert result.runner_id is not None
        assert len(result.runner_id) == 8
        assert all(c in "0123456789abcdef" for c in result.runner_id)

    @pytest.mark.asyncio
    async def test_two_concurrent_starts_get_different_runner_ids(self, executor):
        """동시 2회 start → 각기 다른 runner_id, 409 없음"""
        seen_ids = []

        async def mock_get(key):
            if ":pid" in key:
                return "1234"
            if ":plan_file" in key:
                return "test.md"
            if ":start_time" in key:
                return datetime.now().isoformat()
            return None

        executor.async_redis.get = mock_get
        executor.async_redis.brpop = AsyncMock(
            return_value=(b"key", json.dumps({"success": True}).encode())
        )

        with patch.object(executor, "_check_redis_and_listener", new_callable=AsyncMock):
            request = RunRequest(plan_file="test.md", engine="claude")
            result1 = await executor.start_dev_runner(request)
            result2 = await executor.start_dev_runner(request)

        assert result1.runner_id != result2.runner_id


class TestGetAllRunners:
    """TC-Boundary: get_all_runners()"""

    def test_empty_active_runners_returns_empty_list(self, executor):
        """active_runners Set 비어있을 때 빈 [] 반환"""
        executor.redis_client.smembers = MagicMock(return_value=set())
        result = executor.get_all_runners()
        assert result == []

    def test_returns_runner_list_items(self, executor):
        """active runner 있을 때 RunnerListItem 목록 반환"""
        executor.redis_client.smembers = MagicMock(return_value={"abc12345"})

        def get_side_effect(key):
            mapping = {
                f"{RUNNER_KEY_PREFIX}:abc12345:status": "running",
                f"{RUNNER_KEY_PREFIX}:abc12345:pid": "1234",
                f"{RUNNER_KEY_PREFIX}:abc12345:plan_file": "test.md",
                f"{RUNNER_KEY_PREFIX}:abc12345:engine": "claude",
                f"{RUNNER_KEY_PREFIX}:abc12345:start_time": datetime.now().isoformat(),
            }
            return mapping.get(key)

        executor.redis_client.get = MagicMock(side_effect=get_side_effect)

        result = executor.get_all_runners()
        assert len(result) == 1
        assert result[0].runner_id == "abc12345"
        assert result[0].running is True
        assert result[0].plan_file == "test.md"


class TestStopDevRunner:
    """TC-Inverse: stop_dev_runner()"""

    @pytest.mark.asyncio
    async def test_stop_nonexistent_runner_raises_404(self, executor):
        """존재하지 않는 runner_id로 stop → HTTPException(status_code=404)"""
        from fastapi import HTTPException

        executor.async_redis.ping = AsyncMock()
        executor.async_redis.get = AsyncMock(return_value=None)  # not running

        with pytest.raises(HTTPException) as exc_info:
            await executor.stop_dev_runner("notexist")

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_stop_running_runner_calls_command(self, executor):
        """실행 중인 runner stop → Redis LPUSH 호출"""
        executor.async_redis.ping = AsyncMock()
        executor.async_redis.get = AsyncMock(return_value="running")
        executor.async_redis.brpop = AsyncMock(
            return_value=(b"key", json.dumps({"success": True}).encode())
        )

        result = await executor.stop_dev_runner("abc12345")
        executor.async_redis.lpush.assert_called_once()
        assert "Stopped" in result.get("message", "")


class TestGetRunnerStatus:
    """TC-Cross: get_runner_status() 결과가 Redis 값과 일치"""

    def test_status_matches_redis_values(self, executor):
        """get_runner_status 결과가 RUNNER_KEY_PREFIX:{runner_id}:* 키 값과 일치"""
        start_time = datetime.now().isoformat()

        def get_side_effect(key):
            mapping = {
                f"{RUNNER_KEY_PREFIX}:abc12345:status": "running",
                f"{RUNNER_KEY_PREFIX}:abc12345:pid": "5678",
                f"{RUNNER_KEY_PREFIX}:abc12345:plan_file": "my_plan.md",
                f"{RUNNER_KEY_PREFIX}:abc12345:engine": "gemini",
                f"{RUNNER_KEY_PREFIX}:abc12345:start_time": start_time,
            }
            return mapping.get(key)

        executor.redis_client.get = MagicMock(side_effect=get_side_effect)

        # psutil.pid_exists는 테스트 환경에서 PID 5678이 없어 stale 처리될 수 있으므로 mock
        with patch("psutil.pid_exists", return_value=True):
            result = executor.get_runner_status("abc12345")

        assert result.runner_id == "abc12345"
        assert result.running is True
        assert result.pid == 5678
        assert result.plan_file == "my_plan.md"
        assert result.engine == "gemini"

    def test_redis_connection_error_returns_not_running(self):
        """Redis 연결 실패 시 running=False 반환 (예외 전파 없음)"""
        svc = ExecutorService.__new__(ExecutorService)
        svc.redis_client = MagicMock()
        svc.redis_client.ping = MagicMock(side_effect=redis_module.ConnectionError("connection refused"))
        svc.async_redis = MagicMock()

        result = svc.get_process_status()
        assert result.running is False
        assert result.redis_connected is False


class TestForceCleanupState:
    """TC-Error: _force_cleanup_state()"""

    def test_cleanup_specific_runner(self, executor):
        """특정 runner_id cleanup → SREM + 해당 키 삭제"""
        executor._force_cleanup_state("abc12345")

        executor.redis_client.srem.assert_called_once_with(ACTIVE_RUNNERS_KEY, "abc12345")
        # delete 호출에 per-runner 키 포함
        call_args = executor.redis_client.delete.call_args[0]
        assert any("abc12345" in k for k in call_args)

    def test_cleanup_all_runners(self, executor):
        """runner_id 없이 cleanup → active_runners 전체 정리"""
        executor.redis_client.smembers = MagicMock(return_value={"r1", "r2"})
        executor._force_cleanup_state("")  # 빈 문자열 = 전체 정리

        # smembers 호출 확인
        executor.redis_client.smembers.assert_called_once_with(ACTIVE_RUNNERS_KEY)
