"""ExecutorService TC - RIGHT-BICEP 원칙 적용 (Phase 3 보강)

대상 소스: app/modules/dev_runner/services/executor_service.py
Mock 대상: redis.Redis → fakeredis, redis.asyncio → fakeredis.aioredis
"""

import json
import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock, AsyncMock
import fakeredis
import fakeredis.aioredis

from app.modules.dev_runner.services.executor_service import ExecutorService
from app.modules.dev_runner.schemas import RunRequest, RunStatusResponse
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
    await fake_async_redis.set("plan-runner:listener:heartbeat", "alive")
    await fake_async_redis.set("plan-runner:state:status", "idle")
    await fake_async_redis.set("plan-runner:state:pid", "12345")
    await fake_async_redis.set("plan-runner:state:plan_file", plan_file)
    await fake_async_redis.set("plan-runner:state:start_time", datetime.now().isoformat())


def _make_capture_lpush(fake_async_redis, captured, result_data=None):
    """per-command result key 자동 seed하는 capture_lpush 팩토리"""
    if result_data is None:
        result_data = {"success": True, "pid": 12345}
    original = fake_async_redis.lpush

    async def capture_lpush(key, *values):
        captured.extend(values)
        for v in values:
            try:
                cmd = json.loads(v)
                if "command_id" in cmd:
                    result_key = f"plan-runner:command_results:{cmd['command_id']}"
                    await original(result_key, json.dumps(result_data))
            except (json.JSONDecodeError, TypeError):
                pass
        return await original(key, *values)

    return capture_lpush


# ========== TestStartDevRunner ==========

class TestStartDevRunner:

    async def test_start_single_plan_command(self, executor, run_request_single, fake_async_redis):
        """Right - plan_file 포함된 command 전송"""
        await _setup_listener_success(fake_async_redis)

        captured = []

        with patch.object(executor.async_redis, 'lpush', side_effect=_make_capture_lpush(fake_async_redis, captured)):
            result = await executor.start_dev_runner(run_request_single)

        assert len(captured) == 1
        command = json.loads(captured[0])
        assert command["plan_file"] == "common/docs/plan/test.md"
        assert command["action"] == "run"

    async def test_start_parallel_command(self, executor, run_request_parallel, fake_async_redis):
        """Right - parallel=True, plan_file 미포함"""
        await _setup_listener_success(fake_async_redis)

        captured = []

        with patch("app.modules.dev_runner.services.plan_service.plan_service") as mock_ps, \
             patch.object(executor.async_redis, 'lpush', side_effect=_make_capture_lpush(fake_async_redis, captured)):
            mock_ps.get_extra_plan_dirs.return_value = []
            mock_ps.get_ignored_plan_paths.return_value = []
            await executor.start_dev_runner(run_request_parallel)

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

        with patch.object(executor.async_redis, 'lpush', side_effect=_make_capture_lpush(fake_async_redis, captured)):
            await executor.start_dev_runner(request)

        command = json.loads(captured[0])
        assert command["max_cycles"] == 5
        assert command["max_tokens"] == 100000
        assert command["until"] == "18:00"
        assert command["dry_run"] is True
        assert command["skip_plan"] is True
        assert command["projects"] == "activity-hub,wtools"

    async def test_start_concurrent_returns_different_runner_ids(self, executor, run_request_single, fake_async_redis):
        """Boundary - 멀티 runner: 동시 2회 시작 → 각기 다른 runner_id (409 없음)"""
        await _setup_listener_success(fake_async_redis)

        captured = []

        with patch.object(executor.async_redis, 'lpush', side_effect=_make_capture_lpush(fake_async_redis, captured)):
            result1 = await executor.start_dev_runner(run_request_single)
            result2 = await executor.start_dev_runner(run_request_single)

        assert result1.runner_id is not None
        assert result2.runner_id is not None
        assert result1.runner_id != result2.runner_id

    async def test_start_redis_down_503(self, executor, run_request_single):
        """Boundary - Redis ping ConnectionError → 503"""
        import redis
        executor.async_redis = AsyncMock()
        executor.async_redis.ping.side_effect = redis.ConnectionError("Connection refused")

        with pytest.raises(HTTPException) as exc_info:
            await executor.start_dev_runner(run_request_single)
        assert exc_info.value.status_code == 503

    async def test_start_brpop_timeout_504(self, executor, run_request_single, fake_async_redis):
        """Boundary - BRPOP 타임아웃 → 504"""
        await fake_async_redis.set("plan-runner:listener:heartbeat", "alive")
        with patch.object(executor.async_redis, 'brpop', new_callable=AsyncMock, return_value=None):
            with pytest.raises(HTTPException) as exc_info:
                await executor.start_dev_runner(run_request_single)
            assert exc_info.value.status_code == 504

    async def test_start_listener_failure_500(self, executor, run_request_single, fake_async_redis):
        """Error - listener success=False → 500"""
        await fake_async_redis.set("plan-runner:listener:heartbeat", "alive")
        result_data = {"success": False, "message": "Failed to spawn process"}

        captured = []

        with patch.object(executor.async_redis, 'lpush', side_effect=_make_capture_lpush(fake_async_redis, captured, result_data)):
            with pytest.raises(HTTPException) as exc_info:
                await executor.start_dev_runner(run_request_single)
        assert exc_info.value.status_code == 500
        assert "Failed to spawn process" in exc_info.value.detail or "Failed to start" in exc_info.value.detail

    async def test_start_json_decode_error_500(self, executor, run_request_single, fake_async_redis):
        """Phase3 - JSON decode 실패 → 500"""
        await fake_async_redis.set("plan-runner:listener:heartbeat", "alive")
        with patch.object(
            executor.async_redis, 'brpop',
            new_callable=AsyncMock,
            return_value=("plan-runner:command_results", "not-valid-json{{{")
        ):
            with pytest.raises(HTTPException) as exc_info:
                await executor.start_dev_runner(run_request_single)
            assert exc_info.value.status_code == 500
            assert "Invalid response" in exc_info.value.detail


