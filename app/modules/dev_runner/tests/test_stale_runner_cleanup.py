"""Stale runner cleanup & reconnect logic unit tests

Tests for:
- _reconnect_surviving_runners(): alive PID → attach, dead PID → cleanup
- _attach_to_running_process(): log file missing → cleanup fallback
- _DummyProcess.poll(): returns None when alive, -1 when dead
- ExecutorService._cleanup_stale_runners(): removes dead-PID entries
"""
import sys
import types
import importlib
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock

import pytest

# ---------------------------------------------------------------------------
# Helpers: build a minimal fake module so listener can be imported without
# its heavy optional dependencies (worktree_manager, merge_workflow, etc.)
# ---------------------------------------------------------------------------
_SCRIPTS_DIR = Path(__file__).parents[4] / "scripts"


def _make_fake_module(name: str) -> types.ModuleType:
    mod = types.ModuleType(name)
    sys.modules[name] = mod
    return mod


def _prepare_listener_imports():
    """Inject stub modules so dev-runner-command-listener can be imported."""
    for name in ("listener_noise_filter", "worktree_manager", "merge_workflow"):
        if name not in sys.modules:
            mod = _make_fake_module(name)
            if name == "listener_noise_filter":
                mod.NOISE_BLOCK_MARKERS = []
                mod.is_noise_line = lambda line: False
            if name == "worktree_manager":
                class _WM:
                    @staticmethod
                    def create(*a, **kw):
                        return Path("/tmp/wt"), "branch"
                    @staticmethod
                    def remove(*a, **kw):
                        pass
                mod.WorktreeManager = _WM
                mod.WorktreeError = Exception
                mod.ensure_main_branch = lambda *a, **kw: None
    # Ensure scripts dir is on path
    if str(_SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_DIR))


_prepare_listener_imports()

# Import the listener module by file path (module name has dashes)
import importlib.util
_LISTENER_PATH = _SCRIPTS_DIR / "dev-runner-command-listener.py"
_spec = importlib.util.spec_from_file_location("dev_runner_listener", str(_LISTENER_PATH))
_listener = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_listener)

_DummyProcess = _listener._DummyProcess
_reconnect_surviving_runners = _listener._reconnect_surviving_runners
_attach_to_running_process = _listener._attach_to_running_process
_cleanup_process_state = _listener._cleanup_process_state
_proc_utils = importlib.import_module(_DummyProcess.__module__)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _reset_listener_globals():
    """Ensure listener global dicts are clean before each test."""
    _listener._running_processes.clear()
    _listener._running_log_files.clear()
    _listener._stream_threads.clear()
    yield
    _listener._running_processes.clear()
    _listener._running_log_files.clear()
    _listener._stream_threads.clear()


def _make_redis(active_runners=None, pid_map=None, log_path=None, heartbeat_map=None):
    """Return a MagicMock Redis client with configurable smembers / get."""
    r = MagicMock()
    r.smembers.return_value = set(active_runners or [])

    def _get(key):
        if pid_map:
            for runner_id, pid in pid_map.items():
                if key == f"plan-runner:runners:{runner_id}:pid":
                    return str(pid)
        if log_path:
            for runner_id, path in log_path.items():
                if key == f"plan-runner:runners:{runner_id}:log_file_path":
                    return path
                if key == f"plan-runner:runners:{runner_id}:stream_log_path":
                    return None
        if heartbeat_map:
            for runner_id, hb in heartbeat_map.items():
                if key == f"plan-runner:runners:{runner_id}:subprocess_heartbeat":
                    return hb
        return None

    r.get.side_effect = _get
    return r


# ---------------------------------------------------------------------------
# _DummyProcess tests
# ---------------------------------------------------------------------------
class TestDummyProcess:
    def test_poll_returns_none_when_alive(self):
        """poll() should return None when PID is alive."""
        with patch.object(_proc_utils, "_is_pid_alive", return_value=True):
            dp = _DummyProcess(1234)
            assert dp.poll() is None
            assert dp.returncode is None

    def test_poll_returns_minus_one_when_dead(self):
        """poll() should return -1 and set returncode when PID is dead."""
        with patch.object(_proc_utils, "_is_pid_alive", return_value=False):
            dp = _DummyProcess(9999)
            result = dp.poll()
            assert result == -1
            assert dp.returncode == -1

    def test_poll_caches_returncode(self):
        """poll() should not call _is_pid_alive again once returncode is set."""
        call_count = 0

        def _side(pid):
            nonlocal call_count
            call_count += 1
            return False

        with patch.object(_proc_utils, "_is_pid_alive", side_effect=_side):
            dp = _DummyProcess(42)
            dp.poll()  # sets returncode = -1
            dp.poll()  # should not call _is_pid_alive again
        assert call_count == 1


