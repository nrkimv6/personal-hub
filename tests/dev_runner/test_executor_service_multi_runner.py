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
    r.expire = MagicMock()
    r.exists = MagicMock(return_value=True)
    r.zadd = MagicMock()
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

    @pytest.mark.asyncio
    async def test_start_dev_runner_brpop_timeout_cleans_up_runner(self, executor):
        """RIGHT-E: brpop timeout(None) → _force_cleanup_state 호출 후 504 raise"""
        from fastapi import HTTPException

        executor.async_redis.get = AsyncMock(return_value="active")
        executor.async_redis.brpop = AsyncMock(return_value=None)

        with patch.object(executor, "_check_redis_and_listener", new_callable=AsyncMock):
            with patch.object(executor, "_force_cleanup_state") as mock_cleanup:
                request = RunRequest(plan_file="test.md", engine="claude")
                with pytest.raises(HTTPException) as exc_info:
                    await executor.start_dev_runner(request)

        assert exc_info.value.status_code == 504
        mock_cleanup.assert_called_once()
        called_runner_id = mock_cleanup.call_args[0][0]
        assert len(called_runner_id) == 8


class TestGetAllRunners:
    """TC-Boundary: get_all_runners()"""

    @pytest.mark.asyncio
    async def test_empty_active_runners_returns_empty_list(self, executor):
        """active_runners Set 비어있을 때 빈 [] 반환"""
        executor.async_redis.smembers = AsyncMock(return_value=set())
        executor.async_redis.zremrangebyscore = AsyncMock()
        executor.async_redis.zrange = AsyncMock(return_value=set())
        result = await executor.get_all_runners()
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_runner_list_items(self, executor):
        """active runner 있을 때 RunnerListItem 목록 반환"""
        executor.async_redis.smembers = AsyncMock(return_value={"abc12345"})
        executor.async_redis.zremrangebyscore = AsyncMock()
        executor.async_redis.zrange = AsyncMock(return_value=set())

        async def get_side_effect(key):
            mapping = {
                f"{RUNNER_KEY_PREFIX}:abc12345:status": "running",
                f"{RUNNER_KEY_PREFIX}:abc12345:pid": "1234",
                f"{RUNNER_KEY_PREFIX}:abc12345:plan_file": "test.md",
                f"{RUNNER_KEY_PREFIX}:abc12345:engine": "claude",
                f"{RUNNER_KEY_PREFIX}:abc12345:start_time": datetime.now().isoformat(),
            }
            return mapping.get(key)

        executor.async_redis.get = get_side_effect

        result = await executor.get_all_runners()
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

    @pytest.mark.asyncio
    async def test_status_matches_redis_values(self, executor):
        """get_runner_status 결과가 RUNNER_KEY_PREFIX:{runner_id}:* 키 값과 일치"""
        start_time = datetime.now().isoformat()

        async def get_side_effect(key):
            mapping = {
                f"{RUNNER_KEY_PREFIX}:abc12345:status": "running",
                f"{RUNNER_KEY_PREFIX}:abc12345:pid": "5678",
                f"{RUNNER_KEY_PREFIX}:abc12345:plan_file": "my_plan.md",
                f"{RUNNER_KEY_PREFIX}:abc12345:engine": "gemini",
                f"{RUNNER_KEY_PREFIX}:abc12345:start_time": start_time,
                f"{RUNNER_KEY_PREFIX}:abc12345:current_cycle": None,
            }
            return mapping.get(key)

        executor.async_redis.get = get_side_effect

        # _is_pid_alive는 ctypes.windll를 사용하므로 patch
        with patch.object(executor, "_is_pid_alive", return_value=True):
            result = await executor.get_runner_status("abc12345")

        assert result.runner_id == "abc12345"
        assert result.running is True
        assert result.pid == 5678
        assert result.plan_file == "my_plan.md"
        assert result.engine == "gemini"

    @pytest.mark.asyncio
    async def test_redis_connection_error_returns_not_running(self):
        """Redis 연결 실패 시 running=False 반환 (예외 전파 없음)"""
        import redis.asyncio as aioredis
        svc = ExecutorService.__new__(ExecutorService)
        svc.redis_client = MagicMock()
        svc.async_redis = AsyncMock()
        svc.async_redis.ping = AsyncMock(side_effect=aioredis.ConnectionError("connection refused"))

        result = await svc.get_process_status()
        assert result.running is False
        assert result.redis_connected is False


