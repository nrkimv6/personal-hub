"""일괄실행(batch run) 기능 검증 TC

기존 TC가 커버하지 않는 미커버 영역을 검증한다:
  1. extra_plan_dirs / ignored_plans가 실제 값 포함 시 command 전달
  2. CLI 인자 --extra-plan-dirs, --ignored-plans, --session-id, --fused-session 조립
  3. HTTP API 레벨 parallel 요청 격리 (mock 기반)
"""

import importlib.util
import json
import pytest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
import fakeredis
import fakeredis.aioredis

from app.modules.dev_runner.services.executor_service import ExecutorService
from app.modules.dev_runner.schemas import RunRequest, RunStatusResponse
from tests.dev_runner._path_helpers import (
    get_listener_script_path,
    skip_if_missing,
)


# ========== 공통 헬퍼 ==========

async def _setup_listener_success(fake_async_redis):
    """listener 성공 응답 세팅"""
    await fake_async_redis.set("plan-runner:listener:heartbeat", "alive")
    await fake_async_redis.set("plan-runner:state:status", "idle")
    await fake_async_redis.set("plan-runner:state:pid", "12345")
    await fake_async_redis.set(
        "plan-runner:state:start_time", datetime.now().isoformat()
    )


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


def _get_launch_command(mock_popen):
    for call in mock_popen.call_args_list:
        cmd = call.args[0]
        if isinstance(cmd, list) and cmd and cmd[0] != "git":
            return cmd
    raise AssertionError(f"launch command not found in calls: {mock_popen.call_args_list}")


# ========== Fixtures (executor_service) ==========

@pytest.fixture
def fake_redis():
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def fake_async_redis():
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.fixture
def executor(fake_redis, fake_async_redis, monkeypatch):
    monkeypatch.setenv("PLAN_RUNNER_REDIS_DB", "15")
    service = ExecutorService()
    service.redis_client = fake_redis
    service.async_redis = fake_async_redis
    return service


# ========== Fixtures (listener process) ==========

_listener_mod = None
SCRIPT_PATH = get_listener_script_path()


