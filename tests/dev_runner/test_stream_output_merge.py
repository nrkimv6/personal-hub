"""_stream_output finally 머지 분기 TC

대상 소스: scripts/dev-runner-command-listener.py
수정 내용: merge_requested 플래그 확인 1회 통합 + 로그 강화 + workflow 상태 분기 수정
"""

import importlib.util
import io
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
import fakeredis


# ========== 모듈 로드 ==========

_listener_mod = None


def _get_listener():
    global _listener_mod
    if _listener_mod is not None:
        return _listener_mod
    script_path = Path("D:/work/project/tools/monitor-page/scripts/dev-runner-command-listener.py")
    if not script_path.exists():
        pytest.skip(f"Listener script not found: {script_path}")
    spec = importlib.util.spec_from_file_location("dev_runner_command_listener", str(script_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _listener_mod = mod
    return mod


@pytest.fixture(scope="module")
def listener_mod():
    return _get_listener()


# ========== Fixtures ==========

@pytest.fixture
def fr():
    server = fakeredis.FakeServer()
    return fakeredis.FakeRedis(server=server, decode_responses=True)


def _make_process(returncode=0):
    """mock subprocess.Popen — stdout이 빈 이터러블"""
    p = MagicMock()
    p.stdout = iter([])
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

def test_stream_output_finally_merge_requested_flag(listener_mod, fr):
    """R(Right): merge_requested 플래그 있으면 _do_inline_merge() 호출"""
    runner_id = "t-stream-aabb"
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_requested", "1")

    process = _make_process(returncode=0)
    log_handle = _make_log_handle()
    wf_mgr, _ = _make_wf_manager()

    with patch.object(listener_mod, "_wf_manager", wf_mgr), \
         patch.object(listener_mod, "_do_inline_merge") as mock_merge, \
         patch.object(listener_mod, "_cleanup_process_state") as mock_cleanup, \
         patch.object(listener_mod, "_running_log_files", {}):
        listener_mod._stream_output(process, log_handle, fr, runner_id=runner_id)

    mock_merge.assert_called_once_with(runner_id, fr)
    mock_cleanup.assert_not_called()


def test_stream_output_finally_no_merge_flag(listener_mod, fr):
    """R(Right): merge_requested 플래그 없으면 _cleanup_process_state() 호출"""
    runner_id = "t-stream-eeff"
    # 플래그 미설정

    process = _make_process(returncode=0)
    log_handle = _make_log_handle()
    wf_mgr, _ = _make_wf_manager()

    with patch.object(listener_mod, "_wf_manager", wf_mgr), \
         patch.object(listener_mod, "_do_inline_merge") as mock_merge, \
         patch.object(listener_mod, "_cleanup_process_state") as mock_cleanup, \
         patch.object(listener_mod, "_running_log_files", {}):
        listener_mod._stream_output(process, log_handle, fr, runner_id=runner_id)

    mock_cleanup.assert_called_once_with(runner_id, fr)
    mock_merge.assert_not_called()


def test_stream_output_finally_empty_runner_id(listener_mod, fr):
    """B(Boundary): runner_id='' 이면 merge 없이 cleanup만 호출"""
    process = _make_process(returncode=0)
    log_handle = _make_log_handle()

    with patch.object(listener_mod, "_wf_manager", None), \
         patch.object(listener_mod, "_do_inline_merge") as mock_merge, \
         patch.object(listener_mod, "_cleanup_process_state") as mock_cleanup, \
         patch.object(listener_mod, "_running_log_files", {}):
        listener_mod._stream_output(process, log_handle, fr, runner_id="")

    mock_cleanup.assert_called_once_with("", fr)
    mock_merge.assert_not_called()


def test_stream_output_finally_nonzero_exit(listener_mod, fr):
    """B(Boundary): exit_code=1 이면 workflow failed + cleanup 호출"""
    runner_id = "t-stream-dead"
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_requested", "1")  # 플래그 있어도 머지 안 됨

    process = _make_process(returncode=1)
    log_handle = _make_log_handle()
    wf_mgr, wf = _make_wf_manager()

    with patch.object(listener_mod, "_wf_manager", wf_mgr), \
         patch.object(listener_mod, "_do_inline_merge") as mock_merge, \
         patch.object(listener_mod, "_cleanup_process_state") as mock_cleanup, \
         patch.object(listener_mod, "_running_log_files", {}):
        listener_mod._stream_output(process, log_handle, fr, runner_id=runner_id)

    wf_mgr.update_status.assert_called_with(wf["id"], "failed", error_message="Process exited with code 1")
    mock_cleanup.assert_called_once_with(runner_id, fr)
    mock_merge.assert_not_called()


def test_stream_output_finally_redis_error(listener_mod, fr):
    """E(Error): Redis get 실패 시 warning 로그 출력 후 cleanup fallback"""
    runner_id = "t-stream-cafe"

    process = _make_process(returncode=0)
    log_handle = _make_log_handle()
    wf_mgr, _ = _make_wf_manager()

    broken_redis = MagicMock()
    broken_redis.get.side_effect = Exception("Connection refused")

    with patch.object(listener_mod, "_wf_manager", wf_mgr), \
         patch.object(listener_mod, "_do_inline_merge") as mock_merge, \
         patch.object(listener_mod, "_cleanup_process_state") as mock_cleanup, \
         patch.object(listener_mod, "_running_log_files", {}), \
         patch.object(listener_mod, "logger") as mock_logger:
        listener_mod._stream_output(process, log_handle, broken_redis, runner_id=runner_id)

    # warning 로그 출력 확인
    warning_calls = [str(c) for c in mock_logger.warning.call_args_list]
    assert any("merge_requested 플래그 조회 실패" in c for c in warning_calls), \
        f"경고 로그 미출력. calls={warning_calls}"
    # Redis 오류 → merge 실패 → cleanup fallback
    mock_cleanup.assert_called_once_with(runner_id, broken_redis)
    mock_merge.assert_not_called()


def test_stream_output_workflow_status_no_merge(listener_mod, fr):
    """R(Right): merge_requested 없는 정상 종료 시 workflow status=completed"""
    runner_id = "t-stream-1122"
    # 플래그 미설정

    process = _make_process(returncode=0)
    log_handle = _make_log_handle()
    wf_mgr, wf = _make_wf_manager()

    with patch.object(listener_mod, "_wf_manager", wf_mgr), \
         patch.object(listener_mod, "_do_inline_merge"), \
         patch.object(listener_mod, "_cleanup_process_state"), \
         patch.object(listener_mod, "_running_log_files", {}):
        listener_mod._stream_output(process, log_handle, fr, runner_id=runner_id)

    wf_mgr.update_status.assert_called_with(wf["id"], "completed")
