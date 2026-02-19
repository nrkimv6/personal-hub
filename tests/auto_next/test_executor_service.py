"""ExecutorService TC - RIGHT-BICEP 원칙 적용 (Phase 3 보강)

대상 소스: app/modules/auto_next/services/executor_service.py
Mock 대상: redis.Redis → fakeredis, redis.asyncio → fakeredis.aioredis
"""

import json
import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock, AsyncMock
import fakeredis
import fakeredis.aioredis

from app.modules.auto_next.services.executor_service import ExecutorService
from app.modules.auto_next.schemas import RunRequest, RunStatusResponse
from fastapi import HTTPException


# ========== Fixtures ==========

@pytest.fixture
def fake_redis():
    """fakeredis 동기 인스턴스"""
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def fake_async_redis():
    """fakeredis 비동기 인스턴스"""
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.fixture
def executor(fake_redis, fake_async_redis):
    """fakeredis 주입된 ExecutorService 인스턴스"""
    service = ExecutorService()
    service.redis_client = fake_redis
    service.async_redis = fake_async_redis
    return service


@pytest.fixture
def run_request_single():
    return RunRequest(plan_file="common/docs/plan/test.md")


@pytest.fixture
def run_request_parallel():
    return RunRequest(parallel=True, plan_file=None)


async def _setup_listener_success(fake_async_redis, plan_file="common/docs/plan/test.md"):
    """listener 성공 응답 세팅"""
    result_data = {"success": True, "pid": 12345}
    await fake_async_redis.set("auto-next:listener:heartbeat", "alive")
    await fake_async_redis.set("auto-next:state:status", "idle")
    await fake_async_redis.set("auto-next:state:pid", "12345")
    await fake_async_redis.set("auto-next:state:plan_file", plan_file)
    await fake_async_redis.set("auto-next:state:start_time", datetime.now().isoformat())
    await fake_async_redis.rpush("auto-next:command_results", json.dumps(result_data))


# ========== TestStartAutoNext ==========

