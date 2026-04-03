"""_stream_output finally 머지 분기 TC

대상 소스: scripts/dev-runner-command-listener.py
수정 내용: merge_requested 플래그 확인 1회 통합 + 로그 강화 + workflow 상태 분기 수정
"""

import importlib.util
import io
import pytest
from unittest.mock import MagicMock, patch
import fakeredis

from tests.dev_runner._path_helpers import get_listener_script_path, skip_if_missing


# ========== 모듈 로드 ==========

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


# ========== Fixtures ==========

@pytest.fixture
def fr():
    server = fakeredis.FakeServer()
    return fakeredis.FakeRedis(server=server, decode_responses=True)


def _make_process(returncode=0):
    """mock subprocess.Popen — stdout이 빈 이터러블"""
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


# ========== TC ==========

def test_stream_output_finally_merge_requested_flag(listener_mod, plan_runner_mod, fr):
    """R(Right): merge_requested 플래그 있으면 _do_inline_merge() 호출"""
    runner_id = "t-stream-aabb"
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_requested", "1")
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:exit_reason", "completed")

    process = _make_process(returncode=0)
    log_handle = _make_log_handle()
    wf_mgr, _ = _make_wf_manager()

    with patch.object(plan_runner_mod, "get_wf_manager", return_value=wf_mgr), \
         patch.object(plan_runner_mod, "get_running_log_files", return_value={}), \
         patch.object(plan_runner_mod, "_do_inline_merge") as mock_merge, \
         patch.object(plan_runner_mod, "_cleanup_process_state") as mock_cleanup, \
         patch.object(plan_runner_mod, "detect_merged_but_not_done", return_value=None):
        listener_mod._stream_output(process, log_handle, fr, runner_id=runner_id)

    mock_merge.assert_called_once_with(runner_id, fr)
    mock_cleanup.assert_not_called()


def test_stream_output_finally_no_merge_flag(listener_mod, plan_runner_mod, fr):
    """R(Right): merge_requested 플래그 없으면 _cleanup_process_state() 호출"""
    runner_id = "t-stream-eeff"
    # 플래그 미설정
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:exit_reason", "completed")

    process = _make_process(returncode=0)
    log_handle = _make_log_handle()
    wf_mgr, _ = _make_wf_manager()

    with patch.object(plan_runner_mod, "get_wf_manager", return_value=wf_mgr), \
         patch.object(plan_runner_mod, "get_running_log_files", return_value={}), \
         patch.object(plan_runner_mod, "_do_inline_merge") as mock_merge, \
         patch.object(plan_runner_mod, "_cleanup_process_state") as mock_cleanup, \
         patch.object(plan_runner_mod, "detect_merged_but_not_done", return_value=None):
        listener_mod._stream_output(process, log_handle, fr, runner_id=runner_id)

    mock_cleanup.assert_called_once_with(runner_id, fr)
    mock_merge.assert_not_called()


def test_stream_output_finally_empty_runner_id(listener_mod, plan_runner_mod, fr):
    """B(Boundary): runner_id='' 이면 merge 없이 cleanup만 호출"""
    process = _make_process(returncode=0)
    log_handle = _make_log_handle()

    with patch.object(plan_runner_mod, "get_wf_manager", return_value=None), \
         patch.object(plan_runner_mod, "get_running_log_files", return_value={}), \
         patch.object(plan_runner_mod, "_do_inline_merge") as mock_merge, \
         patch.object(plan_runner_mod, "_cleanup_process_state") as mock_cleanup, \
         patch.object(plan_runner_mod, "detect_merged_but_not_done", return_value=None):
        listener_mod._stream_output(process, log_handle, fr, runner_id="")

    mock_cleanup.assert_called_once_with("", fr)
    mock_merge.assert_not_called()


def test_stream_output_finally_nonzero_exit(listener_mod, plan_runner_mod, fr):
    """B(Boundary): exit_code=1 이면 workflow failed + cleanup 호출"""
    runner_id = "t-stream-dead"
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_requested", "1")  # 플래그 있어도 머지 안 됨

    process = _make_process(returncode=1)
    log_handle = _make_log_handle()
    wf_mgr, wf = _make_wf_manager()

    with patch.object(plan_runner_mod, "get_wf_manager", return_value=wf_mgr), \
         patch.object(plan_runner_mod, "get_running_log_files", return_value={}), \
         patch.object(plan_runner_mod, "_do_inline_merge") as mock_merge, \
         patch.object(plan_runner_mod, "_cleanup_process_state") as mock_cleanup, \
         patch.object(plan_runner_mod, "detect_merged_but_not_done", return_value=None):
        listener_mod._stream_output(process, log_handle, fr, runner_id=runner_id)

    wf_mgr.update_status.assert_called_with(
        wf["id"],
        "failed",
        error_message="exit_code=1; exit_reason=error",
    )
    mock_cleanup.assert_called_once_with(runner_id, fr)
    mock_merge.assert_not_called()