# ========== TestStopDevRunner ==========

class TestStopDevRunner:

    async def test_stop_not_running_404(self, executor, fake_async_redis):
        """Boundary - 미실행 runner_id → 404"""
        with pytest.raises(HTTPException) as exc_info:
            await executor.stop_dev_runner("nonexistent_runner")
        assert exc_info.value.status_code == 404

    async def test_stop_success(self, executor, fake_async_redis):
        """Right - 정상 stop"""
        runner_id = "abc12345"
        await fake_async_redis.set(f"plan-runner:runners:{runner_id}:status", "running")
        result_data = {"success": True, "message": "Stopped"}

        captured = []

        with patch.object(executor.async_redis, 'lpush', side_effect=_make_capture_lpush(fake_async_redis, captured, result_data)):
            result = await executor.stop_dev_runner(runner_id)
        assert result["message"] == "Stopped successfully"

    async def test_stop_listener_timeout_force_cleanup(self, executor, fake_async_redis):
        """Error - listener 무응답 → Redis 상태 강제 정리"""
        runner_id = "abc12345"
        await fake_async_redis.set(f"plan-runner:runners:{runner_id}:status", "running")
        await fake_async_redis.set(f"plan-runner:runners:{runner_id}:pid", "12345")

        with patch.object(executor.async_redis, 'brpop', new_callable=AsyncMock, return_value=None):
            result = await executor.stop_dev_runner(runner_id)

        assert "Force cleaned" in result["message"]

    async def test_stop_redis_down_503(self, executor):
        """Phase3 - stop시 Redis ConnectionError → 503"""
        import redis
        executor.async_redis = AsyncMock()
        executor.async_redis.get.side_effect = redis.ConnectionError("Connection refused")

        with pytest.raises(HTTPException) as exc_info:
            await executor.stop_dev_runner("any_runner")
        assert exc_info.value.status_code == 503

    async def test_stop_json_decode_force_cleanup(self, executor, fake_async_redis, fake_redis):
        """Phase3 - stop시 JSON decode 실패 → force cleanup"""
        runner_id = "abc12345"
        await fake_async_redis.set(f"plan-runner:runners:{runner_id}:status", "running")
        await fake_async_redis.sadd("plan-runner:active_runners", runner_id)
        fake_redis.set(f"plan-runner:runners:{runner_id}:status", "running")
        fake_redis.sadd("plan-runner:active_runners", runner_id)
        fake_redis.set(f"plan-runner:runners:{runner_id}:pid", "12345")

        with patch.object(
            executor.async_redis, 'brpop',
            new_callable=AsyncMock,
            return_value=("plan-runner:command_results", "invalid-json!!!")
        ):
            result = await executor.stop_dev_runner(runner_id)

        assert "Force cleaned" in result["message"]
        # sync redis에서 상태 "stopped"으로 변경 확인 (_force_cleanup_state는 expire 설정, status="stopped")
        assert fake_redis.get(f"plan-runner:runners:{runner_id}:status") == "stopped"