# ---------------------------------------------------------------------------
# _reconnect_surviving_runners tests
# ---------------------------------------------------------------------------
class TestReconnectSurvivingRunners:
    def test_right_alive_pid_registers_dummy_process(self):
        """Alive PID should result in _DummyProcess registered in _running_processes."""
        runner_id = "abc12345"
        pid = 5555
        # subprocess_heartbeat를 제공해야 zombie 감지를 우회하고 _attach_to_running_process 호출
        r = _make_redis(active_runners=[runner_id], pid_map={runner_id: pid},
                        log_path={runner_id: "/tmp/fake.log"},
                        heartbeat_map={runner_id: "1234567890"})

        with (
            patch.object(_proc_utils, "_is_pid_alive", return_value=True),
            patch.object(_proc_utils, "_attach_to_running_process") as mock_attach,
        ):
            _reconnect_surviving_runners(r)
            mock_attach.assert_called_once_with(runner_id, pid, r)

    def test_right_dead_pid_calls_cleanup(self):
        """Dead PID should trigger _cleanup_process_state."""
        runner_id = "dead0001"
        pid = 1111
        r = _make_redis(active_runners=[runner_id], pid_map={runner_id: pid})

        with (
            patch.object(_proc_utils, "_is_pid_alive", return_value=False),
            patch.object(_proc_utils, "_cleanup_process_state") as mock_cleanup,
        ):
            _reconnect_surviving_runners(r)
            mock_cleanup.assert_called_once_with(runner_id, r, reason="reconnect_orphan")

    def test_right_no_pid_key_calls_cleanup(self):
        """Missing PID key should trigger cleanup."""
        runner_id = "nopid001"
        r = _make_redis(active_runners=[runner_id], pid_map={})  # no pid entry

        with patch.object(_proc_utils, "_cleanup_process_state") as mock_cleanup:
            _reconnect_surviving_runners(r)
            mock_cleanup.assert_called_once_with(runner_id, r, reason="reconnect_orphan")

    def test_right_already_in_running_processes_skips(self):
        """Runner already in _running_processes should be skipped."""
        runner_id = "skip0001"
        pid = 9999
        r = _make_redis(active_runners=[runner_id], pid_map={runner_id: pid})
        # Simulate already registered
        _listener._running_processes[runner_id] = _DummyProcess(pid)

        with (
            patch.object(_proc_utils, "_is_pid_alive", return_value=True),
            patch.object(_proc_utils, "_attach_to_running_process") as mock_attach,
        ):
            _reconnect_surviving_runners(r)
            mock_attach.assert_not_called()


# ---------------------------------------------------------------------------
# _attach_to_running_process tests
# ---------------------------------------------------------------------------
class TestAttachToRunningProcess:
    def test_boundary_no_log_file_falls_back_to_cleanup(self, tmp_path):
        """If log file path does not exist, should call cleanup."""
        runner_id = "nolog001"
        pid = 1234
        r = MagicMock()
        r.get.return_value = None  # no log file path in Redis

        with patch.object(_proc_utils, "_cleanup_process_state") as mock_cleanup:
            _attach_to_running_process(runner_id, pid, r)
            mock_cleanup.assert_called_once_with(runner_id, r, reason="no_log_file")

    def test_right_valid_log_file_registers_dummy(self, tmp_path):
        """Valid log file should register _DummyProcess and start threads."""
        runner_id = "validlog1"
        pid = 2222
        log_file = tmp_path / "test.log"
        log_file.write_text("existing log content\n")

        r = MagicMock()
        r.get.side_effect = lambda key: str(log_file) if "log_file_path" in key else None

        with (
            patch("threading.Thread") as MockThread,
        ):
            mock_thread = MagicMock()
            MockThread.return_value = mock_thread
            _attach_to_running_process(runner_id, pid, r)

        assert runner_id in _listener._running_processes
        assert isinstance(_listener._running_processes[runner_id], _DummyProcess)
        assert _listener._running_processes[runner_id].pid == pid


# ---------------------------------------------------------------------------
# ExecutorService._cleanup_stale_runners tests
# ---------------------------------------------------------------------------
class TestCleanupStaleRunners:
    """Tests for the async _cleanup_stale_runners method."""

    @pytest.fixture
    def executor(self):
        """Return ExecutorService with mocked Redis clients."""
        # Import here to avoid circular issues at module load
        sys.path.insert(0, str(Path(__file__).parents[4]))
        from app.modules.dev_runner.services.executor_service import ExecutorService
        svc = ExecutorService.__new__(ExecutorService)
        svc.redis_client = MagicMock()
        svc.async_redis = MagicMock()
        return svc

    @pytest.mark.asyncio
    async def test_right_removes_dead_pid(self, executor):
        """Dead-PID runner should be cleaned up."""
        runner_id = "stale001"
        executor.async_redis.smembers = MagicMock(return_value={runner_id})
        executor.async_redis.get = MagicMock(return_value="9999")
        executor._is_pid_alive = MagicMock(return_value=False)
        executor._force_cleanup_state = AsyncMock()

        # Make async_redis.smembers / get awaitable
        import asyncio

        async def _smembers(key):
            return {runner_id}

        async def _get(key):
            return "9999"

        executor.async_redis.smembers = _smembers
        executor.async_redis.get = _get

        n = await executor._cleanup_stale_runners()
        assert n["total"] == 1
        assert n["cleaned_active"] == 1

    @pytest.mark.asyncio
    async def test_right_keeps_alive_pid(self, executor):
        """Alive-PID runner should NOT be cleaned up."""
        runner_id = "alive001"
        import asyncio

        async def _smembers(key):
            return {runner_id}

        async def _get(key):
            return "1234"

        executor.async_redis.smembers = _smembers
        executor.async_redis.get = _get
        executor._is_pid_alive = MagicMock(return_value=True)
        executor._force_cleanup_state = AsyncMock()

        n = await executor._cleanup_stale_runners()
        assert n["total"] == 0
        assert n["cleaned_active"] == 0


