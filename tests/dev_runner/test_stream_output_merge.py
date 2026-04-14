"""_stream_output finally merge branch TC

Target: scripts/plan_runner/_dr_stream_cleanup.py
Content: merge_requested flag consolidation + logging + workflow status logic
"""

import importlib.util
import io
import os
import subprocess
import tempfile
import pytest
from unittest.mock import MagicMock, patch
import fakeredis
from tests.dev_runner.conftest import assert_no_magicmock_leak, make_strict_redis_mock

from tests.dev_runner._path_helpers import get_listener_script_path, skip_if_missing


# ========== Module Load ==========

_listener_mod = None


def _get_listener():
    global _listener_mod
    if _listener_mod is not None:
        return _listener_mod
    script_path = get_listener_script_path()
    skip_if_missing(script_path, "Listener script")
    spec = importlib.util.spec_from_file_location("dev_runner_command_listener", str(script_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _listener_mod = mod
    return mod


@pytest.fixture(scope="module")
def listener_mod():
    return _get_listener()


@pytest.fixture(scope="module")
def plan_runner_mod(listener_mod):
    import sys
    return sys.modules["_dr_plan_runner"]


@pytest.fixture(scope="module")
def process_utils_mod(listener_mod):
    import sys
    return sys.modules["_dr_process_utils"]

@pytest.fixture(scope="module")
def stream_cleanup_mod(listener_mod):
    import sys
    return sys.modules["_dr_stream_cleanup"]


# ========== Fixtures ==========

@pytest.fixture
def fr():
    server = fakeredis.FakeServer()
    return fakeredis.FakeRedis(server=server, decode_responses=True)


def _make_process(returncode=0):
    """mock subprocess.Popen"""
    p = MagicMock()
    p.stdout = io.StringIO("")
    p.returncode = returncode
    p.wait.return_value = returncode
    p.poll.return_value = returncode
    return p


def _make_log_handle():
    return io.StringIO()


def _make_wf_manager():
    wf = {"id": 99, "runner_id": "test-runner", "status": "running"}
    mgr = MagicMock()
    mgr.get_by_runner_id.return_value = wf
    return mgr, wf


RUNNER_KEY_PREFIX = "plan-runner:runners"


def _strict_redis_mock() -> MagicMock:
    return make_strict_redis_mock()


# ========== TC ==========

def test_stream_output_finally_merge_requested_flag(listener_mod, plan_runner_mod, stream_cleanup_mod, fr):
    """R(Right): call _do_inline_merge() if merge_requested flag is present"""
    runner_id = "t-stream-aabb"
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_requested", "1")
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:exit_reason", "completed")

    process = _make_process(returncode=0)
    log_handle = _make_log_handle()
    wf_mgr, _ = _make_wf_manager()

    with patch.object(plan_runner_mod, "get_wf_manager", return_value=wf_mgr), \
         patch.object(plan_runner_mod, "get_running_log_files", return_value={}), \
         patch.object(stream_cleanup_mod, "_do_inline_merge") as mock_merge, \
         patch.object(stream_cleanup_mod, "_cleanup_process_state") as mock_cleanup, \
         patch.object(stream_cleanup_mod, "detect_merged_but_not_done", return_value=None):
        listener_mod._stream_output(process, log_handle, fr, runner_id=runner_id)

    mock_merge.assert_called_once_with(runner_id, fr)
    mock_cleanup.assert_not_called()


def test_stream_output_finally_no_merge_flag(listener_mod, plan_runner_mod, stream_cleanup_mod, fr):
    """R(Right): call _cleanup_process_state() if no merge_requested flag"""
    runner_id = "t-stream-eeff"
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:exit_reason", "completed")

    process = _make_process(returncode=0)
    log_handle = _make_log_handle()
    wf_mgr, _ = _make_wf_manager()

    with patch.object(plan_runner_mod, "get_wf_manager", return_value=wf_mgr), \
         patch.object(plan_runner_mod, "get_running_log_files", return_value={}), \
         patch.object(stream_cleanup_mod, "_do_inline_merge") as mock_merge, \
         patch.object(stream_cleanup_mod, "_cleanup_process_state") as mock_cleanup, \
         patch.object(stream_cleanup_mod, "detect_merged_but_not_done", return_value=None):
        listener_mod._stream_output(process, log_handle, fr, runner_id=runner_id)

    mock_cleanup.assert_called_once_with(runner_id, fr)
    mock_merge.assert_not_called()


def test_stream_output_finally_empty_runner_id(listener_mod, plan_runner_mod, stream_cleanup_mod, fr):
    """B(Boundary): call cleanup only without merge if runner_id=''"""
    process = _make_process(returncode=0)
    log_handle = _make_log_handle()

    with patch.object(plan_runner_mod, "get_wf_manager", return_value=None), \
         patch.object(plan_runner_mod, "get_running_log_files", return_value={}), \
         patch.object(stream_cleanup_mod, "_do_inline_merge") as mock_merge, \
         patch.object(stream_cleanup_mod, "_cleanup_process_state") as mock_cleanup, \
         patch.object(stream_cleanup_mod, "detect_merged_but_not_done", return_value=None):
        listener_mod._stream_output(process, log_handle, fr, runner_id="")

    mock_cleanup.assert_called_once_with("", fr)
    mock_merge.assert_not_called()


def test_stream_output_finally_nonzero_exit(listener_mod, plan_runner_mod, stream_cleanup_mod, fr):
    """B(Boundary): workflow failed + cleanup if exit_code=1"""
    runner_id = "t-stream-dead"
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_requested", "1")

    process = _make_process(returncode=1)
    log_handle = _make_log_handle()
    wf_mgr, wf = _make_wf_manager()

    with patch.object(plan_runner_mod, "get_wf_manager", return_value=wf_mgr), \
         patch.object(plan_runner_mod, "get_running_log_files", return_value={}), \
         patch.object(stream_cleanup_mod, "_do_inline_merge") as mock_merge, \
         patch.object(stream_cleanup_mod, "_cleanup_process_state") as mock_cleanup, \
         patch.object(stream_cleanup_mod, "detect_merged_but_not_done", return_value=None):
        listener_mod._stream_output(process, log_handle, fr, runner_id=runner_id)

    wf_mgr.update_status.assert_called_with(
        wf["id"],
        "failed",
        error_message="exit_code=1; exit_reason=error",
    )
    mock_cleanup.assert_called_once_with(runner_id, fr)
    mock_merge.assert_not_called()


def test_stream_output_finally_redis_error(listener_mod, plan_runner_mod, stream_cleanup_mod, fr):
    """E(Error): cleanup fallback + warning if Redis get fails"""
    runner_id = "t-stream-cafe"

    process = _make_process(returncode=0)
    log_handle = _make_log_handle()
    wf_mgr, _ = _make_wf_manager()

    broken_redis = _strict_redis_mock()
    broken_redis.get.side_effect = Exception("Connection refused")

    with patch.object(plan_runner_mod, "get_wf_manager", return_value=wf_mgr), \
         patch.object(plan_runner_mod, "get_running_log_files", return_value={}), \
         patch.object(stream_cleanup_mod, "_do_inline_merge") as mock_merge, \
         patch.object(stream_cleanup_mod, "_cleanup_process_state") as mock_cleanup, \
         patch.object(stream_cleanup_mod, "detect_merged_but_not_done", return_value=None), \
         patch.object(stream_cleanup_mod, "logger") as mock_logger:
        listener_mod._stream_output(process, log_handle, broken_redis, runner_id=runner_id)

    # Redis error -> merge fail -> cleanup fallback
    mock_cleanup.assert_called_once_with(runner_id, broken_redis)
    mock_merge.assert_not_called()


def test_stream_output_workflow_status_no_merge(listener_mod, plan_runner_mod, stream_cleanup_mod, fr):
    """R(Right): workflow status=completed if normal exit without merge_requested"""
    runner_id = "t-stream-1122"
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:exit_reason", "completed")

    process = _make_process(returncode=0)
    log_handle = _make_log_handle()
    wf_mgr, wf = _make_wf_manager()

    with patch.object(plan_runner_mod, "get_wf_manager", return_value=wf_mgr), \
         patch.object(plan_runner_mod, "get_running_log_files", return_value={}), \
         patch.object(stream_cleanup_mod, "_do_inline_merge"), \
         patch.object(stream_cleanup_mod, "_cleanup_process_state"), \
         patch.object(stream_cleanup_mod, "detect_merged_but_not_done", return_value=None):
        listener_mod._stream_output(process, log_handle, fr, runner_id=runner_id)

    wf_mgr.update_status.assert_called_with(wf["id"], "completed")


def test_cleanup_preserves_worktree_when_merge_requested(monkeypatch, listener_mod, process_utils_mod, fr):
    """R(Right): _cleanup_process_state should NOT delete worktree if merge_requested=1"""
    monkeypatch.setattr("plan_worktree_helpers.is_plan_in_progress", lambda *a, **kw: True, raising=False)
    monkeypatch.setattr("plan_worktree_helpers.has_unmerged_commits", lambda *a, **kw: False, raising=False)

    runner_id = "t-clnup-aabb"
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_requested", "1")
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file", "docs/plan/test.md")
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:trigger", "user")

    mock_wt = MagicMock()
    with patch.object(process_utils_mod, "get_running_processes", return_value={}), \
         patch.object(process_utils_mod, "get_running_log_files", return_value={}), \
         patch.object(process_utils_mod, "get_stream_threads", return_value={}), \
         patch.object(process_utils_mod, "get_cleanup_done", return_value={}), \
         patch.object(process_utils_mod, "get_dead_process_first_seen", return_value={}), \
         patch.object(process_utils_mod, "get_wf_manager", return_value=None), \
         patch("worktree_manager.WorktreeManager", mock_wt):
        process_utils_mod._cleanup_process_state(runner_id, fr, reason="test")

    mock_wt.remove.assert_not_called()


def test_cleanup_allows_worktree_removal_without_merge_signal(monkeypatch, listener_mod, fr):
    """E(Error): WorktreeManager.remove called if no merge_requested and no merge_status"""
    monkeypatch.setattr("plan_worktree_helpers.is_plan_in_progress", lambda *a, **kw: False, raising=False)
    monkeypatch.setattr("plan_worktree_helpers.has_unmerged_commits", lambda *a, **kw: False, raising=False)

    runner_id = "t-clnup-eeff"
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file", "docs/plan/test.md")
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:trigger", "user")

    mock_wt = MagicMock()
    import sys
    process_utils_mod = sys.modules["_dr_process_utils"]
    with patch.object(process_utils_mod, "get_running_processes", return_value={}), \
         patch.object(process_utils_mod, "get_running_log_files", return_value={}), \
         patch.object(process_utils_mod, "get_stream_threads", return_value={}), \
         patch.object(process_utils_mod, "get_cleanup_done", return_value={}), \
         patch.object(process_utils_mod, "get_dead_process_first_seen", return_value={}), \
         patch.object(process_utils_mod, "get_wf_manager", return_value=None), \
         patch("worktree_manager.WorktreeManager", mock_wt):
        process_utils_mod._cleanup_process_state(runner_id, fr, reason="test")

    mock_wt.remove.assert_called_once()


def test_v2_fallback_runs_without_merge_flag(listener_mod, plan_runner_mod, stream_cleanup_mod, fr):
    """B(Boundary): execute v2 fallback even without merge_requested flag"""
    runner_id = "t-v2-fallback-001"
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:exit_reason", "completed")

    process = _make_process(returncode=0)
    log_handle = _make_log_handle()
    wf_mgr, _ = _make_wf_manager()

    with patch.object(plan_runner_mod, "get_wf_manager", return_value=wf_mgr), \
         patch.object(plan_runner_mod, "get_running_log_files", return_value={}), \
         patch.object(stream_cleanup_mod, "_do_inline_merge") as mock_merge, \
         patch.object(stream_cleanup_mod, "_cleanup_process_state"), \
         patch.object(stream_cleanup_mod, "detect_merged_but_not_done", return_value=None) as mock_detect:
        listener_mod._stream_output(process, log_handle, fr, runner_id=runner_id)

    mock_detect.assert_called_once_with(runner_id, fr)
    mock_merge.assert_not_called()