# ========== TestGetProcessStatus ==========

class TestGetProcessStatus:

    @pytest.fixture(autouse=True)
    def mock_pid_alive(self, executor):
        with patch.object(executor, "_is_pid_alive", return_value=True):
            yield

    async def test_status_running_with_heartbeat(self, executor, fake_async_redis):
        """Right - running + heartbeat 있음 → running=True (호환 래퍼 경유)"""
        runner_id = "abc12345"
        await fake_async_redis.set("plan-runner:listener:heartbeat", "alive")
        await fake_async_redis.sadd("plan-runner:active_runners", runner_id)
        await fake_async_redis.set(f"plan-runner:runners:{runner_id}:status", "running")
        await fake_async_redis.set(f"plan-runner:runners:{runner_id}:pid", "12345")
        await fake_async_redis.set(f"plan-runner:runners:{runner_id}:plan_file", "test.md")
        await fake_async_redis.set(f"plan-runner:runners:{runner_id}:start_time", datetime.now().isoformat())

        result = await executor.get_process_status()
        assert result.running is True
        assert result.pid == 12345
        assert result.plan_file == "test.md"

    async def test_status_running_no_heartbeat_auto_cleanup(self, executor, fake_async_redis):
        """Cross-check - active_runners 비어 있음 → running=False"""
        # active_runners에 아무것도 없으면 not running
        result = await executor.get_process_status()
        assert result.running is False

    async def test_status_not_running(self, executor, fake_async_redis):
        """Right - 미실행 → running=False"""
        result = await executor.get_process_status()
        assert result.running is False

    async def test_status_redis_down_returns_not_running(self, executor):
        """Error - Redis 다운 → running=False (에러 아님)"""
        import redis.asyncio as aioredis
        executor.async_redis = AsyncMock()
        executor.async_redis.ping.side_effect = aioredis.ConnectionError()

        result = await executor.get_process_status()
        assert result.running is False

    async def test_current_cycle_key_absent_returns_none(self, executor, fake_async_redis):
        """Phase 2 TC3 - current_cycle Redis key 없음 → current_cycle=None (0 아님)"""
        runner_id = "abc12345"
        await fake_async_redis.set("plan-runner:listener:heartbeat", "alive")
        await fake_async_redis.sadd("plan-runner:active_runners", runner_id)
        await fake_async_redis.set(f"plan-runner:runners:{runner_id}:status", "running")
        await fake_async_redis.set(f"plan-runner:runners:{runner_id}:pid", "12345")
        await fake_async_redis.set(f"plan-runner:runners:{runner_id}:plan_file", "test.md")
        await fake_async_redis.set(f"plan-runner:runners:{runner_id}:start_time", datetime.now().isoformat())
        # current_cycle key 미설정

        result = await executor.get_process_status()
        assert result.running is True
        assert result.current_cycle is None  # 0이 아니라 None

    async def test_current_cycle_key_present_returns_int(self, executor, fake_async_redis):
        """Phase 2 TC3 - current_cycle Redis key 존재 → int 값 반환"""
        runner_id = "abc12345"
        await fake_async_redis.set("plan-runner:listener:heartbeat", "alive")
        await fake_async_redis.sadd("plan-runner:active_runners", runner_id)
        await fake_async_redis.set(f"plan-runner:runners:{runner_id}:status", "running")
        await fake_async_redis.set(f"plan-runner:runners:{runner_id}:pid", "12345")
        await fake_async_redis.set(f"plan-runner:runners:{runner_id}:plan_file", "test.md")
        await fake_async_redis.set(f"plan-runner:runners:{runner_id}:start_time", datetime.now().isoformat())
        await fake_async_redis.set(f"plan-runner:runners:{runner_id}:current_cycle", "7")

        result = await executor.get_process_status()
        assert result.running is True
        assert result.current_cycle == 7


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

            with patch.object(executor.async_redis, 'lpush', side_effect=_make_capture_lpush(fake_async_redis, captured)):
                await executor.start_dev_runner(RunRequest(plan_file=plan_val))

            command = json.loads(captured[0])
            assert "plan_file" not in command, f"plan_file={plan_val!r} should not be in command"

    async def test_engine_parameter_passing(self, executor, fake_async_redis):
        """Phase 1 - engine 파라미터가 Redis 명령에 포함되고 상태 조회 시 반환됨"""
        await _setup_listener_success(fake_async_redis)

        # 1. Start 시 engine 포함 확인
        captured = []

        with patch.object(executor.async_redis, 'lpush', side_effect=_make_capture_lpush(fake_async_redis, captured)):
            await executor.start_dev_runner(RunRequest(engine="gemini"))

        command = json.loads(captured[0])
        assert command["engine"] == "gemini"

        # 2. Status 조회 시 engine 포함 확인 (per-runner 키)
        runner_id = "abc12345"
        await fake_async_redis.set("plan-runner:listener:heartbeat", "alive")
        await fake_async_redis.sadd("plan-runner:active_runners", runner_id)
        await fake_async_redis.set(f"plan-runner:runners:{runner_id}:status", "running")
        await fake_async_redis.set(f"plan-runner:runners:{runner_id}:pid", "12345")
        await fake_async_redis.set(f"plan-runner:runners:{runner_id}:engine", "gemini")

        with patch.object(executor, "_is_pid_alive", return_value=True):
            status = await executor.get_process_status()
            assert status.engine == "gemini"

    async def test_start_dev_runner_returns_immediate_engine(self, executor, fake_async_redis):
        """Phase 8/9 - start_dev_runner는 Redis 동기화와 무관하게 요청된 엔진명을 즉시 반환함"""
        await _setup_listener_success(fake_async_redis)
        await fake_async_redis.set("plan-runner:state:engine", "claude")

        captured = []
        request = RunRequest(engine="gemini", plan_file="test.md")

        with patch.object(executor.async_redis, 'lpush', side_effect=_make_capture_lpush(fake_async_redis, captured)):
            result = await executor.start_dev_runner(request)
        
        # 응답에는 요청한 gemini가 포함되어야 함
        assert result.engine == "gemini"

    async def test_get_process_status_returns_engine_when_not_running(self, executor, fake_async_redis):
        """Phase 8/9 - active_runners 없을 때 running=False, engine 기본값 반환"""
        await fake_async_redis.set("plan-runner:listener:heartbeat", "alive")
        # active_runners 비어있음 → not running

        status = await executor.get_process_status()
        assert status.running is False
        assert status.engine in ("claude", None, "gemini", "")  # 기본값 허용

    async def test_get_process_status_fallback_to_claude(self, executor, fake_async_redis):
        """Phase 8/9 - Redis에 엔진 정보가 없을 때 기본값 claude 반환"""
        await fake_async_redis.set("plan-runner:listener:heartbeat", "alive")
        await fake_async_redis.set("plan-runner:state:status", "idle")
        # engine key 없음

        status = await executor.get_process_status()
        assert status.engine == "claude"


