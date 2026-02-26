"""멀티 runner 지원: command listener 테스트 (Right-BICEP)

Phase 2 구현 검증: runner_id 기반 프로세스 관리, per-runner Redis 키, Pub/Sub 채널 분리
"""
import sys
import importlib
import importlib.util
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# dev-runner-command-listener.py 경로 (하이픈 포함이므로 importlib.util 사용)
_SCRIPT_PATH = Path(__file__).parent.parent.parent / "scripts" / "dev-runner-command-listener.py"

# noise_filter mock (의존성 격리)
_mock_noise_module = types.ModuleType("listener_noise_filter")
_mock_noise_module.NOISE_BLOCK_MARKERS = []
_mock_noise_module.is_noise_line = lambda line: False


def _load_listener():
    """dev-runner-command-listener.py를 임시 모듈로 로드"""
    sys.modules["listener_noise_filter"] = _mock_noise_module
    spec = importlib.util.spec_from_file_location("_listener", _SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    # 글로벌 dict 초기화
    mod._running_processes = {}
    mod._running_log_files = {}
    mod._stream_threads = {}
    spec.loader.exec_module(mod)
    return mod


def _make_redis_mock():
    r = MagicMock()
    r.set = MagicMock()
    r.delete = MagicMock()
    r.sadd = MagicMock()
    r.srem = MagicMock()
    r.publish = MagicMock()
    r.get = MagicMock(return_value=None)
    return r


@pytest.fixture(autouse=True)
def dev_runner_config_isolation(tmp_path):
    """devrunner conftest autouse 오버라이드 — plan_service 의존성 없음"""
    yield


class TestMultiRunnerGlobalDicts:
    """Task 3: 전역 Dict 변수 전환 검증"""

    def test_global_dicts_exist(self):
        """_running_processes, _running_log_files, _stream_threads 가 dict"""
        listener = _load_listener()
        assert isinstance(listener._running_processes, dict)
        assert isinstance(listener._running_log_files, dict)
        assert isinstance(listener._stream_threads, dict)


class TestCleanupProcessState:
    """Task 4: _cleanup_process_state(runner_id, redis_client)"""

    def test_cleanup_removes_runner_from_dicts(self):
        """cleanup 후 _running_processes에서 runner_id 제거"""
        listener = _load_listener()

        mock_proc = MagicMock()
        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = False
        listener._running_processes["abc12345"] = mock_proc
        listener._running_log_files["abc12345"] = Path("/tmp/test.log")
        listener._stream_threads["abc12345"] = mock_thread

        r = _make_redis_mock()
        listener._cleanup_process_state("abc12345", r)

        assert "abc12345" not in listener._running_processes
        assert "abc12345" not in listener._running_log_files
        assert "abc12345" not in listener._stream_threads

    def test_cleanup_calls_redis_srem(self):
        """cleanup 시 ACTIVE_RUNNERS_KEY에서 runner_id SREM 호출"""
        listener = _load_listener()
        r = _make_redis_mock()
        listener._cleanup_process_state("abc12345", r)
        r.srem.assert_called_once_with(listener.ACTIVE_RUNNERS_KEY, "abc12345")

    def test_cleanup_deletes_per_runner_redis_keys(self):
        """cleanup 시 per-runner Redis 키 삭제"""
        listener = _load_listener()
        r = _make_redis_mock()
        listener._cleanup_process_state("abc12345", r)

        deleted_keys = r.delete.call_args[0]
        assert any("abc12345:status" in k for k in deleted_keys)
        assert any("abc12345:pid" in k for k in deleted_keys)


class TestStreamOutput:
    """Task 5: _stream_output() per-runner 로그 채널"""

    def test_stream_output_publishes_to_per_runner_channel(self):
        """_stream_output이 plan-runner:logs:{runner_id} 채널에 publish"""
        listener = _load_listener()

        mock_process = MagicMock()
        mock_process.stdout = iter(["hello world\n"])
        mock_process.returncode = 0
        mock_process.wait = MagicMock()

        mock_log_handle = MagicMock()
        r = _make_redis_mock()

        with patch.object(listener, "_cleanup_process_state"):
            listener._stream_output(mock_process, mock_log_handle, r, "abc12345")

        call_args_list = r.publish.call_args_list
        assert len(call_args_list) > 0
        channel = call_args_list[-1][0][0]
        assert channel == f"{listener.LOG_CHANNEL_PREFIX}:abc12345"


class TestStartPlanRunner:
    """Task 6: start_plan_runner() Right-BICEP"""

    @patch("subprocess.Popen")
    def test_right_runner_id_stored_in_processes(self, mock_popen):
        """TC-Right: runner_id 포함 command → _running_processes[runner_id] 저장, SADD 호출"""
        listener = _load_listener()

        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        r = _make_redis_mock()
        command = {
            "action": "run",
            "runner_id": "abc12345",
            "plan_file": "test.md",
            "engine": "claude",
        }

        fake_worktree = Path("/tmp/worktrees/abc12345")
        with patch.object(Path, "mkdir"), \
             patch("builtins.open", MagicMock()), \
             patch("os.environ.copy", return_value={}), \
             patch.object(listener.WorktreeManager, "create", return_value=fake_worktree), \
             patch("threading.Thread") as mock_thread_cls:
            mock_thread_inst = MagicMock()
            mock_thread_cls.return_value = mock_thread_inst
            result = listener.start_plan_runner(command, r)

        assert result["success"] is True
        assert "abc12345" in listener._running_processes
        r.sadd.assert_called_with(listener.ACTIVE_RUNNERS_KEY, "abc12345")

    def test_boundary_same_runner_id_twice_returns_already_running(self):
        """TC-Boundary: 동일 runner_id로 두 번 start → 두 번째 Already running 반환"""
        listener = _load_listener()

        mock_proc = MagicMock()
        mock_proc.pid = 9999
        mock_proc.poll.return_value = None  # 실행 중
        listener._running_processes["dup11111"] = mock_proc

        fake_worktree = Path("/tmp/worktrees/dup11111")
        with patch.object(listener, "_is_pid_alive", return_value=True), \
             patch.object(listener.WorktreeManager, "create", return_value=fake_worktree):
            r = _make_redis_mock()
            command = {
                "action": "run",
                "runner_id": "dup11111",
                "plan_file": "test.md",
                "engine": "claude",
            }
            result = listener.start_plan_runner(command, r)

        assert result["success"] is False
        assert "Already running" in result["message"]

    def test_error_no_runner_id_returns_failure(self):
        """TC-Error: runner_id 없는 command → success=False, 예외 없음"""
        listener = _load_listener()
        r = _make_redis_mock()
        command = {"action": "run", "plan_file": "test.md"}
        result = listener.start_plan_runner(command, r)

        assert result["success"] is False
        assert "runner_id" in result["message"]


class TestStopPlanRunner:
    """Task 7: stop_plan_runner()"""

    def test_inverse_stop_removes_runner_from_processes(self):
        """TC-Inverse: stop 후 _running_processes에서 runner_id 키 제거"""
        listener = _load_listener()

        mock_proc = MagicMock()
        mock_proc.pid = 5678
        mock_proc.poll.return_value = None  # 실행 중
        listener._running_processes["stop1111"] = mock_proc

        r = _make_redis_mock()
        result = listener.stop_plan_runner("stop1111", r)

        assert result["success"] is True
        assert "stop1111" not in listener._running_processes

    def test_stop_not_running_returns_failure(self):
        """TC-Error: 실행 중이 아닌 runner_id → success=False"""
        listener = _load_listener()
        r = _make_redis_mock()
        result = listener.stop_plan_runner("notexist", r)

        assert result["success"] is False
        assert "Not running" in result["message"]


class TestExecuteCommand:
    """Task 8: execute_command() runner_id 전달"""

    def test_cross_stop_passes_runner_id(self):
        """TC-Cross: execute_command stop → stop_plan_runner에 runner_id 전달"""
        listener = _load_listener()
        r = _make_redis_mock()
        with patch.object(listener, "stop_plan_runner", return_value={"success": True, "message": "ok"}) as mock_stop:
            listener.execute_command({"action": "stop", "runner_id": "abc12345"}, r)
            mock_stop.assert_called_once_with("abc12345", r)

    def test_cross_force_stop_passes_runner_id(self):
        """TC-Cross: execute_command force-stop → force_stop_plan_runner에 runner_id 전달"""
        listener = _load_listener()
        r = _make_redis_mock()
        with patch.object(listener, "force_stop_plan_runner", return_value={"success": True, "message": "ok"}) as mock_fs:
            listener.execute_command({"action": "force-stop", "runner_id": "abc12345"}, r)
            mock_fs.assert_called_once_with("abc12345", r)