class TestStartAutoNext:

    async def test_start_single_plan_command(self, executor, run_request_single, fake_async_redis):
        """Right - plan_file 포함된 command 전송"""
        await _setup_listener_success(fake_async_redis)

        original_lpush = fake_async_redis.lpush
        captured = []

        async def capture_lpush(key, *values):
            captured.extend(values)
            return await original_lpush(key, *values)

        with patch.object(executor.async_redis, 'lpush', side_effect=capture_lpush):
            result = await executor.start_auto_next(run_request_single)

        assert len(captured) == 1
        command = json.loads(captured[0])
        assert command["plan_file"] == "common/docs/plan/test.md"
        assert command["action"] == "run"

    async def test_start_parallel_command(self, executor, run_request_parallel, fake_async_redis):
        """Right - parallel=True, plan_file 미포함"""
        await _setup_listener_success(fake_async_redis)

        captured = []
        original_lpush = fake_async_redis.lpush

        async def capture_lpush(key, *values):
            captured.extend(values)
            return await original_lpush(key, *values)

        with patch.object(executor.async_redis, 'lpush', side_effect=capture_lpush):
            await executor.start_auto_next(run_request_parallel)

        command = json.loads(captured[0])
        assert command.get("parallel") is True
        assert "plan_file" not in command

    async def test_start_all_options(self, executor, fake_async_redis):
        """Right - 모든 옵션 command에 반영"""
        request = RunRequest(
            plan_file="test.md", max_cycles=5, max_tokens=100000,
            until="18:00", dry_run=True, skip_plan=True,
            projects="activity-hub,wtools"
        )
        await _setup_listener_success(fake_async_redis, "test.md")

        captured = []
        original_lpush = fake_async_redis.lpush

        async def capture_lpush(key, *values):
            captured.extend(values)
            return await original_lpush(key, *values)

        with patch.object(executor.async_redis, 'lpush', side_effect=capture_lpush):
            await executor.start_auto_next(request)

        command = json.loads(captured[0])
        assert command["max_cycles"] == 5
        assert command["max_tokens"] == 100000
        assert command["until"] == "18:00"
        assert command["dry_run"] is True
        assert command["skip_plan"] is True
        assert command["projects"] == "activity-hub,wtools"

    async def test_start_already_running_409(self, executor, run_request_single, fake_async_redis):
        """Boundary - status=running + heartbeat 있음 → 409"""
        await fake_async_redis.set("auto-next:listener:heartbeat", "alive")
        await fake_async_redis.set("auto-next:state:status", "running")
        await fake_async_redis.set("auto-next:state:pid", "12345")

        with pytest.raises(HTTPException) as exc_info:
            await executor.start_auto_next(run_request_single)
        assert exc_info.value.status_code == 409

    async def test_start_redis_down_503(self, executor, run_request_single):
        """Boundary - Redis ping ConnectionError → 503"""
        import redis
        executor.async_redis = AsyncMock()
        executor.async_redis.ping.side_effect = redis.ConnectionError("Connection refused")

        with pytest.raises(HTTPException) as exc_info:
            await executor.start_auto_next(run_request_single)
        assert exc_info.value.status_code == 503

    async def test_start_brpop_timeout_504(self, executor, run_request_single, fake_async_redis):
        """Boundary - BRPOP 타임아웃 → 504"""
        await fake_async_redis.set("auto-next:listener:heartbeat", "alive")
        with patch.object(executor.async_redis, 'brpop', new_callable=AsyncMock, return_value=None):
            with pytest.raises(HTTPException) as exc_info:
                await executor.start_auto_next(run_request_single)
            assert exc_info.value.status_code == 504

    async def test_start_listener_failure_500(self, executor, run_request_single, fake_async_redis):
        """Error - listener success=False → 500"""
        await fake_async_redis.set("auto-next:listener:heartbeat", "alive")
        result_data = {"success": False, "message": "Failed to spawn process"}
        await fake_async_redis.rpush("auto-next:command_results", json.dumps(result_data))

        with pytest.raises(HTTPException) as exc_info:
            await executor.start_auto_next(run_request_single)
        assert exc_info.value.status_code == 500
        assert "Failed to spawn process" in exc_info.value.detail or "Failed to start" in exc_info.value.detail

    async def test_start_json_decode_error_500(self, executor, run_request_single, fake_async_redis):
        """Phase3 - JSON decode 실패 → 500"""
        await fake_async_redis.set("auto-next:listener:heartbeat", "alive")
        with patch.object(
            executor.async_redis, 'brpop',
            new_callable=AsyncMock,
            return_value=("auto-next:command_results", "not-valid-json{{{")
        ):
            with pytest.raises(HTTPException) as exc_info:
                await executor.start_auto_next(run_request_single)
            assert exc_info.value.status_code == 500
            assert "Invalid response" in exc_info.value.detail


# ========== TestStopAutoNext ==========

class TestStopAutoNext:

    async def test_stop_not_running_404(self, executor, fake_async_redis):
        """Boundary - 미실행 상태 stop → 404"""
        await fake_async_redis.set("auto-next:state:status", "stopped")

        with pytest.raises(HTTPException) as exc_info:
            await executor.stop_auto_next()
        assert exc_info.value.status_code == 404

    async def test_stop_success(self, executor, fake_async_redis):
        """Right - 정상 stop"""
        await fake_async_redis.set("auto-next:state:status", "running")
        result_data = {"success": True, "message": "Stopped"}
        await fake_async_redis.rpush("auto-next:command_results", json.dumps(result_data))

        result = await executor.stop_auto_next()
        assert result["message"] == "Stopped successfully"

    async def test_stop_listener_timeout_force_cleanup(self, executor, fake_async_redis):
        """Error - listener 무응답 → Redis 상태 강제 정리"""
        await fake_async_redis.set("auto-next:state:status", "running")
        await fake_async_redis.set("auto-next:state:pid", "12345")

        with patch.object(executor.async_redis, 'brpop', new_callable=AsyncMock, return_value=None):
            result = await executor.stop_auto_next()

        assert "Force cleaned" in result["message"]
        # cleanup은 sync redis_client에서 실행
        # force_cleanup_state가 호출되었는지 확인
        # force_cleanup이 호출되었음은 결과 메시지로 확인됨

    async def test_stop_redis_down_503(self, executor):
        """Phase3 - stop시 Redis ConnectionError → 503"""
        import redis
        executor.async_redis = AsyncMock()
        executor.async_redis.get.side_effect = redis.ConnectionError("Connection refused")

        with pytest.raises(HTTPException) as exc_info:
            await executor.stop_auto_next()
        assert exc_info.value.status_code == 503

    async def test_stop_json_decode_force_cleanup(self, executor, fake_async_redis, fake_redis):
        """Phase3 - stop시 JSON decode 실패 → force cleanup"""
        await fake_async_redis.set("auto-next:state:status", "running")
        fake_redis.set("auto-next:state:status", "running")
        fake_redis.set("auto-next:state:pid", "12345")

        with patch.object(
            executor.async_redis, 'brpop',
            new_callable=AsyncMock,
            return_value=("auto-next:command_results", "invalid-json!!!")
        ):
            result = await executor.stop_auto_next()

        assert "Force cleaned" in result["message"]
        # sync redis에서 상태 정리 확인
        assert fake_redis.get("auto-next:state:status") is None