def test_stream_output_finally_redis_error(listener_mod, plan_runner_mod, fr):
    """E(Error): Redis get 실패 시 warning 로그 출력 후 cleanup fallback"""
    runner_id = "t-stream-cafe"

    process = _make_process(returncode=0)
    log_handle = _make_log_handle()
    wf_mgr, _ = _make_wf_manager()

    broken_redis = MagicMock()
    broken_redis.get.side_effect = Exception("Connection refused")

    with patch.object(plan_runner_mod, "get_wf_manager", return_value=wf_mgr), \
         patch.object(plan_runner_mod, "get_running_log_files", return_value={}), \
         patch.object(plan_runner_mod, "_do_inline_merge") as mock_merge, \
         patch.object(plan_runner_mod, "_cleanup_process_state") as mock_cleanup, \
         patch.object(plan_runner_mod, "detect_merged_but_not_done", return_value=None), \
         patch.object(plan_runner_mod, "logger") as mock_logger:
        listener_mod._stream_output(process, log_handle, broken_redis, runner_id=runner_id)

    # warning 로그 출력 확인
    warning_calls = [str(c) for c in mock_logger.warning.call_args_list]
    assert any("merge_requested 플래그 조회 실패" in c for c in warning_calls), \
        f"경고 로그 미출력. calls={warning_calls}"
    # Redis 오류 → merge 실패 → cleanup fallback
    mock_cleanup.assert_called_once_with(runner_id, broken_redis)
    mock_merge.assert_not_called()


def test_stream_output_workflow_status_no_merge(listener_mod, plan_runner_mod, fr):
    """R(Right): merge_requested 없는 정상 종료 시 workflow status=completed"""
    runner_id = "t-stream-1122"
    # 플래그 미설정
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:exit_reason", "completed")

    process = _make_process(returncode=0)
    log_handle = _make_log_handle()
    wf_mgr, wf = _make_wf_manager()

    with patch.object(plan_runner_mod, "get_wf_manager", return_value=wf_mgr), \
         patch.object(plan_runner_mod, "get_running_log_files", return_value={}), \
         patch.object(plan_runner_mod, "_do_inline_merge"), \
         patch.object(plan_runner_mod, "_cleanup_process_state"), \
         patch.object(plan_runner_mod, "detect_merged_but_not_done", return_value=None):
        listener_mod._stream_output(process, log_handle, fr, runner_id=runner_id)

    wf_mgr.update_status.assert_called_with(wf["id"], "completed")


def test_stream_output_sets_pre_merge_status(listener_mod, plan_runner_mod, fr):
    """R(Right): merge_requested=1 + exit_code=0 시 인라인 merge가 상태 전이를 담당"""
    runner_id = "t-premrg-aabb"
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_requested", "1")
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:exit_reason", "completed")

    process = _make_process(returncode=0)
    log_handle = _make_log_handle()

    with patch.object(plan_runner_mod, "get_wf_manager", return_value=None), \
         patch.object(plan_runner_mod, "get_running_log_files", return_value={}), \
         patch.object(plan_runner_mod, "_do_inline_merge") as mock_merge, \
         patch.object(plan_runner_mod, "_cleanup_process_state"), \
         patch.object(plan_runner_mod, "detect_merged_but_not_done", return_value=None):
        listener_mod._stream_output(process, log_handle, fr, runner_id=runner_id)

    mock_merge.assert_called_once_with(runner_id, fr)
    merge_status = fr.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status")
    assert merge_status is None, f"merge_status는 _stream_output에서 직접 세팅하지 않아야 함, 실제: {merge_status!r}"


def test_stream_output_no_pre_merge_when_no_flag(listener_mod, plan_runner_mod, fr):
    """B(Boundary): merge_requested 없음 + exit_code=0 → merge_status 설정 안 됨 (Fix 4)"""
    runner_id = "t-premrg-ccdd"
    # merge_requested 미설정

    process = _make_process(returncode=0)
    log_handle = _make_log_handle()

    with patch.object(plan_runner_mod, "get_wf_manager", return_value=None), \
         patch.object(plan_runner_mod, "get_running_log_files", return_value={}), \
         patch.object(plan_runner_mod, "_do_inline_merge"), \
         patch.object(plan_runner_mod, "_cleanup_process_state"), \
         patch.object(plan_runner_mod, "detect_merged_but_not_done", return_value=None):
        listener_mod._stream_output(process, log_handle, fr, runner_id=runner_id)

    merge_status = fr.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status")
    assert merge_status is None, f"merge_status가 설정되지 않아야 함, 실제: {merge_status!r}"