# ---------------------------------------------------------------------------
# TestPrepareListenerImports: _prepare_listener_imports() stub 검증
# ---------------------------------------------------------------------------


class TestPrepareListenerImports:
    """_prepare_listener_imports()가 fake worktree_manager를 올바르게 등록하는지 검증"""

    def setup_method(self):
        # 매 테스트 전 worktree_manager와 listener를 sys.modules에서 제거
        sys.modules.pop("worktree_manager", None)
        sys.modules.pop("dev_runner_listener", None)

    def test_prepare_listener_imports_right_ensure_main_branch_exists(self):
        """R: _prepare_listener_imports 후 sys.modules['worktree_manager'].ensure_main_branch가 callable"""
        _prepare_listener_imports()
        wm = sys.modules.get("worktree_manager")
        assert wm is not None, "worktree_manager가 sys.modules에 없음"
        assert callable(getattr(wm, "ensure_main_branch", None)), \
            "ensure_main_branch가 callable이 아님"

    def test_prepare_listener_imports_right_worktree_manager_stub_complete(self):
        """R: stub에 WorktreeManager, WorktreeError, ensure_main_branch 3개 모두 존재"""
        _prepare_listener_imports()
        wm = sys.modules.get("worktree_manager")
        assert hasattr(wm, "WorktreeManager"), "WorktreeManager 없음"
        assert hasattr(wm, "WorktreeError"), "WorktreeError 없음"
        assert hasattr(wm, "ensure_main_branch"), "ensure_main_branch 없음"

    def test_prepare_listener_imports_boundary_idempotent(self):
        """B: 2회 연속 호출 시 worktree_manager 모듈 객체가 동일 (if name not in sys.modules 가드 검증)"""
        _prepare_listener_imports()
        first = sys.modules.get("worktree_manager")
        _prepare_listener_imports()
        second = sys.modules.get("worktree_manager")
        assert first is second, "2회 호출 시 다른 모듈 객체가 등록됨"

    def test_missing_ensure_main_branch_causes_import_error(self):
        """T3: 최소 worktree_manager stub에서도 listener import가 깨지지 않아야 함."""
        import importlib.util
        import types

        _SCRIPTS_DIR = Path(__file__).parents[4] / "scripts"
        _LISTENER_FILE = _SCRIPTS_DIR / "dev-runner-command-listener.py"

        def _inject_incomplete_stub():
            """ensure_main_branch 없는 minimal fake worktree_manager 주입"""
            sys.modules.pop("dev_runner_listener", None)
            sys.modules.pop("worktree_manager", None)
            mod = types.ModuleType("worktree_manager")

            class _WM:
                @staticmethod
                def create(*a, **kw):
                    return Path("/tmp/wt"), "branch"

                @staticmethod
                def remove(*a, **kw):
                    pass

            mod.WorktreeManager = _WM
            mod.WorktreeError = Exception
            # ensure_main_branch 의도적으로 누락
            sys.modules["worktree_manager"] = mod

        def _load_listener():
            spec = importlib.util.spec_from_file_location(
                "dev_runner_listener", _LISTENER_FILE
            )
            m = importlib.util.module_from_spec(spec)
            sys.modules["dev_runner_listener"] = m
            spec.loader.exec_module(m)

        # 1) incomplete stub → 현재 구조에서는 import 성공해야 함 (listener가 직접 의존하지 않음)
        _inject_incomplete_stub()
        try:
            _load_listener()
        except (ImportError, AttributeError) as e:
            pytest.fail(f"최소 stub에서 import 오류 발생: {e}")

        # 2) _prepare_listener_imports()으로 올바른 stub 주입 → 오류 없음
        sys.modules.pop("dev_runner_listener", None)
        sys.modules.pop("worktree_manager", None)
        _prepare_listener_imports()
        try:
            _load_listener()
        except (ImportError, AttributeError) as e:
            pytest.fail(f"수정 후에도 import 오류: {e}")
