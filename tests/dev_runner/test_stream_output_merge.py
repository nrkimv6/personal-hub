"""_stream_output finally 머지 분기 TC

대상 소스: scripts/dev-runner-command-listener.py
수정 내용: merge_requested 플래그 확인 1회 통합 + 로그 강화 + workflow 상태 분기 수정
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
def stream_output_mod(listener_mod):
    """_stream_output 실제 구현 모듈 — _dr_stream_output에서 get_wf_manager 등 패치 시 사용"""
    import sys

    return sys.modules["_dr_stream_output"]


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


def _strict_redis_mock() -> MagicMock:
    return make_strict_redis_mock()


# ========== TC ==========

def test_stream_output_finally_merge_requested_flag(listener_mod, plan_runner_mod, stream_cleanup_mod, stream_output_mod, fr):
    """R(Right): merge_requested 플래그 있으면 _do_inline_merge() 호출"""
    runner_id = "t-stream-aabb"
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_requested", "1")
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:exit_reason", "completed")

    process = _make_process(returncode=0)
    log_handle = _make_log_handle()
    wf_mgr, _ = _make_wf_manager()

    with patch.object(stream_output_mod, "get_wf_manager", return_value=wf_mgr), \
         patch.object(stream_output_mod, "get_running_log_files", return_value={}), \
         patch.object(stream_cleanup_mod, "_do_inline_merge") as mock_merge, \
         patch.object(stream_cleanup_mod, "_cleanup_process_state") as mock_cleanup, \
         patch.object(stream_cleanup_mod, "detect_merged_but_not_done", return_value=None):
        listener_mod._stream_output(process, log_handle, fr, runner_id=runner_id)

    mock_merge.assert_called_once_with(runner_id, fr)
    mock_cleanup.assert_not_called()


def test_stream_output_finally_no_merge_flag(listener_mod, plan_runner_mod, stream_cleanup_mod, stream_output_mod, fr):
    """R(Right): merge_requested 플래그 없으면 _cleanup_process_state() 호출"""
    runner_id = "t-stream-eeff"
    # 플래그 미설정
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:exit_reason", "completed")

    process = _make_process(returncode=0)
    log_handle = _make_log_handle()
    wf_mgr, _ = _make_wf_manager()

    with patch.object(stream_output_mod, "get_wf_manager", return_value=wf_mgr), \
         patch.object(stream_output_mod, "get_running_log_files", return_value={}), \
         patch.object(stream_cleanup_mod, "_do_inline_merge") as mock_merge, \
         patch.object(stream_cleanup_mod, "_cleanup_process_state") as mock_cleanup, \
         patch.object(stream_cleanup_mod, "detect_merged_but_not_done", return_value=None):
        listener_mod._stream_output(process, log_handle, fr, runner_id=runner_id)

    mock_cleanup.assert_called_once_with(runner_id, fr)
    mock_merge.assert_not_called()


def test_stream_output_finally_empty_runner_id(listener_mod, plan_runner_mod, stream_cleanup_mod, stream_output_mod, fr):
    """B(Boundary): runner_id='' 이면 merge 없이 cleanup만 호출"""
    process = _make_process(returncode=0)
    log_handle = _make_log_handle()

    with patch.object(stream_output_mod, "get_wf_manager", return_value=None), \
         patch.object(stream_output_mod, "get_running_log_files", return_value={}), \
         patch.object(stream_cleanup_mod, "_do_inline_merge") as mock_merge, \
         patch.object(stream_cleanup_mod, "_cleanup_process_state") as mock_cleanup, \
         patch.object(stream_cleanup_mod, "detect_merged_but_not_done", return_value=None):
        listener_mod._stream_output(process, log_handle, fr, runner_id="")

    mock_cleanup.assert_called_once_with("", fr)
    mock_merge.assert_not_called()


def test_stream_output_finally_nonzero_exit(listener_mod, plan_runner_mod, stream_cleanup_mod, stream_output_mod, fr):
    """B(Boundary): exit_code=1 이면 workflow failed + cleanup 호출"""
    runner_id = "t-stream-dead"
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_requested", "1")  # 플래그 있어도 머지 안 됨

    process = _make_process(returncode=1)
    log_handle = _make_log_handle()
    wf_mgr, wf = _make_wf_manager()

    with patch.object(stream_output_mod, "get_wf_manager", return_value=wf_mgr), \
         patch.object(stream_output_mod, "get_running_log_files", return_value={}), \
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


def test_stream_output_finally_redis_error(listener_mod, plan_runner_mod, stream_cleanup_mod, stream_output_mod, fr):
    """E(Error): Redis get 실패 시 warning 로그 출력 후 cleanup fallback"""
    runner_id = "t-stream-cafe"

    process = _make_process(returncode=0)
    log_handle = _make_log_handle()
    wf_mgr, _ = _make_wf_manager()

    broken_redis = _strict_redis_mock()
    broken_redis.get.side_effect = Exception("Connection refused")

    with patch.object(stream_output_mod, "get_wf_manager", return_value=wf_mgr), \
         patch.object(stream_output_mod, "get_running_log_files", return_value={}), \
         patch.object(stream_cleanup_mod, "_do_inline_merge") as mock_merge, \
         patch.object(stream_cleanup_mod, "_cleanup_process_state") as mock_cleanup, \
         patch.object(stream_cleanup_mod, "detect_merged_but_not_done", return_value=None), \
         patch.object(stream_cleanup_mod, "logger") as mock_logger:
        listener_mod._stream_output(process, log_handle, broken_redis, runner_id=runner_id)

    # warning 로그 출력 확인
    warning_calls = [str(c) for c in mock_logger.warning.call_args_list]
    assert any("merge_requested 플래그 조회 실패" in c for c in warning_calls), \
        f"경고 로그 미출력. calls={warning_calls}"
    # Redis 오류 → merge 실패 → cleanup fallback
    mock_cleanup.assert_called_once_with(runner_id, broken_redis)
    mock_merge.assert_not_called()


def test_stream_output_merge_strict_redis_default_none_B():
    """B(Boundary): shared strict helper는 merge_requested 기본값을 None으로 고정한다."""
    mock_redis = _strict_redis_mock()
    value = mock_redis.get(f"{RUNNER_KEY_PREFIX}:strict-check:merge_requested")
    assert_no_magicmock_leak(value, "redis.get")
    assert value is None


def test_stream_output_workflow_status_no_merge(listener_mod, plan_runner_mod, stream_cleanup_mod, stream_output_mod, fr):
    """R(Right): merge_requested 없는 정상 종료 시 workflow status=completed"""
    runner_id = "t-stream-1122"
    # 플래그 미설정
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:exit_reason", "completed")

    process = _make_process(returncode=0)
    log_handle = _make_log_handle()
    wf_mgr, wf = _make_wf_manager()

    with patch.object(stream_output_mod, "get_wf_manager", return_value=wf_mgr), \
         patch.object(stream_output_mod, "get_running_log_files", return_value={}), \
         patch.object(stream_cleanup_mod, "_do_inline_merge"), \
         patch.object(stream_cleanup_mod, "_cleanup_process_state"), \
         patch.object(stream_cleanup_mod, "detect_merged_but_not_done", return_value=None):
        listener_mod._stream_output(process, log_handle, fr, runner_id=runner_id)

    wf_mgr.update_status.assert_called_with(wf["id"], "completed")


def test_stream_output_sets_pre_merge_status(listener_mod, plan_runner_mod, stream_cleanup_mod, stream_output_mod, fr):
    """R(Right): merge_requested=1 + exit_code=0 시 인라인 merge가 상태 전이를 담당"""
    runner_id = "t-premrg-aabb"
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_requested", "1")
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:exit_reason", "completed")

    process = _make_process(returncode=0)
    log_handle = _make_log_handle()

    with patch.object(stream_output_mod, "get_wf_manager", return_value=None), \
         patch.object(stream_output_mod, "get_running_log_files", return_value={}), \
         patch.object(stream_cleanup_mod, "_do_inline_merge") as mock_merge, \
         patch.object(stream_cleanup_mod, "_cleanup_process_state"), \
         patch.object(stream_cleanup_mod, "detect_merged_but_not_done", return_value=None):
        listener_mod._stream_output(process, log_handle, fr, runner_id=runner_id)

    mock_merge.assert_called_once_with(runner_id, fr)
    merge_status = fr.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status")
    assert merge_status is None, f"merge_status는 _stream_output에서 직접 세팅하지 않아야 함, 실제: {merge_status!r}"


def test_stream_output_no_pre_merge_when_no_flag(listener_mod, plan_runner_mod, stream_cleanup_mod, stream_output_mod, fr):
    """B(Boundary): merge_requested 없음 + exit_code=0 → merge_status 설정 안 됨 (Fix 4)"""
    runner_id = "t-premrg-ccdd"
    # merge_requested 미설정

    process = _make_process(returncode=0)
    log_handle = _make_log_handle()

    with patch.object(stream_output_mod, "get_wf_manager", return_value=None), \
         patch.object(stream_output_mod, "get_running_log_files", return_value={}), \
         patch.object(stream_cleanup_mod, "_do_inline_merge"), \
         patch.object(stream_cleanup_mod, "_cleanup_process_state"), \
         patch.object(stream_cleanup_mod, "detect_merged_but_not_done", return_value=None):
        listener_mod._stream_output(process, log_handle, fr, runner_id=runner_id)

    merge_status = fr.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status")
    assert merge_status is None, f"merge_status가 설정되지 않아야 함, 실제: {merge_status!r}"


def test_cleanup_preserves_worktree_when_merge_requested(listener_mod, process_utils_mod, fr):
    """R(Right): 구현중 plan이면 _cleanup_process_state가 worktree 삭제 안 함"""
    runner_id = "t-clnup-aabb"
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_requested", "1")
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file", "docs/plan/test.md")

    # trigger="user" 설정: 미설정 시 invisible runner로 판단해 plan_file 키가 삭제됨
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:trigger", "user")
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


# ========== 신규 TC: 에러 가시성 + merge 판정 로그 레벨 ==========

def test_error_exit_no_stdout_publishes_failure_message(listener_mod, plan_runner_mod, stream_cleanup_mod, stream_output_mod, fr):
    """R(Right): stdout 없는 에러 종료 → [ERROR] _failure_message 채널 publish"""
    runner_id = "t-err-vis-001"
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:exit_reason", "error")

    process = _make_process(returncode=15)
    log_handle = _make_log_handle()
    wf_mgr, _ = _make_wf_manager()

    published_messages = []

    with patch.object(stream_output_mod, "get_wf_manager", return_value=wf_mgr), \
         patch.object(stream_output_mod, "get_running_log_files", return_value={}), \
         patch.object(stream_cleanup_mod, "_do_inline_merge"), \
         patch.object(stream_cleanup_mod, "_cleanup_process_state"), \
         patch.object(stream_cleanup_mod, "detect_merged_but_not_done", return_value=None), \
         patch.object(stream_cleanup_mod, "_pick_error_detail_line", return_value=None), \
         patch.object(stream_cleanup_mod, "_load_log_tail_lines", return_value=[]), \
         patch.object(stream_cleanup_mod, "_publish_with_retry", side_effect=lambda rc, ch, msg: published_messages.append(msg) or True):
        listener_mod._stream_output(process, log_handle, fr, runner_id=runner_id)

    error_msgs = [m for m in published_messages if m.startswith("[ERROR]")]
    assert error_msgs, f"[ERROR] 메시지가 채널에 발행되지 않음. published={published_messages}"
    assert any("exit_code=15" in m for m in error_msgs), \
        f"exit_code=15 포함 [ERROR] 메시지 없음. error_msgs={error_msgs}"


def test_error_exit_with_detail_publishes_detail(listener_mod, plan_runner_mod, stream_cleanup_mod, stream_output_mod, fr):
    """R(Right): stdout에 에러 힌트 있음 → 기존대로 [ERROR] {_error_detail} publish (회귀 방지)"""
    runner_id = "t-err-vis-002"
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:exit_reason", "error")

    process = _make_process(returncode=1)
    log_handle = _make_log_handle()
    wf_mgr, _ = _make_wf_manager()

    published_messages = []

    with patch.object(stream_output_mod, "get_wf_manager", return_value=wf_mgr), \
         patch.object(stream_output_mod, "get_running_log_files", return_value={}), \
         patch.object(stream_cleanup_mod, "_do_inline_merge"), \
         patch.object(stream_cleanup_mod, "_cleanup_process_state"), \
         patch.object(stream_cleanup_mod, "detect_merged_but_not_done", return_value=None), \
         patch.object(stream_cleanup_mod, "_pick_error_detail_line", return_value="SomeError: details"), \
         patch.object(stream_cleanup_mod, "_load_log_tail_lines", return_value=["SomeError: details"]), \
         patch.object(stream_cleanup_mod, "_publish_with_retry", side_effect=lambda rc, ch, msg: published_messages.append(msg) or True):
        listener_mod._stream_output(process, log_handle, fr, runner_id=runner_id)

    error_msgs = [m for m in published_messages if m.startswith("[ERROR]")]
    assert any("SomeError: details" in m for m in error_msgs), \
        f"[ERROR] SomeError: details 메시지 없음. error_msgs={error_msgs}"
    # _failure_message 포맷이 아닌 _error_detail 원문이 publish되어야 함
    assert not any("exit_code=" in m and "SomeError" not in m for m in error_msgs), \
        f"_failure_message 포맷이 잘못 publish됨: {error_msgs}"


def test_no_merge_flag_uses_debug_log(listener_mod, plan_runner_mod, stream_cleanup_mod, stream_output_mod, fr):
    """R(Right): merge_requested 키 없음 → CLEANUP 채널에 'merge 분기 판정' 미출력"""
    runner_id = "t-merge-log-001"
    # merge_requested 키 미세팅

    process = _make_process(returncode=15)
    log_handle = _make_log_handle()
    wf_mgr, _ = _make_wf_manager()

    pub_and_log_calls = []

    with patch.object(stream_output_mod, "get_wf_manager", return_value=wf_mgr), \
         patch.object(stream_output_mod, "get_running_log_files", return_value={}), \
         patch.object(stream_cleanup_mod, "_do_inline_merge"), \
         patch.object(stream_cleanup_mod, "_cleanup_process_state"), \
         patch.object(stream_cleanup_mod, "detect_merged_but_not_done", return_value=None), \
         patch.object(stream_cleanup_mod, "_pub_and_log", side_effect=lambda rid, msg, rc, tag: pub_and_log_calls.append(msg)), \
         patch.object(stream_cleanup_mod, "logger") as mock_logger:
        listener_mod._stream_output(process, log_handle, fr, runner_id=runner_id)

    # _pub_and_log에 "merge 분기 판정" 문자열이 전달되지 않아야 함
    assert not any("merge 분기 판정" in m for m in pub_and_log_calls), \
        f"merge 분기 판정이 CLEANUP 채널에 publish됨: {pub_and_log_calls}"
    # logger.debug에 "merge 분기 판정"이 기록되어야 함
    debug_calls = [str(c) for c in mock_logger.debug.call_args_list]
    assert any("merge 분기 판정" in c for c in debug_calls), \
        f"logger.debug에 merge 분기 판정 미기록. debug_calls={debug_calls}"


def test_merge_flag_exists_publishes_cleanup_log(listener_mod, plan_runner_mod, stream_cleanup_mod, stream_output_mod, fr):
    """R(Right): merge_requested 키 존재 → CLEANUP 채널에 'merge 분기 판정' 출력 유지"""
    runner_id = "t-merge-log-002"
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_requested", "1")
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:exit_reason", "completed")

    process = _make_process(returncode=0)
    log_handle = _make_log_handle()
    wf_mgr, _ = _make_wf_manager()

    pub_and_log_calls = []

    with patch.object(stream_output_mod, "get_wf_manager", return_value=wf_mgr), \
         patch.object(stream_output_mod, "get_running_log_files", return_value={}), \
         patch.object(stream_cleanup_mod, "_do_inline_merge"), \
         patch.object(stream_cleanup_mod, "_cleanup_process_state"), \
         patch.object(stream_cleanup_mod, "detect_merged_but_not_done", return_value=None), \
         patch.object(stream_cleanup_mod, "_pub_and_log", side_effect=lambda rid, msg, rc, tag: pub_and_log_calls.append(msg)):
        listener_mod._stream_output(process, log_handle, fr, runner_id=runner_id)

    assert any("merge 분기 판정" in m for m in pub_and_log_calls), \
        f"merge_requested 있을 때 CLEANUP 채널 미출력. pub_and_log_calls={pub_and_log_calls}"


def test_v2_fallback_runs_without_merge_flag(listener_mod, plan_runner_mod, stream_cleanup_mod, stream_output_mod, fr):
    """B(Boundary): merge_requested 없어도 v2 fallback(detect_merged_but_not_done) 실행"""
    runner_id = "t-v2-fallback-001"
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:exit_reason", "completed")
    # merge_requested 키 미세팅

    process = _make_process(returncode=0)
    log_handle = _make_log_handle()
    wf_mgr, _ = _make_wf_manager()

    with patch.object(stream_output_mod, "get_wf_manager", return_value=wf_mgr), \
         patch.object(stream_output_mod, "get_running_log_files", return_value={}), \
         patch.object(stream_cleanup_mod, "_do_inline_merge") as mock_merge, \
         patch.object(stream_cleanup_mod, "_cleanup_process_state"), \
         patch.object(stream_cleanup_mod, "detect_merged_but_not_done", return_value=None) as mock_detect:
        listener_mod._stream_output(process, log_handle, fr, runner_id=runner_id)

    mock_detect.assert_called_once_with(runner_id, fr)
    mock_merge.assert_not_called()


def test_flag_undefined_on_redis_error_no_name_error(listener_mod, plan_runner_mod, stream_cleanup_mod, stream_output_mod, fr):
    """E(Error): Redis get 실패 시 _flag=None fallback, NameError 없음"""
    runner_id = "t-flag-init-001"

    process = _make_process(returncode=0)
    log_handle = _make_log_handle()
    wf_mgr, _ = _make_wf_manager()

    pub_and_log_calls = []

    broken_redis = _strict_redis_mock()
    broken_redis.get.side_effect = Exception("Connection refused")

    with patch.object(stream_output_mod, "get_wf_manager", return_value=wf_mgr), \
         patch.object(stream_output_mod, "get_running_log_files", return_value={}), \
         patch.object(stream_cleanup_mod, "_do_inline_merge"), \
         patch.object(stream_cleanup_mod, "_cleanup_process_state"), \
         patch.object(stream_cleanup_mod, "detect_merged_but_not_done", return_value=None), \
         patch.object(stream_cleanup_mod, "_pub_and_log", side_effect=lambda rid, msg, rc, tag: pub_and_log_calls.append(msg)):
        # NameError 없이 정상 종료해야 함
        listener_mod._stream_output(process, log_handle, broken_redis, runner_id=runner_id)

    # _flag=None → debug 경로 → _pub_and_log에 "merge 분기 판정" 미전달
    assert not any("merge 분기 판정" in m for m in pub_and_log_calls), \
        f"Redis 오류 시 _flag=None인데 CLEANUP 채널에 merge 분기 판정 publish됨: {pub_and_log_calls}"


def test_completed_exit_with_no_stdout_no_error_publish(listener_mod, plan_runner_mod, stream_cleanup_mod, stream_output_mod, fr):
    """B(Boundary): exit_code=0 + completed → [ERROR] publish 안 함"""
    runner_id = "t-completed-001"
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:exit_reason", "completed")

    process = _make_process(returncode=0)
    log_handle = _make_log_handle()
    wf_mgr, _ = _make_wf_manager()

    published_messages = []

    with patch.object(stream_output_mod, "get_wf_manager", return_value=wf_mgr), \
         patch.object(stream_output_mod, "get_running_log_files", return_value={}), \
         patch.object(stream_cleanup_mod, "_do_inline_merge"), \
         patch.object(stream_cleanup_mod, "_cleanup_process_state"), \
         patch.object(stream_cleanup_mod, "detect_merged_but_not_done", return_value=None), \
         patch.object(stream_cleanup_mod, "_pick_error_detail_line", return_value=None), \
         patch.object(stream_cleanup_mod, "_load_log_tail_lines", return_value=[]), \
         patch.object(stream_cleanup_mod, "_publish_with_retry", side_effect=lambda rc, ch, msg: published_messages.append(msg) or True):
        listener_mod._stream_output(process, log_handle, fr, runner_id=runner_id)

    error_msgs = [m for m in published_messages if m.startswith("[ERROR]")]
    assert not error_msgs, f"completed 종료인데 [ERROR] 메시지가 발행됨: {error_msgs}"


# ========== 신규 TC: exit_code=0 + completed 경로 워크트리 커밋 감지 ==========

def test_auto_merge_on_completed_with_worktree_commits_R_success(listener_mod, plan_runner_mod, stream_cleanup_mod, stream_output_mod, fr):
    """R(Right): exit_code=0 + completed + merge_requested 없음 + 워크트리 커밋 있음 → merge"""
    runner_id = "t-automrg-001"
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:exit_reason", "completed")
    # merge_requested 키 미설정

    process = _make_process(returncode=0)
    log_handle = _make_log_handle()
    wf_mgr, _ = _make_wf_manager()

    with patch.object(stream_output_mod, "get_wf_manager", return_value=wf_mgr), \
         patch.object(stream_output_mod, "get_running_log_files", return_value={}), \
         patch.object(stream_cleanup_mod, "_do_inline_merge") as mock_merge, \
         patch.object(stream_cleanup_mod, "_cleanup_process_state") as mock_cleanup, \
         patch.object(stream_cleanup_mod, "detect_merged_but_not_done", return_value=None), \
         patch.object(stream_cleanup_mod, "_has_worktree_commits", return_value=True):
        listener_mod._stream_output(process, log_handle, fr, runner_id=runner_id)

    mock_merge.assert_called_once_with(runner_id, fr)
    mock_cleanup.assert_not_called()


def test_no_merge_on_completed_without_worktree_commits_B_no_commits(listener_mod, plan_runner_mod, stream_cleanup_mod, stream_output_mod, fr):
    """B(Boundary): exit_code=0 + completed + merge_requested 없음 + 워크트리 커밋 없음 → merge 안 함"""
    runner_id = "t-automrg-002"
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:exit_reason", "completed")

    process = _make_process(returncode=0)
    log_handle = _make_log_handle()
    wf_mgr, _ = _make_wf_manager()

    with patch.object(stream_output_mod, "get_wf_manager", return_value=wf_mgr), \
         patch.object(stream_output_mod, "get_running_log_files", return_value={}), \
         patch.object(stream_cleanup_mod, "_do_inline_merge") as mock_merge, \
         patch.object(stream_cleanup_mod, "_cleanup_process_state") as mock_cleanup, \
         patch.object(stream_cleanup_mod, "detect_merged_but_not_done", return_value=None), \
         patch.object(stream_cleanup_mod, "_has_worktree_commits", return_value=False):
        listener_mod._stream_output(process, log_handle, fr, runner_id=runner_id)

    mock_merge.assert_not_called()
    mock_cleanup.assert_called_once_with(runner_id, fr)


def test_no_merge_on_completed_without_branch_key_B_no_branch(listener_mod, plan_runner_mod, stream_cleanup_mod, stream_output_mod, fr):
    """B(Boundary): exit_code=0 + completed + merge_requested 없음 + branch 키 없음 → merge 안 함"""
    runner_id = "t-automrg-003"
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:exit_reason", "completed")
    # branch 키 미설정 → _has_worktree_commits가 False 반환

    process = _make_process(returncode=0)
    log_handle = _make_log_handle()
    wf_mgr, _ = _make_wf_manager()

    with patch.object(stream_output_mod, "get_wf_manager", return_value=wf_mgr), \
         patch.object(stream_output_mod, "get_running_log_files", return_value={}), \
         patch.object(stream_cleanup_mod, "_do_inline_merge") as mock_merge, \
         patch.object(stream_cleanup_mod, "_cleanup_process_state") as mock_cleanup, \
         patch.object(stream_cleanup_mod, "detect_merged_but_not_done", return_value=None):
        # _has_worktree_commits는 실제 호출 — FakeRedis에 branch 키 없으므로 False 반환
        listener_mod._stream_output(process, log_handle, fr, runner_id=runner_id)

    mock_merge.assert_not_called()
    mock_cleanup.assert_called_once_with(runner_id, fr)


def test_merge_requested_flag_still_takes_precedence_I_flag_override(listener_mod, plan_runner_mod, stream_cleanup_mod, stream_output_mod, fr):
    """I(Inverse): merge_requested=1 플래그 있으면 _has_worktree_commits 호출 없이 merge"""
    runner_id = "t-automrg-004"
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_requested", "1")
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:exit_reason", "completed")

    process = _make_process(returncode=0)
    log_handle = _make_log_handle()
    wf_mgr, _ = _make_wf_manager()

    with patch.object(stream_output_mod, "get_wf_manager", return_value=wf_mgr), \
         patch.object(stream_output_mod, "get_running_log_files", return_value={}), \
         patch.object(stream_cleanup_mod, "_do_inline_merge") as mock_merge, \
         patch.object(stream_cleanup_mod, "_cleanup_process_state"), \
         patch.object(stream_cleanup_mod, "detect_merged_but_not_done", return_value=None), \
         patch.object(stream_cleanup_mod, "_has_worktree_commits") as mock_hwc:
        listener_mod._stream_output(process, log_handle, fr, runner_id=runner_id)

    mock_merge.assert_called_once_with(runner_id, fr)
    # 플래그 경로에서는 _has_worktree_commits 호출 안 함
    mock_hwc.assert_not_called()


# ========== 신규 TC: _has_worktree_commits 단위 테스트 ==========

def test_has_worktree_commits_true_R_success(stream_cleanup_mod, fr):
    """R(Right): branch 키 있고 git log 결과 있으면 True"""
    runner_id = "t-hwc-001"
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:branch", "plan/some-branch")

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="abc1234 feat: impl\ndef5678 fix: test\n", returncode=0)
        result = stream_cleanup_mod._has_worktree_commits(runner_id, fr)

    assert result is True


def test_has_worktree_commits_false_B_no_commits(stream_cleanup_mod, fr):
    """B(Boundary): branch 키 있지만 git log 결과 비어있으면 False"""
    runner_id = "t-hwc-002"
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:branch", "plan/some-branch")

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="", returncode=0)
        result = stream_cleanup_mod._has_worktree_commits(runner_id, fr)

    assert result is False


def test_has_worktree_commits_no_branch_E_missing_branch(stream_cleanup_mod, fr):
    """E(Error): branch 키 없으면 subprocess 호출 없이 False"""
    runner_id = "t-hwc-003"
    # branch 키 미설정

    with patch("subprocess.run") as mock_run:
        result = stream_cleanup_mod._has_worktree_commits(runner_id, fr)

    assert result is False
    mock_run.assert_not_called()


def test_has_worktree_commits_git_error_E_command_fail(stream_cleanup_mod, fr):
    """E(Error): git log 실행 실패(Exception) → False 반환 (안전 기본값)"""
    runner_id = "t-hwc-004"
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:branch", "plan/some-branch")

    with patch("subprocess.run", side_effect=Exception("git not found")):
        result = stream_cleanup_mod._has_worktree_commits(runner_id, fr)

    assert result is False


# ========== Phase T3: 실제 git 기반 통합 TC ==========

@pytest.fixture
def real_git_repo():
    """실제 git 저장소를 임시 디렉토리에 생성하고 경로를 반환한다."""
    with tempfile.TemporaryDirectory() as tmpdir:
        env = {**os.environ, "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "t@t.com",
               "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "t@t.com"}
        # git init
        subprocess.run(["git", "init", "-b", "main"], cwd=tmpdir, capture_output=True, env=env)
        # 최초 커밋 (main)
        dummy = os.path.join(tmpdir, "README.md")
        with open(dummy, "w") as f:
            f.write("init")
        subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True, env=env)
        subprocess.run(["git", "commit", "-m", "init"], cwd=tmpdir, capture_output=True, env=env)
        # feature 브랜치 생성 + 커밋 추가
        subprocess.run(["git", "checkout", "-b", "plan/test-feature"], cwd=tmpdir, capture_output=True, env=env)
        with open(dummy, "a") as f:
            f.write("\nfeature")
        subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True, env=env)
        subprocess.run(["git", "commit", "-m", "feat: add feature"], cwd=tmpdir, capture_output=True, env=env)
        yield tmpdir


def test_completed_flow_triggers_merge_with_real_git(listener_mod, plan_runner_mod, stream_cleanup_mod, stream_output_mod, fr, real_git_repo):
    """T3: 실제 git 저장소로 exit_code=0 + completed + 워크트리 커밋 → _do_inline_merge 호출 검증"""
    runner_id = "t-realgit-001"
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:exit_reason", "completed")
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:branch", "plan/test-feature")
    # merge_requested 키 미설정 (no flag)

    process = _make_process(returncode=0)
    log_handle = _make_log_handle()
    wf_mgr, _ = _make_wf_manager()

    from pathlib import Path
    with patch.object(stream_output_mod, "get_wf_manager", return_value=wf_mgr), \
         patch.object(stream_output_mod, "get_running_log_files", return_value={}), \
         patch.object(stream_cleanup_mod, "_do_inline_merge") as mock_merge, \
         patch.object(stream_cleanup_mod, "_cleanup_process_state"), \
         patch.object(stream_cleanup_mod, "detect_merged_but_not_done", return_value=None), \
         patch("_dr_constants.PROJECT_ROOT", Path(real_git_repo)):
        listener_mod._stream_output(process, log_handle, fr, runner_id=runner_id)

    mock_merge.assert_called_once_with(runner_id, fr), (
        "exit_code=0 + completed + worktree 커밋 존재 → _do_inline_merge 호출되어야 함"
    )


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


# ========== Phase T1: _determine_merge_requested (flag=None 경로) 단위 TC ==========
# 주의: _determine_merge_requested 는 _dr_stream_cleanup 에 정의됨.
# mock 패치 대상은 반드시 stream_cleanup_mod._has_worktree_commits (plan_runner_mod 패치 무효)

@pytest.fixture(scope="module")
def stream_cleanup_mod(listener_mod):
    import sys
    return sys.modules["_dr_stream_cleanup"]


def _make_ctx(stream_cleanup_mod, runner_id, redis_client, exit_code=0, completed_for_flow=True):
    """_StreamCleanupCtx 편의 생성 — log_channel 필수 포함"""
    return stream_cleanup_mod._StreamCleanupCtx(
        runner_id=runner_id,
        redis_client=redis_client,
        log_channel="plan-runner:log",
        exit_code=exit_code,
        exit_reason="completed" if completed_for_flow else "error",
        completed_for_flow=completed_for_flow,
    )


def test_determine_merge_requested_flag_none_exit0_completed_with_commits_R(
    stream_cleanup_mod, fr
):
    """R(Right): flag=None + exit_code=0 + completed_for_flow=True + 워크트리 커밋 있음 → True"""
    runner_id = "t-dmr-001"
    ctx = _make_ctx(stream_cleanup_mod, runner_id, fr, exit_code=0, completed_for_flow=True)
    # merge_requested 키 미설정 (flag=None)

    with patch.object(stream_cleanup_mod, "_has_worktree_commits", return_value=True), \
         patch.object(stream_cleanup_mod, "_pub_and_log"):
        result = stream_cleanup_mod._determine_merge_requested(ctx)

    assert result is True, f"exit_code=0 + completed + 커밋 있음 → True여야 함, 실제: {result}"


def test_determine_merge_requested_flag_none_exit0_completed_no_commits_B(
    stream_cleanup_mod, fr
):
    """B(Boundary): flag=None + exit_code=0 + completed_for_flow=True + 워크트리 커밋 없음 → False"""
    runner_id = "t-dmr-002"
    ctx = _make_ctx(stream_cleanup_mod, runner_id, fr, exit_code=0, completed_for_flow=True)

    with patch.object(stream_cleanup_mod, "_has_worktree_commits", return_value=False), \
         patch.object(stream_cleanup_mod, "_pub_and_log"):
        result = stream_cleanup_mod._determine_merge_requested(ctx)

    assert result is False, f"커밋 없음 → False여야 함, 실제: {result}"


def test_determine_merge_requested_flag_none_exit0_not_completed_B(
    stream_cleanup_mod, fr
):
    """B(Boundary): flag=None + exit_code=0 + completed_for_flow=False → False, 워크트리 체크 호출 안 됨"""
    runner_id = "t-dmr-003"
    ctx = _make_ctx(stream_cleanup_mod, runner_id, fr, exit_code=0, completed_for_flow=False)

    with patch.object(stream_cleanup_mod, "_has_worktree_commits") as mock_hwc, \
         patch.object(stream_cleanup_mod, "_pub_and_log"):
        result = stream_cleanup_mod._determine_merge_requested(ctx)

    assert result is False, f"completed_for_flow=False → False여야 함, 실제: {result}"
    mock_hwc.assert_not_called(), "_has_worktree_commits는 not_completed 경로에서 호출 안 됨"


def test_determine_merge_requested_flag_none_exit_nonzero_B(
    stream_cleanup_mod, fr
):
    """B(Boundary): flag=None + exit_code=1 → False, 워크트리 체크 호출 안 됨"""
    runner_id = "t-dmr-004"
    ctx = _make_ctx(stream_cleanup_mod, runner_id, fr, exit_code=1, completed_for_flow=False)

    with patch.object(stream_cleanup_mod, "_has_worktree_commits") as mock_hwc, \
         patch.object(stream_cleanup_mod, "_pub_and_log"):
        result = stream_cleanup_mod._determine_merge_requested(ctx)

    assert result is False, f"exit_code=1 → False여야 함, 실제: {result}"
    mock_hwc.assert_not_called(), "_has_worktree_commits는 exit_code!=0 경로에서 호출 안 됨"


def test_determine_merge_requested_flag_none_has_worktree_commits_raises_E(
    stream_cleanup_mod, fr
):
    """E(Error): _has_worktree_commits 예외 발생 → False 반환 (안전 기본값, 예외 전파 없음)"""
    runner_id = "t-dmr-005"
    ctx = _make_ctx(stream_cleanup_mod, runner_id, fr, exit_code=0, completed_for_flow=True)

    with patch.object(stream_cleanup_mod, "_has_worktree_commits", side_effect=Exception("git error")), \
         patch.object(stream_cleanup_mod, "_pub_and_log"):
        # 예외가 전파되면 안 됨
        result = stream_cleanup_mod._determine_merge_requested(ctx)

    assert result is False, f"예외 발생 시 안전 기본값 False여야 함, 실제: {result}"


def test_determine_merge_requested_flag_none_runner_id_empty_E(
    stream_cleanup_mod, fr
):
    """E(Error): ctx.runner_id=None → False 반환 (기존 동작 유지 회귀 방지)"""
    ctx = _make_ctx(stream_cleanup_mod, runner_id=None, redis_client=fr, exit_code=0, completed_for_flow=True)

    with patch.object(stream_cleanup_mod, "_has_worktree_commits") as mock_hwc, \
         patch.object(stream_cleanup_mod, "_pub_and_log"):
        result = stream_cleanup_mod._determine_merge_requested(ctx)

    assert result is False, f"runner_id=None → False여야 함, 실제: {result}"
    mock_hwc.assert_not_called(), "runner_id=None이면 _has_worktree_commits 호출 안 됨"