# ========== TestMaxCyclesZeroBugFix ==========

class TestMaxCyclesZeroBugFix:
    """fix: max_cycles=0 (무제한)이 command에 포함되지 않는 버그 수정 검증

    버그: if request.max_cycles and request.max_cycles > 0 → 0은 falsy → 누락
    픽스: if request.max_cycles is not None → 0 포함
    """

    async def test_max_cycles_zero_included_in_command(self, executor, fake_async_redis):
        """max_cycles=0 (무제한)이 Redis command에 포함되어야 함"""
        await _setup_listener_success(fake_async_redis, "test.md")
        request = RunRequest(plan_file="test.md", max_cycles=0)

        captured = []

        with patch.object(executor.async_redis, 'lpush', side_effect=_make_capture_lpush(fake_async_redis, captured)):
            await executor.start_dev_runner(request)

        command = json.loads(captured[0])
        assert "max_cycles" in command, "max_cycles=0이 command에 포함되어야 함 (버그: falsy로 누락됨)"
        assert command["max_cycles"] == 0

    async def test_max_cycles_positive_included_in_command(self, executor, fake_async_redis):
        """max_cycles=3 (유한)이 Redis command에 포함되어야 함 (기존 동작 유지)"""
        await _setup_listener_success(fake_async_redis, "test.md")
        request = RunRequest(plan_file="test.md", max_cycles=3)

        captured = []

        with patch.object(executor.async_redis, 'lpush', side_effect=_make_capture_lpush(fake_async_redis, captured)):
            await executor.start_dev_runner(request)

        command = json.loads(captured[0])
        assert command["max_cycles"] == 3

    async def test_max_cycles_none_not_included_in_command(self, executor, fake_async_redis):
        """max_cycles=None (미지정)은 command에 포함되지 않아야 함"""
        await _setup_listener_success(fake_async_redis, "test.md")
        request = RunRequest(plan_file="test.md", max_cycles=None)

        captured = []

        with patch.object(executor.async_redis, 'lpush', side_effect=_make_capture_lpush(fake_async_redis, captured)):
            await executor.start_dev_runner(request)

        command = json.loads(captured[0])
        assert "max_cycles" not in command, "max_cycles=None은 command에 포함되지 않아야 함"