def _get_listener():
    global _listener_mod
    if _listener_mod is not None:
        return _listener_mod
    skip_if_missing(SCRIPT_PATH, "Listener script")
    spec = importlib.util.spec_from_file_location(
        "dev_runner_command_listener_batch", str(SCRIPT_PATH)
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _listener_mod = mod
    return mod


@pytest.fixture(scope="module")
def listener_mod():
    return _get_listener()


@pytest.fixture
def fr():
    server = fakeredis.FakeServer()
    return fakeredis.FakeRedis(server=server, decode_responses=True)


@pytest.fixture
def mock_popen():
    p = MagicMock()
    p.pid = 12345
    p.poll.return_value = None
    p.wait.return_value = 0
    return p


RUNNER_ID = "batch-verify-01"


@pytest.fixture(autouse=True)
def reset_globals(listener_mod):
    listener_mod._running_processes.clear()
    listener_mod._running_log_files.clear()
    listener_mod._stream_threads.clear()
    yield
    listener_mod._running_processes.clear()
    listener_mod._running_log_files.clear()
    listener_mod._stream_threads.clear()


@pytest.fixture
def mock_worktree(listener_mod, tmp_path):
    worktree_path = tmp_path / "worktree"
    worktree_path.mkdir()
    with patch.object(
        listener_mod.WorktreeManager, "create",
        return_value=(worktree_path, "runner/batch-verify-01"),
    ):
        yield worktree_path


# ========== Phase 1: executor_service 미커버 TC ==========

class TestParallelCommandExtraFields:
    """extra_plan_dirs / ignored_plans가 command dict에 올바르게 포함되는지 검증"""

    async def test_parallel_command_includes_extra_plan_dirs(
        self, executor, fake_async_redis
    ):
        """Right: extra_plan_dirs 실제 값 → command에 쉼표 구분 문자열로 포함"""
        await _setup_listener_success(fake_async_redis)
        request = RunRequest(
            parallel=True, plan_file=None, test_source="batch_verify"
        )
        captured = []

        with patch(
            "app.modules.dev_runner.services.plan_service.plan_service"
        ) as mock_ps, patch.object(
            executor.async_redis,
            "lpush",
            side_effect=_make_capture_lpush(fake_async_redis, captured),
        ):
            mock_ps.get_extra_plan_dirs.return_value = [
                "D:\\work\\a\\docs\\plan",
                "D:\\work\\b\\docs\\plan",
            ]
            mock_ps.get_ignored_plan_paths.return_value = []
            await executor.start_dev_runner(request)

        assert len(captured) >= 1
        command = json.loads(captured[0])
        assert command.get("extra_plan_dirs") == (
            "D:\\work\\a\\docs\\plan,D:\\work\\b\\docs\\plan"
        )

    async def test_parallel_command_includes_ignored_plans(
        self, executor, fake_async_redis
    ):
        """Right: ignored_plans 실제 값 → command에 쉼표 구분 문자열로 포함"""
        await _setup_listener_success(fake_async_redis)
        request = RunRequest(
            parallel=True, plan_file=None, test_source="batch_verify"
        )
        captured = []

        with patch(
            "app.modules.dev_runner.services.plan_service.plan_service"
        ) as mock_ps, patch.object(
            executor.async_redis,
            "lpush",
            side_effect=_make_capture_lpush(fake_async_redis, captured),
        ):
            mock_ps.get_extra_plan_dirs.return_value = []
            mock_ps.get_ignored_plan_paths.return_value = [
                "D:\\work\\a\\docs\\plan\\skip.md"
            ]
            await executor.start_dev_runner(request)

        command = json.loads(captured[0])
        assert command.get("ignored_plans") == "D:\\work\\a\\docs\\plan\\skip.md"

    async def test_parallel_command_empty_extra_dirs_omitted(
        self, executor, fake_async_redis
    ):
        """Boundary: get_extra_plan_dirs() → [] 이면 command에 키 없음"""
        await _setup_listener_success(fake_async_redis)
        request = RunRequest(
            parallel=True, plan_file=None, test_source="batch_verify"
        )
        captured = []

        with patch(
            "app.modules.dev_runner.services.plan_service.plan_service"
        ) as mock_ps, patch.object(
            executor.async_redis,
            "lpush",
            side_effect=_make_capture_lpush(fake_async_redis, captured),
        ):
            mock_ps.get_extra_plan_dirs.return_value = []
            mock_ps.get_ignored_plan_paths.return_value = []
            await executor.start_dev_runner(request)

        command = json.loads(captured[0])
        assert "extra_plan_dirs" not in command
        assert "ignored_plans" not in command


# ========== Phase 2: CLI 인자 조립 미커버 TC ==========

class TestLaunchCliArgs:
    """_launch_plan_runner_process — extra_plan_dirs, ignored_plans, session_id, fused_session CLI 변환 검증"""

    def test_launch_cli_includes_extra_plan_dirs(
        self, listener_mod, fr, mock_popen, tmp_path, mock_worktree
    ):
        """Right: command의 extra_plan_dirs → --extra-plan-dirs CLI 인자로 변환"""
        command = {
            "action": "run",
            "runner_id": RUNNER_ID,
            "parallel": True,
            "extra_plan_dirs": "D:\\a,D:\\b",
        }

        with patch("_dr_plan_runner.LOG_DIR", tmp_path), \
             patch("_dr_plan_runner.threading.Thread") as mock_thread, \
             patch("_dr_plan_runner.subprocess.Popen", return_value=mock_popen) as mp:
            mock_thread.return_value = MagicMock()
            listener_mod._launch_plan_runner_process(
                command, fr, RUNNER_ID, mock_worktree, None, None
            )

        cmd = _get_launch_command(mp)
        assert "--extra-plan-dirs" in cmd
        idx = cmd.index("--extra-plan-dirs")
        assert cmd[idx + 1] == "D:\\a,D:\\b"

    def test_launch_cli_includes_ignored_plans(
        self, listener_mod, fr, mock_popen, tmp_path, mock_worktree
    ):
        """Right: command의 ignored_plans → --ignored-plans CLI 인자로 변환"""
        command = {
            "action": "run",
            "runner_id": RUNNER_ID,
            "parallel": True,
            "ignored_plans": "D:\\a\\skip.md",
        }

        with patch("_dr_plan_runner.LOG_DIR", tmp_path), \
             patch("_dr_plan_runner.threading.Thread") as mock_thread, \
             patch("_dr_plan_runner.subprocess.Popen", return_value=mock_popen) as mp:
            mock_thread.return_value = MagicMock()
            listener_mod._launch_plan_runner_process(
                command, fr, RUNNER_ID, mock_worktree, None, None
            )

        cmd = _get_launch_command(mp)
        assert "--ignored-plans" in cmd
        idx = cmd.index("--ignored-plans")
        assert cmd[idx + 1] == "D:\\a\\skip.md"

    def test_launch_cli_includes_session_id(
        self, listener_mod, fr, mock_popen, tmp_path, mock_worktree
    ):
        """Right: command의 session_id → --session-id CLI 인자로 변환"""
        command = {
            "action": "run",
            "runner_id": RUNNER_ID,
            "plan_file": "test.md",
            "session_id": "abc-def-123",
        }

        with patch("_dr_plan_runner.LOG_DIR", tmp_path), \
             patch("_dr_plan_runner.threading.Thread") as mock_thread, \
             patch("_dr_plan_runner.subprocess.Popen", return_value=mock_popen) as mp:
            mock_thread.return_value = MagicMock()
            listener_mod._launch_plan_runner_process(
                command, fr, RUNNER_ID, mock_worktree, "test.md", None
            )

        cmd = _get_launch_command(mp)
        assert "--session-id" in cmd
        idx = cmd.index("--session-id")
        assert cmd[idx + 1] == "abc-def-123"

    def test_launch_cli_no_skip_plan_R(
        self, listener_mod, fr, mock_popen, tmp_path, mock_worktree
    ):
        """R(Right): skip_plan=True 지정해도 cmd에 --skip-plan 없음 (CLI에서 제거된 옵션)"""
        command = {
            "action": "run",
            "runner_id": RUNNER_ID,
            "plan_file": "test.md",
            "skip_plan": True,
        }

        with patch("_dr_plan_runner.LOG_DIR", tmp_path), \
             patch("_dr_plan_runner.threading.Thread") as mock_thread, \
             patch("_dr_plan_runner.subprocess.Popen", return_value=mock_popen) as mp:
            mock_thread.return_value = MagicMock()
            listener_mod._launch_plan_runner_process(
                command, fr, RUNNER_ID, mock_worktree, "test.md", None
            )

        cmd = _get_launch_command(mp)
        assert "--skip-plan" not in cmd

    def test_launch_cli_includes_fused_session(
        self, listener_mod, fr, mock_popen, tmp_path, mock_worktree
    ):
        """Right: command의 fused_session=True → --fused-session CLI 플래그 포함"""
        command = {
            "action": "run",
            "runner_id": RUNNER_ID,
            "plan_file": "test.md",
            "session_id": "abc",
            "fused_session": True,
        }

        with patch("_dr_plan_runner.LOG_DIR", tmp_path), \
             patch("_dr_plan_runner.threading.Thread") as mock_thread, \
             patch("_dr_plan_runner.subprocess.Popen", return_value=mock_popen) as mp:
            mock_thread.return_value = MagicMock()
            listener_mod._launch_plan_runner_process(
                command, fr, RUNNER_ID, mock_worktree, "test.md", None
            )

        cmd = _get_launch_command(mp)
        assert "--fused-session" in cmd


# ========== Phase 3: HTTP API 격리 테스트 ==========

@pytest.mark.http
class TestHttpRunParallel:
    """FastAPI TestClient로 parallel=True 요청이 정상 처리되는지 검증"""

    @pytest.fixture(scope="class")
    def client(self):
        from fastapi.testclient import TestClient
        from app.main import app
        return TestClient(app)

    def test_http_run_parallel_returns_running(self, client):
        """Right: parallel=True POST → 200 응답 + running=True"""
        mock_response = RunStatusResponse(
            running=True,
            listener_alive=True,
            redis_connected=True,
            runner_id="t-batch-01",
        )
        with patch(
            "app.modules.dev_runner.routes.runner.executor_service.start_dev_runner",
            new=AsyncMock(return_value=mock_response),
        ):
            r = client.post(
                "/api/v1/dev-runner/run",
                json={"parallel": True, "dry_run": True, "trigger": "user:all"},
            )
        assert r.status_code == 200, f"HTTP {r.status_code}: {r.text}"
        data = r.json()
        assert data["running"] is True

    def test_http_run_parallel_response_has_runner_id(self, client):
        """Conformance: parallel 응답 JSON에 runner_id 필드가 비어 있지 않음"""
        mock_response = RunStatusResponse(
            running=True,
            listener_alive=True,
            redis_connected=True,
            runner_id="t-batch-01",
        )
        with patch(
            "app.modules.dev_runner.routes.runner.executor_service.start_dev_runner",
            new=AsyncMock(return_value=mock_response),
        ):
            r = client.post(
                "/api/v1/dev-runner/run",
                json={"parallel": True, "dry_run": True, "trigger": "user:all"},
            )
        data = r.json()
        assert "runner_id" in data
        assert data["runner_id"]  # 빈 문자열/None 아님