# ========== TestGetProcessStatus ==========

class TestGetProcessStatus:

    def test_status_running_with_heartbeat(self, executor, fake_redis):
        """Right - running + heartbeat 있음 → running=True"""
        fake_redis.set("auto-next:listener:heartbeat", "alive")
        fake_redis.set("auto-next:state:status", "running")
        fake_redis.set("auto-next:state:pid", "12345")
        fake_redis.set("auto-next:state:plan_file", "test.md")
        fake_redis.set("auto-next:state:start_time", datetime.now().isoformat())

        result = executor.get_process_status()
        assert result.running is True
        assert result.pid == 12345
        assert result.plan_file == "test.md"

    def test_status_running_no_heartbeat_auto_cleanup(self, executor, fake_redis):
        """Cross-check - heartbeat 없음 → stale 자동 정리"""
        fake_redis.set("auto-next:state:status", "running")
        fake_redis.set("auto-next:state:pid", "99999")
        # heartbeat 없음 → stale

        result = executor.get_process_status()
        assert result.running is False
        assert fake_redis.get("auto-next:state:status") is None

    def test_status_not_running(self, executor, fake_redis):
        """Right - 미실행 → running=False"""
        result = executor.get_process_status()
        assert result.running is False

    def test_status_redis_down_returns_not_running(self, executor):
        """Error - Redis 다운 → running=False (에러 아님)"""
        import redis
        executor.redis_client = MagicMock()
        executor.redis_client.get.side_effect = redis.ConnectionError()

        result = executor.get_process_status()
        assert result.running is False


# ========== TestResetRunningState ==========

class TestResetRunningState:

    def _make_db(self, tmp_path, rows):
        """테스트용 SQLite DB 생성"""
        import sqlite3
        db_path = tmp_path / "auto_next.db"
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, status TEXT, started_at TEXT)")
        for row in rows:
            cursor.execute("INSERT INTO tasks VALUES (?, ?, ?)", row)
        conn.commit()
        conn.close()
        return db_path

    def test_reset_running_to_pending(self, executor, tmp_path):
        """Right - RUNNING → PENDING 복구"""
        db_path = self._make_db(tmp_path, [
            ("task1", "running", "2026-02-16 10:00:00"),
            ("task2", "pending", None),
        ])

        with patch('app.modules.auto_next.services.executor_service.config') as mc:
            mc.AUTO_NEXT_DB_PATH = str(db_path)
            result = executor.reset_running_state(full_reset=False)

        assert result["success"] is True
        assert result["reset_count"] == 1

        import sqlite3
        conn = sqlite3.connect(str(db_path))
        status = conn.execute("SELECT status FROM tasks WHERE id='task1'").fetchone()[0]
        conn.close()
        assert status == "pending"

    def test_full_reset_deletes_all(self, executor, tmp_path):
        """Right - full_reset=True → 전체 삭제"""
        db_path = self._make_db(tmp_path, [
            ("task1", "running", None),
            ("task2", "success", None),
        ])

        with patch('app.modules.auto_next.services.executor_service.config') as mc:
            mc.AUTO_NEXT_DB_PATH = str(db_path)
            result = executor.reset_running_state(full_reset=True)

        assert result["reset_count"] == 2
        assert result["full_reset"] is True

        import sqlite3
        conn = sqlite3.connect(str(db_path))
        count = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        conn.close()
        assert count == 0

    def test_reset_no_running_tasks(self, executor, tmp_path):
        """Boundary - RUNNING 0건"""
        db_path = self._make_db(tmp_path, [("task1", "success", None)])

        with patch('app.modules.auto_next.services.executor_service.config') as mc:
            mc.AUTO_NEXT_DB_PATH = str(db_path)
            result = executor.reset_running_state(full_reset=False)

        assert result["reset_count"] == 0

    def test_reset_db_not_found(self, executor, tmp_path):
        """Boundary - DB 파일 없음 → 정상 반환"""
        with patch('app.modules.auto_next.services.executor_service.config') as mc:
            mc.AUTO_NEXT_DB_PATH = str(tmp_path / "nonexistent.db")
            result = executor.reset_running_state()

        assert result["success"] is True
        assert result["reset_count"] == 0


