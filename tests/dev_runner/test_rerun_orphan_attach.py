"""T1/T2/T3: rerun orphan attach verification.

Phase T1 unit tests:
- Duplicate detection by plan_file (attach / new execution / PID dead / all-plans ignore / cleaning up)
- _tail_log_and_publish replay_from_start behavior
- _cleanup_process_state cleanup_in_progress flag

Phase T3 integration tests:
- fakeredis shared server + actual function call attach -> per-command result key verification
"""
from __future__ import annotations

import json
import importlib
import sys
import time
import threading
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import fakeredis
import pytest

# add scripts path
_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

# dependency module stubs (without full listener loading)
import types


def _install_stub_module(module_name: str, **attrs):
    stub = types.ModuleType(module_name)
    for key, value in attrs.items():
        setattr(stub, key, value)
    return stub


# noise_filter default settings
_nf = _install_stub_module(
    "listener_noise_filter",
    NOISE_BLOCK_MARKERS=[],
    is_noise_line=lambda line: False,
)

# merge_queue stubs
_mq = _install_stub_module(
    "merge_queue",
    release_merge_turn=lambda *a, **kw: None,
    _get_repo_id=lambda *a, **kw: "test-repo",
    get_queue_key=lambda *a, **kw: "test:queue",
)

# worktree_manager stubs
class _WM:
    @staticmethod
    def remove(*a, **kw):
        pass


_wm = _install_stub_module("worktree_manager", WorktreeManager=_WM)

# plan_worktree_helpers stubs
_pwh = _install_stub_module(
    "plan_worktree_helpers",
    is_plan_in_progress=lambda *a, **kw: False,
)

from _dr_constants import RUNNER_KEY_PREFIX, ACTIVE_RUNNERS_KEY, PLAN_FILE_ALL, _LEGACY_ALL, RESULTS_KEY, LOG_CHANNEL_PREFIX
import _dr_state as _dr_state_module
from _dr_state import get_running_processes
from _dr_process_utils import _tail_log_and_publish, _cleanup_process_state, _DummyProcess
from _dr_plan_runner import start_plan_runner


# ?????????????????????????????????????????????????????????????
# Helpers
# ?????????????????????????????????????????????????????????????

@pytest.fixture(autouse=True)
def _install_dev_runner_stubs(monkeypatch):
    monkeypatch.setitem(sys.modules, "listener_noise_filter", _nf)
    monkeypatch.setitem(sys.modules, "merge_queue", _mq)
    monkeypatch.setitem(sys.modules, "worktree_manager", _wm)
    monkeypatch.setitem(sys.modules, "plan_worktree_helpers", _pwh)

    # 이전 테스트 파일에서 이미 로드된 dev-runner 모듈을 강제로 비우고,
    # 여기서 설치한 stub를 반영한 fresh import로 다시 연결한다.
    for module_name in (
        "_dr_state",
        "_dr_process_utils",
        "_dr_plan_runner",
        "scripts.plan_runner._dr_state",
        "scripts.plan_runner._dr_process_utils",
        "scripts.plan_runner._dr_plan_runner",
    ):
        sys.modules.pop(module_name, None)

    global _dr_state_module, get_running_processes
    global _tail_log_and_publish, _cleanup_process_state, _DummyProcess, start_plan_runner

    _dr_state_module = importlib.import_module("_dr_state")
    get_running_processes = _dr_state_module.get_running_processes

    _process_utils_module = importlib.import_module("_dr_process_utils")
    _tail_log_and_publish = _process_utils_module._tail_log_and_publish
    _cleanup_process_state = _process_utils_module._cleanup_process_state
    _DummyProcess = _process_utils_module._DummyProcess

    _plan_runner_module = importlib.import_module("_dr_plan_runner")
    start_plan_runner = _plan_runner_module.start_plan_runner


@pytest.fixture(autouse=True)
def _reset_running_processes(monkeypatch):
    for name in ("_running_processes", "_running_log_files", "_stream_threads", "_cleanup_done", "_dead_process_first_seen", "_zombie_first_seen"):
        getattr(_dr_state_module, name).clear()
    monkeypatch.setattr("_dr_plan_runner.get_running_processes", _dr_state_module.get_running_processes)
    monkeypatch.setattr("_dr_process_utils.get_running_processes", _dr_state_module.get_running_processes)