def test_cleanup_preserves_worktree_when_merge_requested(listener_mod, process_utils_mod, fr):
    """R(Right): 구현중 plan이면 _cleanup_process_state가 worktree 삭제 안 함"""
    runner_id = "t-clnup-aabb"
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_requested", "1")
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file", "docs/plan/test.md")

    mock_wt = MagicMock()
    with patch.object(process_utils_mod, "get_running_processes", return_value={}), \
         patch.object(process_utils_mod, "get_running_log_files", return_value={}), \
         patch.object(process_utils_mod, "get_stream_threads", return_value={}), \
         patch.object(process_utils_mod, "get_cleanup_done", return_value={}), \
         patch.object(process_utils_mod, "get_dead_process_first_seen", return_value={}), \
         patch.object(process_utils_mod, "get_wf_manager", return_value=None), \
         patch("plan_worktree_helpers.is_plan_in_progress", return_value=True), \
         patch("worktree_manager.WorktreeManager", mock_wt):
        process_utils_mod._cleanup_process_state(runner_id, fr, reason="test")

    mock_wt.remove.assert_not_called(), "merge_requested 있을 때 worktree 삭제 금지"


def test_cleanup_allows_worktree_removal_without_merge_signal(listener_mod, fr):
    """E(Error): merge_requested 없고 merge_status 없음 → WorktreeManager.remove 호출됨 (기존 동작)"""
    runner_id = "t-clnup-eeff"
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file", "docs/plan/test.md")
    # merge_requested/merge_status 미설정

    mock_wt = MagicMock()
    import sys
    process_utils_mod = sys.modules["_dr_process_utils"]
    with patch.object(process_utils_mod, "get_running_processes", return_value={}), \
         patch.object(process_utils_mod, "get_running_log_files", return_value={}), \
         patch.object(process_utils_mod, "get_stream_threads", return_value={}), \
         patch.object(process_utils_mod, "get_cleanup_done", return_value={}), \
         patch.object(process_utils_mod, "get_dead_process_first_seen", return_value={}), \
         patch.object(process_utils_mod, "get_wf_manager", return_value=None), \
         patch("plan_worktree_helpers.is_plan_in_progress", return_value=False), \
         patch("worktree_manager.WorktreeManager", mock_wt):
        process_utils_mod._cleanup_process_state(runner_id, fr, reason="test")

    mock_wt.remove.assert_called_once(), "merge 시그널 없으면 WorktreeManager.remove 호출되어야 함"


def test_cleanup_publishes_completed_after_status_stopped(process_utils_mod, fr):
    """R(Right): _cleanup_process_state는 status=stopped 반영 후 __COMPLETED를 publish한다."""
    runner_id = "t-clnup-order-001"
    status_key = f"{RUNNER_KEY_PREFIX}:{runner_id}:status"
    exit_reason_key = f"{RUNNER_KEY_PREFIX}:{runner_id}:exit_reason"
    log_channel = f"plan-runner:logs:{runner_id}"

    fr.set(status_key, "running")
    fr.set(exit_reason_key, "error")
    fr.sadd("plan-runner:active_runners", runner_id)

    ordered_events = []
    original_set = fr.set
    original_publish = fr.publish

    def _set_spy(key, value, *args, **kwargs):
        if key == status_key and value == "stopped":
            ordered_events.append("status_stopped")
        return original_set(key, value, *args, **kwargs)

    def _publish_spy(channel, message, *args, **kwargs):
        if channel == log_channel and str(message).startswith("__COMPLETED::"):
            ordered_events.append("completed_publish")
        return original_publish(channel, message, *args, **kwargs)

    mock_wt = MagicMock()
    with patch.object(process_utils_mod, "get_running_processes", return_value={}), \
         patch.object(process_utils_mod, "get_running_log_files", return_value={}), \
         patch.object(process_utils_mod, "get_stream_threads", return_value={}), \
         patch.object(process_utils_mod, "get_cleanup_done", return_value={}), \
         patch.object(process_utils_mod, "get_dead_process_first_seen", return_value={}), \
         patch.object(process_utils_mod, "get_wf_manager", return_value=None), \
         patch("plan_worktree_helpers.is_plan_in_progress", return_value=False), \
         patch("worktree_manager.WorktreeManager", mock_wt), \
         patch.object(fr, "set", side_effect=_set_spy), \
         patch.object(fr, "publish", side_effect=_publish_spy):
        process_utils_mod._cleanup_process_state(runner_id, fr, reason="test")

    assert "status_stopped" in ordered_events, f"status=stopped 반영 누락: {ordered_events}"
    assert "completed_publish" in ordered_events, f"completed publish 누락: {ordered_events}"
    assert ordered_events.index("status_stopped") < ordered_events.index("completed_publish"), (
        f"완료 신호가 상태 반영보다 먼저 publish됨: {ordered_events}"
    )