class TestForceCleanupState:
    """TC-Error: _force_cleanup_state()"""

    def test_cleanup_specific_runner(self, executor):
        """특정 runner_id cleanup → status=stopped + expire + srem + zadd (delete 없음)"""
        executor._force_cleanup_state("abc12345")

        # status "stopped" 설정 확인
        executor.redis_client.set.assert_any_call(
            f"{RUNNER_KEY_PREFIX}:abc12345:status", "stopped"
        )
        # ACTIVE_RUNNERS_KEY에서 제거 확인
        executor.redis_client.srem.assert_called_once_with(ACTIVE_RUNNERS_KEY, "abc12345")
        # per-runner 키에 TTL expire 설정 확인
        assert executor.redis_client.expire.call_count >= 1
        # RECENT_RUNNERS_KEY에 추가 확인
        executor.redis_client.zadd.assert_called_once()
        # delete는 호출되지 않음 (expire 방식)
        executor.redis_client.delete.assert_not_called()

    def test_cleanup_all_runners(self, executor):
        """runner_id 없이 cleanup → 각 runner expire + zadd + ACTIVE_RUNNERS_KEY 삭제"""
        executor.redis_client.smembers = MagicMock(return_value={"r1", "r2"})
        executor._force_cleanup_state("")  # 빈 문자열 = 전체 정리

        # smembers 호출 확인
        executor.redis_client.smembers.assert_called_once_with(ACTIVE_RUNNERS_KEY)
        # 각 runner에 status "stopped" 설정 확인
        set_calls = [str(c) for c in executor.redis_client.set.call_args_list]
        assert any("r1" in c and "stopped" in c for c in set_calls)
        assert any("r2" in c and "stopped" in c for c in set_calls)
        # per-runner 키에 expire 호출 확인 (runner 2개이므로 ≥ 2)
        assert executor.redis_client.expire.call_count >= 2
        # 각 runner에 zadd 호출 확인
        assert executor.redis_client.zadd.call_count == 2
        # ACTIVE_RUNNERS_KEY 삭제 확인
        executor.redis_client.delete.assert_called_once_with(ACTIVE_RUNNERS_KEY)

    def test_cleanup_specific_runner_sets_stopped_and_expires(self, executor):
        """RIGHT-R: _force_cleanup_state(runner_id) → set(stopped) + expire ≥ 1 + zadd"""
        executor._force_cleanup_state("abc12345")

        executor.redis_client.set.assert_any_call(
            f"{RUNNER_KEY_PREFIX}:abc12345:status", "stopped"
        )
        assert executor.redis_client.expire.call_count >= 1
        executor.redis_client.zadd.assert_called_once()

    def test_cleanup_specific_runner_no_delete_called(self, executor):
        """RIGHT-I: _force_cleanup_state(runner_id) → delete 미호출 (expire 방식)"""
        executor._force_cleanup_state("abc12345")

        executor.redis_client.delete.assert_not_called()

    def test_cleanup_all_runners_deletes_active_set(self, executor):
        """RIGHT-R: _force_cleanup_state("") → delete(ACTIVE_RUNNERS_KEY) 1회"""
        executor.redis_client.smembers = MagicMock(return_value={"r1", "r2"})
        executor._force_cleanup_state("")

        executor.redis_client.delete.assert_called_once_with(ACTIVE_RUNNERS_KEY)