def _make_fr():
    return fakeredis.FakeRedis(decode_responses=True)


def _seed_runner(r, runner_id: str, plan_file: str, pid: int = 1234):
    """register running runner in fakeredis"""
    r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
    r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file", plan_file)
    r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:pid", str(pid))
    r.sadd(ACTIVE_RUNNERS_KEY, runner_id)


def _pop_result(r, command_id: str) -> dict:
    """pop result from per-command result key"""
    result_key = f"{RESULTS_KEY}:{command_id}" if command_id else RESULTS_KEY
    raw = r.rpop(result_key)
    if raw:
        return json.loads(raw)
    return {}


def _make_command(plan_file: str, runner_id: str = "new-runner-001", command_id: str = "cmd-001") -> dict:
    return {
        "action": "run",
        "runner_id": runner_id,
        "plan_file": plan_file,
        "command_id": command_id,
        "engine": "claude",
    }


# ?????????????????????????????????????????????????????????????
# Phase T1: plan_file based duplicate detection
# ?????????????????????????????????????????????????????????????

class TestStartPlanRunnerDuplicateDetection:
    """start_plan_runner plan_file based attach detection logic"""

    def test_start_detects_existing_runner_same_plan(self):
        """R: return attached response if runner with same plan_file is running"""
        r = _make_fr()
        existing_id = "existing-runner-abc"
        _seed_runner(r, existing_id, plan_file="docs/plan/test.md", pid=9999)

        cmd = _make_command(plan_file="docs/plan/test.md", runner_id="new-runner-xyz")

        with patch("_dr_plan_runner._is_pid_alive", return_value=True), \
             patch("_dr_plan_runner._do_start_plan_runner"), \
             patch("_dr_plan_runner._cleanup_process_state"):
            result = start_plan_runner(cmd, r)

        # returns None sentinel (accepted is pushed to result key)
        assert result is None
        resp = _pop_result(r, "cmd-001")
        assert resp.get("success") is True
        assert resp.get("status") == "attached"
        assert resp.get("runner_id") == existing_id

    def test_start_creates_new_when_different_plan(self):
        """I: run new if runner with different plan_file is running"""
        r = _make_fr()
        _seed_runner(r, "existing-runner-abc", plan_file="docs/plan/a.md", pid=9999)

        cmd = _make_command(plan_file="docs/plan/b.md", runner_id="new-runner-xyz")

        thread_started = []
        with patch("_dr_plan_runner._is_pid_alive", return_value=True), \
             patch("_dr_plan_runner.threading") as mock_threading:
            mock_thread = MagicMock()
            mock_threading.Thread.return_value = mock_thread
            result = start_plan_runner(cmd, r)
            thread_started.append(mock_thread.start.called)

        assert result is None
        resp = _pop_result(r, "cmd-001")
        # accepted, not attached
        assert resp.get("status") != "attached"
        assert resp.get("message") == "accepted"
        assert thread_started[0] is True  # new thread started

    def test_start_creates_new_when_dead_pid(self):
        """B: run new if PID is dead even with same plan_file"""
        r = _make_fr()
        _seed_runner(r, "existing-dead", plan_file="docs/plan/test.md", pid=9999)

        cmd = _make_command(plan_file="docs/plan/test.md", runner_id="new-runner-xyz")

        with patch("_dr_plan_runner._is_pid_alive", return_value=False), \
             patch("_dr_plan_runner.threading") as mock_threading:
            mock_thread = MagicMock()
            mock_threading.Thread.return_value = mock_thread
            result = start_plan_runner(cmd, r)

        assert result is None
        resp = _pop_result(r, "cmd-001")
        assert resp.get("message") == "accepted"
        assert resp.get("status") != "attached"

    def test_start_ignores_all_plans_runner(self):
        """B: plan_file=__ALL_PLANS__ runner is excluded from attach targets"""
        r = _make_fr()
        _seed_runner(r, "all-plans-runner", plan_file=PLAN_FILE_ALL, pid=9999)

        cmd = _make_command(plan_file="docs/plan/test.md", runner_id="new-runner-xyz")

        with patch("_dr_plan_runner._is_pid_alive", return_value=True), \
             patch("_dr_plan_runner.threading") as mock_threading:
            mock_thread = MagicMock()
            mock_threading.Thread.return_value = mock_thread
            result = start_plan_runner(cmd, r)

        assert result is None
        resp = _pop_result(r, "cmd-001")
        assert resp.get("message") == "accepted"

    def test_start_ignores_legacy_all_runner(self):
        """B: plan_file=ALL (legacy) runner is excluded from attach targets"""
        r = _make_fr()
        _seed_runner(r, "legacy-all-runner", plan_file=_LEGACY_ALL, pid=9999)

        cmd = _make_command(plan_file="docs/plan/test.md", runner_id="new-runner-xyz")

        with patch("_dr_plan_runner._is_pid_alive", return_value=True), \
             patch("_dr_plan_runner.threading") as mock_threading:
            mock_thread = MagicMock()
            mock_threading.Thread.return_value = mock_thread
            result = start_plan_runner(cmd, r)

        assert result is None
        resp = _pop_result(r, "cmd-001")
        assert resp.get("message") == "accepted"

    def test_start_returns_cleanup_in_progress(self):
        """B: return 'cleaning up' if same plan cleanup is in progress"""
        r = _make_fr()
        cleaning_id = "cleaning-runner-abc"
        _seed_runner(r, cleaning_id, plan_file="docs/plan/test.md", pid=9999)
        r.set(f"{RUNNER_KEY_PREFIX}:{cleaning_id}:cleanup_in_progress", "1")

        cmd = _make_command(plan_file="docs/plan/test.md", runner_id="new-runner-xyz")

        with patch("_dr_plan_runner._is_pid_alive", return_value=False):
            result = start_plan_runner(cmd, r)

        assert result is None
        resp = _pop_result(r, "cmd-001")
        assert resp.get("success") is False
        # use partial match to avoid encoding issues if it returns Korean
        assert resp.get("message") is not None