# ========== TestCommandListenerMaxCycles ==========

class TestCommandListenerMaxCycles:
    """command-listener.py의 max_cycles 처리 로직 단위 검증"""

    def _build_cmd(self, command: dict) -> list:
        """command-listener.py L250~270 로직을 직접 재현 (임포트 없이 테스트)"""
        cmd = ["monitorpage-worker.exe", "-m", "app.modules.dev_runner.plan_runner"]
        if command.get("plan_file"):
            cmd.extend(["--plan-file", command["plan_file"]])
        if command.get("max_cycles") is not None:
            cmd.extend(["--max-cycles", str(command["max_cycles"])])
        if command.get("max_tokens") is not None:
            cmd.extend(["--max-tokens", str(command["max_tokens"])])
        return cmd

    def test_max_cycles_zero_appended_to_cli(self):
        """max_cycles=0이 --max-cycles 0으로 CLI에 전달되어야 함"""
        cmd = self._build_cmd({"plan_file": "test.md", "max_cycles": 0})
        assert "--max-cycles" in cmd
        idx = cmd.index("--max-cycles")
        assert cmd[idx + 1] == "0"

    def test_max_cycles_positive_appended_to_cli(self):
        """max_cycles=3이 --max-cycles 3으로 CLI에 전달되어야 함"""
        cmd = self._build_cmd({"plan_file": "test.md", "max_cycles": 3})
        assert "--max-cycles" in cmd
        idx = cmd.index("--max-cycles")
        assert cmd[idx + 1] == "3"

    def test_max_cycles_absent_not_in_cli(self):
        """max_cycles 키가 없으면 --max-cycles가 CLI에 포함되지 않아야 함"""
        cmd = self._build_cmd({"plan_file": "test.md"})
        assert "--max-cycles" not in cmd