# ========== Phase3: _is_pid_alive ==========

class TestIsPidAlive:

    def test_valid_pid_returns_true(self, executor):
        """Phase3 - 유효 PID → True (handle 반환 + exit_code=STILL_ACTIVE)"""
        import ctypes
        mock_kernel32 = MagicMock()
        mock_kernel32.OpenProcess.return_value = 1234  # nonzero handle
        mock_kernel32.CloseHandle.return_value = True
        # GetExitCodeProcess가 exit_code를 259(STILL_ACTIVE)로 채우도록 설정
        def set_exit_code_alive(handle, ptr):
            ctypes.cast(ptr, ctypes.POINTER(ctypes.c_ulong)).contents.value = 259
        mock_kernel32.GetExitCodeProcess.side_effect = set_exit_code_alive

        with patch('ctypes.windll') as mock_windll:
            mock_windll.kernel32 = mock_kernel32
            assert executor._is_pid_alive(1000) is True
            mock_kernel32.CloseHandle.assert_called_once_with(1234)

    def test_dead_pid_returns_false(self, executor):
        """Phase3 - 죽은 PID → False (handle=0)"""
        mock_kernel32 = MagicMock()
        mock_kernel32.OpenProcess.return_value = 0

        with patch('ctypes.windll') as mock_windll:
            mock_windll.kernel32 = mock_kernel32
            assert executor._is_pid_alive(99999) is False

    def test_negative_pid_returns_false(self, executor):
        """Phase3 - 음수 PID → False"""
        mock_kernel32 = MagicMock()
        mock_kernel32.OpenProcess.return_value = 0

        with patch('ctypes.windll') as mock_windll:
            mock_windll.kernel32 = mock_kernel32
            assert executor._is_pid_alive(-1) is False

    def test_exception_returns_false(self, executor):
        """Phase3 - 예외 발생 → False"""
        mock_kernel32 = MagicMock()
        mock_kernel32.OpenProcess.side_effect = OSError("Access denied")

        with patch('ctypes.windll') as mock_windll:
            mock_windll.kernel32 = mock_kernel32
            assert executor._is_pid_alive(1000) is False


# ========== CORRECT 원칙 ==========

class TestCORRECTConformance:

    def test_run_request_invalid_schema(self):
        """RunRequest 필드 타입 오류 → Pydantic 에러"""
        with pytest.raises(Exception):
            RunRequest(max_cycles="invalid")

    async def test_plan_file_none_vs_empty(self, executor, fake_async_redis):
        """plan_file=None vs '' → 둘 다 command에 미포함"""
        for plan_val in [None, ""]:
            await _setup_listener_success(fake_async_redis)
            captured = []
            original_lpush = fake_async_redis.lpush

            async def capture_lpush(key, *values):
                captured.extend(values)
                return await original_lpush(key, *values)

            with patch.object(executor.async_redis, 'lpush', side_effect=capture_lpush):
                await executor.start_auto_next(RunRequest(plan_file=plan_val))

            command = json.loads(captured[0])
            assert "plan_file" not in command, f"plan_file={plan_val!r} should not be in command"