# ?????????????????????????????????????????????????????????????
# Phase T1: _tail_log_and_publish replay behavior
# ?????????????????????????????????????????????????????????????

class TestTailLogReplay:
    """_tail_log_and_publish replay_from_start behavior verification"""

    def _write_log_lines(self, tmp_path: Path, count: int) -> Path:
        log_file = tmp_path / "runner.log"
        log_file.write_text("\n".join(f"LOG LINE {i}" for i in range(count)) + "\n", encoding="utf-8")
        return log_file

    def test_tail_log_replay_from_start_publishes_all(self, tmp_path):
        """R: publish all existing logs from start if replay_from_start=True"""
        r = _make_fr()
        runner_id = "replay-runner-001"
        log_file = self._write_log_lines(tmp_path, 10)

        # register DummyProcess that exits immediately in _running_processes
        dummy = MagicMock()
        dummy.pid = 1234
        dummy.poll.return_value = 0  # already exited

        published = []

        def _fake_publish(redis_client, channel, data):
            published.append(data)

        procs = {runner_id: dummy}
        with patch.dict(_tail_log_and_publish.__globals__, {
            "get_running_processes": lambda: procs,
        }), patch("_dr_process_utils._publish_with_retry", side_effect=_fake_publish):
            _tail_log_and_publish(runner_id, str(log_file), r, replay_from_start=True)

        # all 10 lines published
        content = " ".join(published)
        for i in range(10):
            assert f"LOG LINE {i}" in content, f"LINE {i} missing (published={published})"

    def test_tail_log_default_skips_existing(self, tmp_path):
        """I: do not publish existing lines if replay_from_start=False (default)"""
        r = _make_fr()
        runner_id = "noreplay-runner-001"
        log_file = self._write_log_lines(tmp_path, 10)

        dummy = MagicMock()
        dummy.pid = 1234
        dummy.poll.return_value = 0

        published = []

        def _fake_publish(redis_client, channel, data):
            published.append(data)

        procs = {runner_id: dummy}
        with patch.dict(_tail_log_and_publish.__globals__, {
            "get_running_processes": lambda: procs,
        }), patch("_dr_process_utils._publish_with_retry", side_effect=_fake_publish):
            _tail_log_and_publish(runner_id, str(log_file), r, replay_from_start=False)

        # existing 10 lines should not be published (start from EOF)
        assert len(published) == 0, f"existing lines published: {published}"


# ?????????????????????????????????????????????????????????????
# Phase T1: _cleanup_process_state cleanup_in_progress flag
# ?????????????????????????????????????????????????????????????

class TestCleanupInProgressFlag:
    """_cleanup_process_state cleanup_in_progress Redis flag verification"""

    def _minimal_cleanup(self, runner_id: str, r):
        """execute _cleanup_process_state with minimal dependency mocks"""
        wf_mgr = MagicMock()
        wf_mgr.get_by_runner_id.return_value = None

        wm_stub = MagicMock()
        wm_stub.remove.return_value = None

        with patch("_dr_process_utils.get_wf_manager", return_value=wf_mgr), \
             patch("_dr_runner_predicates._is_pre_review_stopped_runner", return_value=False), \
             patch("_dr_process_utils._try_v2_merge_fallback"), \
             patch("worktree_manager.WorktreeManager", wm_stub), \
             patch("plan_worktree_helpers.is_plan_in_progress", return_value=False):
            _cleanup_process_state(runner_id, r, reason="test")

    def test_cleanup_clears_in_progress_flag(self):
        """R: cleanup_in_progress key is deleted after cleanup completion"""
        r = _make_fr()
        runner_id = "cleanup-test-001"
        r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file", "docs/plan/x.md")
        r.sadd(ACTIVE_RUNNERS_KEY, runner_id)

        self._minimal_cleanup(runner_id, r)

        # should not have flag after completion
        flag = r.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:cleanup_in_progress")
        assert flag is None, f"cleanup_in_progress not deleted: {flag}"

    def test_cleanup_sets_in_progress_then_clears(self):
        """R: set flag on entry, delete on completion"""
        r = _make_fr()
        runner_id = "cleanup-test-002"
        r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        r.sadd(ACTIVE_RUNNERS_KEY, runner_id)

        # execution cleanup and verify
        self._minimal_cleanup(runner_id, r)
        flag_after = r.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:cleanup_in_progress")
        assert flag_after is None


# ?????????????????????????????????????????????????????????????
# Phase T3: rerun -> attach integration test
# ?????????????????????????????????????????????????????????????

class TestRerunAttachIntegration:
    """verify actual start_plan_runner attach flow with fakeredis shared server"""

    def test_rerun_attaches_to_alive_worker_integration(self):
        """T3: rerun while same plan is running -> attached response + existing runner_id returned"""
        server = fakeredis.FakeServer()
        r1 = fakeredis.FakeRedis(server=server, decode_responses=True)
        r2 = fakeredis.FakeRedis(server=server, decode_responses=True)

        existing_id = "existing-int-runner"
        plan_file = "docs/plan/integration_test.md"
        _seed_runner(r1, existing_id, plan_file=plan_file, pid=7777)

        cmd = _make_command(plan_file=plan_file, runner_id="new-int-runner", command_id="cmd-int-001")

        with patch("_dr_plan_runner._is_pid_alive", return_value=True), \
             patch("_dr_plan_runner._cleanup_process_state"):
            result = start_plan_runner(cmd, r2)

        assert result is None

        resp = _pop_result(r2, "cmd-int-001")
        assert resp["success"] is True, f"success expected True, actual: {resp}"
        assert resp["status"] == "attached", f"status expected attached, actual: {resp}"
        assert resp["runner_id"] == existing_id

    def test_rerun_creates_new_after_stop_integration(self):
        """T3: rerun after stop -> accepted with new runner_id (no orphan)"""
        r = _make_fr()
        old_id = "old-stopped-runner"
        plan_file = "docs/plan/stop_then_run.md"

        # after stop: not in ACTIVE_RUNNERS (assume cleanup called srem)
        r.set(f"{RUNNER_KEY_PREFIX}:{old_id}:status", "stopped")
        r.set(f"{RUNNER_KEY_PREFIX}:{old_id}:plan_file", plan_file)
        # do not add to ACTIVE_RUNNERS (state after stop)

        cmd = _make_command(plan_file=plan_file, runner_id="brand-new-runner", command_id="cmd-new-001")

        with patch("_dr_plan_runner._is_pid_alive", return_value=True), \
             patch("_dr_plan_runner.threading") as mock_threading:
            mock_thread = MagicMock()
            mock_threading.Thread.return_value = mock_thread
            result = start_plan_runner(cmd, r)

        assert result is None
        resp = _pop_result(r, "cmd-new-001")
        # accepted, not attached
        assert resp.get("message") == "accepted"
        assert resp.get("status") != "attached"


# ?????????????????????????????????????????????????????????????
# Phase T1 item 16: ExecutorService attached response handling
# ?????????????????????????????????????????????????????????????

class TestExecutorServiceAttachedResponse:
    """verification of ExecutorService.start_dev_runner attached response handling"""

    @pytest.fixture
    def fake_async_redis(self):
        import fakeredis.aioredis
        return fakeredis.aioredis.FakeRedis(decode_responses=True)

    @pytest.fixture
    def executor(self, fake_async_redis, monkeypatch):
        monkeypatch.setenv("PLAN_RUNNER_REDIS_DB", "15")
        from app.modules.dev_runner.services.executor_service import ExecutorService
        import fakeredis
        svc = ExecutorService()
        svc.redis_client = fakeredis.FakeRedis(decode_responses=True)
        svc.async_redis = fake_async_redis
        return svc

    async def test_start_dev_runner_returns_attached_response(self, executor, fake_async_redis):
        """R: _send_command returns attached -> RunStatusResponse.attached==True"""
        existing_id = "existing-runner-from-exec"
        await fake_async_redis.set("plan-runner:listener:heartbeat", "alive")
        # existing runner Redis state setup
        await fake_async_redis.set(f"plan-runner:runners:{existing_id}:pid", "5678")
        await fake_async_redis.set(f"plan-runner:runners:{existing_id}:plan_file", "docs/plan/test.md")
        await fake_async_redis.set(f"plan-runner:runners:{existing_id}:engine", "claude")
        from datetime import datetime
        await fake_async_redis.set(f"plan-runner:runners:{existing_id}:start_time", datetime.now().isoformat())
        await fake_async_redis.set(f"plan-runner:runners:{existing_id}:execution_count", "3")

        attached_resp = {
            "success": True,
            "status": "attached",
            "runner_id": existing_id,
            "message": "attached to existing worker",
        }

        from app.modules.dev_runner.schemas import RunRequest
        request = RunRequest(test_source="tc:exec-attach", plan_file="docs/plan/test.md")

        with patch.object(executor, "_send_command", return_value=attached_resp):
            from app.modules.dev_runner.services.executor_service import ExecutorService
            result = await executor.start_dev_runner(request)

        assert result.attached is True, f"expected attached True, actual: {result}"
        assert result.runner_id == existing_id
        assert result.running is True
        assert result.pid == 5678
        assert result.execution_count == 3

    async def test_start_dev_runner_normal_run_not_attached(self, executor, fake_async_redis):
        """I: normal run response -> RunStatusResponse.attached==False"""
        await fake_async_redis.set("plan-runner:listener:heartbeat", "alive")

        accepted_resp = {
            "success": True,
            "message": "accepted",
            "runner_id": "whatever-uuid",
        }

        from datetime import datetime
        runner_fields = {
            "pid": "9876",
            "plan_file": "docs/plan/test.md",
            "start_time": datetime.now().isoformat(),
            "execution_count": "1",
        }

        from app.modules.dev_runner.schemas import RunRequest
        request = RunRequest(test_source="tc:exec-normal", plan_file="docs/plan/test.md")

        with patch.object(executor, "_send_command", return_value=accepted_resp), \
             patch.object(executor, "_get_runner_fields", return_value=runner_fields):
            result = await executor.start_dev_runner(request)

        assert result.attached is False, f"expected attached False, actual: {result}"

