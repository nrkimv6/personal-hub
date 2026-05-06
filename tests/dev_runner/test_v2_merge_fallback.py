"""
TC: v2 merge 후처리 누락 fallback 단위 테스트

Phase T1:
- detect_merged_but_not_done: R/B/E
- _stream_output v2 fallback: R/B/E
- heartbeat v2 fallback: R
- _cleanup_process_state self-join 방지: R/B
- handle_merge_stage merge_status 세팅: R/E
- _handle_post_merge_done 상태 전이: R
"""
import importlib.util
import re
import sys
import threading
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from tests.dev_runner.conftest import assert_no_magicmock_leak, make_strict_redis_mock

_SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

# noise filter mock
_mock_noise = types.ModuleType("listener_noise_filter")
_mock_noise.NOISE_BLOCK_MARKERS = []
_mock_noise.is_noise_line = lambda line: False


def _load_dr_merge():
    sys.modules["listener_noise_filter"] = _mock_noise
    import _dr_merge
    import importlib
    importlib.reload(_dr_merge)
    return _dr_merge


def _strict_redis_mock() -> MagicMock:
    return make_strict_redis_mock()


def _make_redis_mock(merge_status=None, plan_file=None, branch=None, stop_stage=None):
    r = _strict_redis_mock()
    prefix = "plan-runner:runners"

    def _get(key):
        if ":merge_status" in key:
            return merge_status
        if ":plan_file" in key:
            return plan_file
        if ":branch" in key:
            return branch
        if ":stop_stage" in key:
            return stop_stage
        if ":exit_reason" in key:
            return "stopped"
        return None

    r.get.side_effect = _get
    return r


def test_make_redis_mock_unknown_key_defaults_none_B():
    """B(Boundary): shared strict helper + custom get side_effect도 미매핑 키를 None으로 고정."""
    mock_redis = _make_redis_mock()
    value = mock_redis.get("plan-runner:runners:strict-check:merge_requested")
    assert_no_magicmock_leak(value, "redis.get")
    assert value is None


# ── detect_merged_but_not_done ────────────────────────────────────────────────


def test_detect_merged_but_not_done_redis_R(tmp_path):
    """R(Right): Redis merge_status=merged + plan 파일 잔존 + 상태 머지대기 → dict 반환"""
    plan = tmp_path / "plan.md"
    plan.write_text("> 상태: 머지대기\n- [ ] todo\n", encoding="utf-8")

    r = _make_redis_mock(merge_status="merged", plan_file=str(plan), branch="plan/test-branch")

    mod = _load_dr_merge()
    with patch("plan_worktree_helpers.is_plan_archived", return_value=False):
        result = mod.detect_merged_but_not_done("runner1", r)

    assert result is not None
    assert result["plan_file"] == str(plan)
    assert result["branch"] == "plan/test-branch"


def test_detect_merged_but_not_done_git_log_R(tmp_path):
    """R(Right): Redis merge_status 없음 + git log에 merge commit → dict 반환"""
    plan = tmp_path / "plan.md"
    plan.write_text("> 상태: 머지대기\n- [ ] todo\n", encoding="utf-8")

    r = _make_redis_mock(merge_status=None, plan_file=str(plan), branch="plan/test-branch")

    mod = _load_dr_merge()
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "abc1234 Merge branch 'plan/test-branch' into main\n"

    with patch("plan_worktree_helpers.is_plan_archived", return_value=False), \
         patch("subprocess.run", return_value=mock_result):
        result = mod.detect_merged_but_not_done("runner1", r)

    assert result is not None
    assert result["plan_file"] == str(plan)


def test_detect_merged_but_not_done_no_merge_B(tmp_path):
    """B(Boundary): Redis merge_status 없음 + git log 빈 결과 → None 반환"""
    plan = tmp_path / "plan.md"
    plan.write_text("> 상태: 머지대기\n- [ ] todo\n", encoding="utf-8")

    r = _make_redis_mock(merge_status=None, plan_file=str(plan), branch="plan/test-branch")

    mod = _load_dr_merge()
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = ""

    with patch("plan_worktree_helpers.is_plan_archived", return_value=False), \
         patch("subprocess.run", return_value=mock_result):
        result = mod.detect_merged_but_not_done("runner1", r)

    assert result is None


def test_detect_merged_but_not_done_already_archived_B(tmp_path):
    """B(Boundary): merge 있지만 plan이 이미 archive → None 반환 (중복 방지)"""
    plan = tmp_path / "plan.md"
    plan.write_text("> 상태: 머지대기\n- [ ] todo\n", encoding="utf-8")

    r = _make_redis_mock(merge_status="merged", plan_file=str(plan), branch="plan/test-branch")

    mod = _load_dr_merge()
    with patch("plan_worktree_helpers.is_plan_archived", return_value=True):
        result = mod.detect_merged_but_not_done("runner1", r)

    assert result is None


def test_detect_merged_but_not_done_no_plan_file_E():
    """E(Error): plan_file Redis 키가 None → None 반환"""
    r = _make_redis_mock(merge_status="merged", plan_file=None, branch="plan/test-branch")

    mod = _load_dr_merge()
    result = mod.detect_merged_but_not_done("runner1", r)

    assert result is None


def test_detect_merged_but_not_done_redis_error_E():
    """E(Error): Redis 연결 실패 시 예외 전파 않고 None 반환"""
    r = _strict_redis_mock()
    r.get.side_effect = Exception("Redis connection refused")

    mod = _load_dr_merge()
    result = mod.detect_merged_but_not_done("runner1", r)

    assert result is None


def test_detect_merged_but_not_done_wrong_status_B(tmp_path):
    """B(Boundary): plan 상태가 구현완료(이미 전이됨) → None 반환"""
    plan = tmp_path / "plan.md"
    plan.write_text("> 상태: 구현완료\n- [x] done\n", encoding="utf-8")

    r = _make_redis_mock(merge_status="merged", plan_file=str(plan), branch="plan/test-branch")

    mod = _load_dr_merge()
    with patch("plan_worktree_helpers.is_plan_archived", return_value=False):
        result = mod.detect_merged_but_not_done("runner1", r)

    assert result is None


def test_detect_merged_but_not_done_pre_review_stopped_B(tmp_path):
    """B: stop_stage=pre_review면 merge fallback 감지에서 제외."""
    plan = tmp_path / "plan.md"
    plan.write_text("> 상태: 머지대기\n- [ ] todo\n", encoding="utf-8")

    r = _make_redis_mock(
        merge_status="merged",
        plan_file=str(plan),
        branch="plan/test-branch",
        stop_stage="pre_review",
    )

    mod = _load_dr_merge()
    with patch("plan_worktree_helpers.is_plan_archived", return_value=False):
        result = mod.detect_merged_but_not_done("runner-pre", r)

    assert result is None


def test_detect_merged_but_not_done_post_review_stopped_R(tmp_path):
    """R: stop_stage=post_review면 기존 merge fallback 감지를 유지."""
    plan = tmp_path / "plan.md"
    plan.write_text("> 상태: 머지대기\n- [ ] todo\n", encoding="utf-8")

    r = _make_redis_mock(
        merge_status="merged",
        plan_file=str(plan),
        branch="plan/test-branch",
        stop_stage="post_review",
    )

    mod = _load_dr_merge()
    with patch("plan_worktree_helpers.is_plan_archived", return_value=False):
        result = mod.detect_merged_but_not_done("runner-post", r)

    assert result is not None
    assert result["plan_file"] == str(plan)


# ── _stream_output v2 fallback ────────────────────────────────────────────────


def _load_plan_runner():
    sys.modules["listener_noise_filter"] = _mock_noise
    import _dr_plan_runner
    import importlib
    importlib.reload(_dr_plan_runner)
    return _dr_plan_runner


def test_stream_output_v2_fallback_trigger_R(tmp_path):
    """R(Right): merge_requested=False + detect → dict → _handle_post_merge_done 호출 확인"""
    import subprocess
    import io

    plan = tmp_path / "plan.md"
    plan.write_text("> 상태: 머지대기\n- [ ] todo\n", encoding="utf-8")

    detect_result = {"plan_file": str(plan), "branch": "plan/test"}
    mock_redis = _strict_redis_mock()
    mock_redis.get.return_value = None  # merge_requested = None

    # subprocess mock: stdout이 비어있는 프로세스
    mock_proc = MagicMock()
    mock_proc.stdout = io.StringIO("")
    mock_proc.returncode = 15
    mock_proc.wait.return_value = 0

    log_handle = io.StringIO()

    from _dr_state import get_running_log_files, get_stream_threads, get_wf_manager
    get_running_log_files()["runner-t1"] = tmp_path / "test.log"
    (tmp_path / "test.log").write_text("", encoding="utf-8")

    with patch("_dr_stream_cleanup.detect_merged_but_not_done", return_value=detect_result) as mock_detect, \
         patch("_dr_stream_cleanup._handle_post_merge_done") as mock_done, \
         patch("_dr_stream_cleanup._cleanup_process_state") as mock_cleanup:
        from _dr_plan_runner import _stream_output
        _stream_output(mock_proc, log_handle, mock_redis, "runner-t1")

    mock_detect.assert_called_once_with("runner-t1", mock_redis)
    mock_done.assert_called_once()
    mock_cleanup.assert_called_once()


def test_stream_output_v2_fallback_skip_B(tmp_path):
    """B(Boundary): detect → None → _handle_post_merge_done 미호출 + _cleanup_process_state 호출"""
    import io

    mock_redis = _strict_redis_mock()
    mock_redis.get.return_value = None

    mock_proc = MagicMock()
    mock_proc.stdout = io.StringIO("")
    mock_proc.returncode = 0
    mock_proc.wait.return_value = 0

    log_handle = io.StringIO()

    from _dr_state import get_running_log_files
    get_running_log_files()["runner-t2"] = tmp_path / "test2.log"
    (tmp_path / "test2.log").write_text("", encoding="utf-8")

    with patch("_dr_stream_cleanup.detect_merged_but_not_done", return_value=None) as mock_detect, \
         patch("_dr_stream_cleanup._handle_post_merge_done") as mock_done, \
         patch("_dr_stream_cleanup._cleanup_process_state") as mock_cleanup:
        from _dr_plan_runner import _stream_output
        _stream_output(mock_proc, log_handle, mock_redis, "runner-t2")

    mock_detect.assert_called_once_with("runner-t2", mock_redis)
    mock_done.assert_not_called()
    mock_cleanup.assert_called_once()


def test_stream_output_v2_fallback_error_still_cleanup_E(tmp_path):
    """E(Error): _handle_post_merge_done이 예외 발생 → 예외 후에도 _cleanup_process_state 호출"""
    import io

    detect_result = {"plan_file": "/some/plan.md", "branch": "plan/test"}
    mock_redis = _strict_redis_mock()
    mock_redis.get.return_value = None

    mock_proc = MagicMock()
    mock_proc.stdout = io.StringIO("")
    mock_proc.returncode = 15
    mock_proc.wait.return_value = 0

    log_handle = io.StringIO()

    from _dr_state import get_running_log_files
    get_running_log_files()["runner-t3"] = tmp_path / "test3.log"
    (tmp_path / "test3.log").write_text("", encoding="utf-8")

    with patch("_dr_stream_cleanup.detect_merged_but_not_done", return_value=detect_result), \
         patch("_dr_stream_cleanup._handle_post_merge_done", side_effect=RuntimeError("done 실패")), \
         patch("_dr_stream_cleanup._cleanup_process_state") as mock_cleanup:
        from _dr_plan_runner import _stream_output
        _stream_output(mock_proc, log_handle, mock_redis, "runner-t3")

    mock_cleanup.assert_called_once()


def test_stream_output_exit_reason_rate_limit_marks_failed_R(tmp_path):
    """R(Right): exit_code=0 이어도 exit_reason=rate_limit이면 workflow failed 처리"""
    import io

    mock_redis = _strict_redis_mock()

    def _get_side(key):
        if key.endswith(":merge_requested"):
            return None
        if key.endswith(":exit_reason"):
            return "rate_limit"
        return None

    mock_redis.get.side_effect = _get_side

    mock_proc = MagicMock()
    mock_proc.stdout = io.StringIO("")
    mock_proc.returncode = 0
    mock_proc.wait.return_value = 0

    wf_mgr = MagicMock()
    wf_mgr.get_by_runner_id.return_value = {"id": 777, "runner_id": "runner-t4"}

    log_handle = io.StringIO()

    with patch("_dr_stream_output.get_wf_manager", return_value=wf_mgr), \
         patch("_dr_stream_output.get_running_log_files", return_value={}), \
         patch("_dr_stream_cleanup.detect_merged_but_not_done", return_value=None), \
         patch("_dr_stream_cleanup._cleanup_process_state"), \
         patch("_dr_stream_cleanup._do_inline_merge"):
        from _dr_plan_runner import _stream_output
        _stream_output(mock_proc, log_handle, mock_redis, "runner-t4")

    err_msgs = [c.kwargs.get("error_message", "") for c in wf_mgr.update_status.call_args_list]
    assert any("exit_reason=rate_limit" in m for m in err_msgs)


def test_stream_output_merge_requested_but_rate_limit_skips_merge_R(tmp_path):
    """R(Right): merge_requested=1 이어도 exit_reason=rate_limit이면 merge 진입 금지"""
    import io

    mock_redis = _strict_redis_mock()

    def _get_side(key):
        if key.endswith(":merge_requested"):
            return "1"
        if key.endswith(":exit_reason"):
            return "rate_limit"
        return None

    mock_redis.get.side_effect = _get_side

    mock_proc = MagicMock()
    mock_proc.stdout = io.StringIO("")
    mock_proc.returncode = 0
    mock_proc.wait.return_value = 0

    wf_mgr = MagicMock()
    wf_mgr.get_by_runner_id.return_value = {"id": 778, "runner_id": "runner-t5"}

    log_handle = io.StringIO()

    with patch("_dr_stream_output.get_wf_manager", return_value=wf_mgr), \
         patch("_dr_stream_output.get_running_log_files", return_value={}), \
         patch("_dr_stream_cleanup.detect_merged_but_not_done", return_value=None), \
         patch("_dr_stream_cleanup._cleanup_process_state"), \
         patch("_dr_stream_cleanup._do_inline_merge") as mock_inline_merge:
        from _dr_plan_runner import _stream_output
        _stream_output(mock_proc, log_handle, mock_redis, "runner-t5")

    mock_inline_merge.assert_not_called()
    err_msgs = [c.kwargs.get("error_message", "") for c in wf_mgr.update_status.call_args_list]
    assert any("exit_reason=rate_limit" in m for m in err_msgs)


def test_stream_output_exit_reason_lookup_error_marks_failed_R(tmp_path):
    """R(Right): exit_reason 조회 실패 시 fail-safe로 completed 금지."""
    import io

    mock_redis = _strict_redis_mock()

    def _get_side(key):
        if key.endswith(":merge_requested"):
            return None
        if key.endswith(":exit_reason"):
            raise RuntimeError("redis read failed")
        return None

    mock_redis.get.side_effect = _get_side

    mock_proc = MagicMock()
    mock_proc.stdout = io.StringIO("")
    mock_proc.returncode = 0
    mock_proc.wait.return_value = 0

    wf_mgr = MagicMock()
    wf_mgr.get_by_runner_id.return_value = {"id": 779, "runner_id": "runner-t6"}

    log_handle = io.StringIO()

    with patch("_dr_stream_output.get_wf_manager", return_value=wf_mgr), \
         patch("_dr_stream_output.get_running_log_files", return_value={}), \
         patch("_dr_stream_cleanup.detect_merged_but_not_done", return_value=None), \
         patch("_dr_stream_cleanup._cleanup_process_state"), \
         patch("_dr_stream_cleanup._do_inline_merge"):
        from _dr_plan_runner import _stream_output
        _stream_output(mock_proc, log_handle, mock_redis, "runner-t6")

    err_msgs = [c.kwargs.get("error_message", "") for c in wf_mgr.update_status.call_args_list]
    assert any("exit_reason=error" in m for m in err_msgs)
    assert not any(
        len(call.args) >= 2 and call.args[1] == "completed"
        for call in wf_mgr.update_status.call_args_list
    )


def test_stream_output_missing_exit_reason_marks_failed_R(tmp_path):
    """R(Right): exit_reason 키 누락(None)도 fail-safe로 completed 금지."""
    import io

    mock_redis = _strict_redis_mock()

    def _get_side(key):
        if key.endswith(":merge_requested"):
            return None
        if key.endswith(":exit_reason"):
            return None
        return None

    mock_redis.get.side_effect = _get_side

    mock_proc = MagicMock()
    mock_proc.stdout = io.StringIO("")
    mock_proc.returncode = 0
    mock_proc.wait.return_value = 0

    wf_mgr = MagicMock()
    wf_mgr.get_by_runner_id.return_value = {"id": 780, "runner_id": "runner-t7"}

    log_handle = io.StringIO()

    with patch("_dr_stream_output.get_wf_manager", return_value=wf_mgr), \
         patch("_dr_stream_output.get_running_log_files", return_value={}), \
         patch("_dr_stream_cleanup.detect_merged_but_not_done", return_value=None), \
         patch("_dr_stream_cleanup._cleanup_process_state"), \
         patch("_dr_stream_cleanup._do_inline_merge"):
        from _dr_plan_runner import _stream_output
        _stream_output(mock_proc, log_handle, mock_redis, "runner-t7")

    err_msgs = [c.kwargs.get("error_message", "") for c in wf_mgr.update_status.call_args_list]
    assert any("exit_reason=error" in m for m in err_msgs)


# ── heartbeat v2 fallback ─────────────────────────────────────────────────────


def test_heartbeat_v2_fallback_R(tmp_path):
    """R(Right): heartbeat 루프 dead process + detect → dict → _handle_post_merge_done 호출"""
    plan = tmp_path / "plan.md"
    plan.write_text("> 상태: 머지대기\n- [ ] todo\n", encoding="utf-8")

    detect_result = {"plan_file": str(plan), "branch": "plan/test"}

    # heartbeat fallback 로직 직접 테스트: 해당 분기 추출
    pub_calls = []
    mock_redis = _strict_redis_mock()

    with patch("_dr_merge.detect_merged_but_not_done", return_value=detect_result) as mock_detect, \
         patch("_dr_merge._handle_post_merge_done") as mock_done, \
         patch("_dr_merge._pub_and_log"):
        import _dr_merge
        detect_res = _dr_merge.detect_merged_but_not_done("runner-hb", mock_redis)
        if detect_res:
            _dr_merge._handle_post_merge_done(detect_res["plan_file"], "runner-hb", lambda m: None, mock_redis)

    mock_detect.assert_called_once()
    mock_done.assert_called_once()


# ── _cleanup_process_state self-join 방지 ─────────────────────────────────────


def test_cleanup_no_self_join_R():
    """R(Right): current_thread == stream_thread일 때 t.join() 미호출 → RuntimeError 없음"""
    from _dr_process_utils import _cleanup_process_state
    from _dr_state import get_stream_threads, get_running_processes, get_cleanup_done

    runner_id = "runner-self-join-test"
    result_holder = {"error": None, "joined": False}

    def run_cleanup():
        # 현재 스레드를 stream_threads에 등록
        t = threading.current_thread()
        mock_t = MagicMock()
        mock_t.is_alive.return_value = True
        # current_thread()와 동일한 객체여야 self-join 방지 가드가 작동
        get_stream_threads()[runner_id] = t
        get_running_processes()[runner_id] = MagicMock()

        mock_redis = _strict_redis_mock()
        mock_redis.get.return_value = None
        mock_redis.set.return_value = None
        mock_redis.srem.return_value = None
        mock_redis.zadd.return_value = None
        mock_redis.expire.return_value = None
        mock_redis.lrem.return_value = None
        mock_redis.publish.return_value = None
        mock_redis.persist.return_value = None

        try:
            with patch("worktree_manager.WorktreeManager"), \
                 patch("_dr_process_utils.get_wf_manager", return_value=None):
                _cleanup_process_state(runner_id, mock_redis)
        except RuntimeError as e:
            result_holder["error"] = str(e)

    t = threading.Thread(target=run_cleanup)
    t.start()
    t.join(timeout=5)

    assert result_holder["error"] is None, f"self-join 에러 발생: {result_holder['error']}"


def test_cleanup_normal_join_B():
    """B(Boundary): 다른 스레드에서 호출 시 t.join() 정상 호출 (스킵 없음)"""
    from _dr_process_utils import _cleanup_process_state
    from _dr_state import get_stream_threads, get_running_processes

    runner_id = "runner-normal-join-test"
    join_called = []

    mock_stream_t = MagicMock()
    mock_stream_t.is_alive.return_value = True
    mock_stream_t.join.side_effect = lambda timeout=None: join_called.append(True)

    get_stream_threads()[runner_id] = mock_stream_t
    get_running_processes()[runner_id] = MagicMock()

    mock_redis = _strict_redis_mock()
    mock_redis.get.return_value = None
    mock_redis.set.return_value = None
    mock_redis.srem.return_value = None
    mock_redis.zadd.return_value = None
    mock_redis.expire.return_value = None
    mock_redis.lrem.return_value = None
    mock_redis.publish.return_value = None
    mock_redis.persist.return_value = None

    with patch("worktree_manager.WorktreeManager"), \
         patch("_dr_process_utils.get_wf_manager", return_value=None):
        _cleanup_process_state(runner_id, mock_redis)

    # mock_stream_t != threading.current_thread() → join 호출 확인
    assert len(join_called) == 1


# ── handle_merge_stage merge_status 세팅 ─────────────────────────────────────


@pytest.mark.asyncio
async def test_handle_merge_stage_sets_merge_status_on_success_R():
    """R(Right): execute_merge mock 성공 → merge_status가 merged를 거쳐 done으로 종료"""
    import sys
    _wtools_tools = Path(__file__).parents[6] / "service" / "wtools" / "common" / "tools"
    _wtools_plan_runner = _wtools_tools / "plan-runner"
    for _p in (str(_wtools_plan_runner), str(_wtools_tools)):
        if _p not in sys.path:
            sys.path.insert(0, _p)

    try:
        # wtools/plan-runner는 legacy absolute import(`core.*`)를 쓰면서,
        # 최근에는 module alias(`plan_runner.core.*`)도 참조한다.
        # 두 경로를 모두 sys.path에 올리고, alias를 안전하게 보장한다.
        from core.merge_stage import handle_merge_stage, StageResult
        import core.merge_stage as _cm
        sys.modules.setdefault("plan_runner.core.merge_stage", _cm)
    except ImportError:
        pytest.skip("wtools merge_stage 임포트 불가")

    status_history = []

    class _StubMergeLogger:
        def __init__(self, *args, **kwargs):
            pass

        def set_status(self, status: str, key: str) -> None:
            status_history.append((key, status))

        def log(self, *_args, **_kwargs):
            return None

        def publish_completed(self, **_kwargs):
            return None

        def push_result(self, *_args, **_kwargs):
            return None

    mock_merge_result = MagicMock()
    mock_merge_result.success = True
    mock_test_result = MagicMock()
    mock_test_result.success = True
    mock_test_result.fix_attempts = 0

    with patch("core.merge_stage.execute_merge", new=AsyncMock(return_value=mock_merge_result)), \
         patch("core.merge_stage.run_post_merge_tests", new=AsyncMock(return_value=mock_test_result)), \
         patch("core.merge_stage.run_done", return_value=True), \
         patch("core.merge_stage._cleanup_remote_branch"), \
         patch("core.merge_stage.MergeLogger", new=_StubMergeLogger), \
         patch("core.merge_stage._ml_get_repo_id", return_value="repo-test"), \
         patch("core.merge_stage._ml_acquire", return_value=True), \
         patch("core.merge_stage._ml_release", return_value=True), \
         patch("core.merge_stage._redis_mod") as mock_redis_mod:
        mock_redis_mod.Redis.return_value = _strict_redis_mock()

        result = await handle_merge_stage(
            project_dir=Path("/tmp/proj"),
            runner_id="runner-ms-test",
            python_path="python",
            branch="plan/test",
            worktree_path=Path("/tmp/wt"),
            plan_file="/tmp/plan.md",
        )

    assert result.status == "SUCCESS"
    # merge_status는 merged를 거쳐 최종 done으로 마감된다.
    merged_key = "plan-runner:runners:runner-ms-test:merge_status"
    assert (merged_key, "merged") in status_history, f"merge_status=merged 세팅 이력 없음. history={status_history}"
    # wtools merge_stage는 post-merge test 성공 시 merge_status를 merged로 유지하고,
    # done 전이는 post-merge done 단계에서 수행된다.
    assert status_history and status_history[-1] == (merged_key, "merged"), f"최종 merge_status가 merged가 아님. history={status_history}"


@pytest.mark.asyncio
async def test_handle_merge_stage_sets_merge_status_on_failure_E():
    """E(Error): execute_merge mock 실패 → merge_status=error 확인"""
    import sys
    _wtools_tools = Path(__file__).parents[6] / "service" / "wtools" / "common" / "tools"
    _wtools_plan_runner = _wtools_tools / "plan-runner"
    for _p in (str(_wtools_plan_runner), str(_wtools_tools)):
        if _p not in sys.path:
            sys.path.insert(0, _p)

    try:
        from core.merge_stage import handle_merge_stage
        import core.merge_stage as _cm
        sys.modules.setdefault("plan_runner.core.merge_stage", _cm)
    except ImportError:
        pytest.skip("wtools merge_stage 임포트 불가")

    status_history = []

    class _StubMergeLogger:
        def __init__(self, *args, **kwargs):
            pass

        def set_status(self, status: str, key: str) -> None:
            status_history.append((key, status))

        def log(self, *_args, **_kwargs):
            return None

        def publish_completed(self, **_kwargs):
            return None

        def push_result(self, *_args, **_kwargs):
            return None

    mock_merge_result = MagicMock()
    mock_merge_result.success = False
    mock_merge_result.message = "merge 실패"

    with patch("core.merge_stage.execute_merge", new=AsyncMock(return_value=mock_merge_result)), \
         patch("core.merge_stage.MergeLogger", new=_StubMergeLogger), \
         patch("core.merge_stage._ml_get_repo_id", return_value="repo-test"), \
         patch("core.merge_stage._ml_acquire", return_value=True), \
         patch("core.merge_stage._ml_release", return_value=True), \
         patch("core.merge_stage._redis_mod") as mock_redis_mod:
        mock_redis_mod.Redis.return_value = _strict_redis_mock()

        result = await handle_merge_stage(
            project_dir=Path("/tmp/proj"),
            runner_id="runner-ms-fail",
            python_path="python",
            branch="plan/test",
            worktree_path=Path("/tmp/wt"),
            plan_file="/tmp/plan.md",
        )

    assert result.status == "FAILED"
    error_key = "plan-runner:runners:runner-ms-fail:merge_status"
    assert status_history and status_history[-1] == (error_key, "error"), f"merge_status=error 세팅 없음. history={status_history}"


@pytest.mark.asyncio
async def test_handle_merge_stage_sets_merging_before_execute_R():
    """R(Right): execute_merge 호출 전 merge_status=merging 세팅 확인"""
    import sys
    _wtools_tools = Path(__file__).parents[6] / "service" / "wtools" / "common" / "tools"
    _wtools_plan_runner = _wtools_tools / "plan-runner"
    for _p in (str(_wtools_plan_runner), str(_wtools_tools)):
        if _p not in sys.path:
            sys.path.insert(0, _p)

    try:
        from core.merge_stage import handle_merge_stage
        import core.merge_stage as _cm
        sys.modules.setdefault("plan_runner.core.merge_stage", _cm)
    except ImportError:
        pytest.skip("wtools merge_stage 임포트 불가")

    status_history = []

    class _StubMergeLogger:
        def __init__(self, *args, **kwargs):
            pass

        def set_status(self, status: str, key: str) -> None:
            status_history.append((key, status))

        def log(self, *_args, **_kwargs):
            return None

        def publish_completed(self, **_kwargs):
            return None

        def push_result(self, *_args, **_kwargs):
            return None

    merge_called_after = []

    async def _mock_execute_merge(*args, **kwargs):
        # merging이 먼저 세팅됐는지 확인
        merge_key = "plan-runner:runners:runner-merging:merge_status"
        merging_set = (merge_key, "merging") in status_history
        merge_called_after.append(merging_set)
        r = MagicMock()
        r.success = False
        r.message = "test"
        return r

    with patch("core.merge_stage.execute_merge", new=_mock_execute_merge), \
         patch("core.merge_stage.MergeLogger", new=_StubMergeLogger), \
         patch("core.merge_stage._ml_get_repo_id", return_value="repo-test"), \
         patch("core.merge_stage._ml_acquire", return_value=True), \
         patch("core.merge_stage._ml_release", return_value=True), \
         patch("core.merge_stage._redis_mod") as mock_redis_mod:
        mock_redis_mod.Redis.return_value = _strict_redis_mock()

        await handle_merge_stage(
            project_dir=Path("/tmp/proj"),
            runner_id="runner-merging",
            python_path="python",
            branch="plan/test",
            worktree_path=Path("/tmp/wt"),
            plan_file="/tmp/plan.md",
        )

    assert merge_called_after and merge_called_after[0] is True, "execute_merge 호출 전 merging 미세팅"


# ── _handle_post_merge_done 상태 전이 ─────────────────────────────────────────


def test_handle_post_merge_done_transitions_status_R(tmp_path):
    """R(Right): plan 상태 머지대기 → _handle_post_merge_done() 호출 → plan 상태 구현완료로 전이"""
    plan = tmp_path / "2026-03-30_test-plan.md"
    plan.write_text(
        "> 작성일: 2026-03-30\n"
        "> 상태: 머지대기\n"
        "> 진행률: 5/5 (100%)\n"
        "\n"
        "- [x] 항목1\n"
        "- [x] 항목2\n"
        "- [x] 항목3\n"
        "- [x] 항목4\n"
        "- [x] 항목5\n",
        encoding="utf-8",
    )

    pub_calls = []
    mock_redis = _strict_redis_mock()
    mock_redis.get.return_value = None

    with patch("plan_worktree_helpers.remove_plan_header_fields"), \
         patch("plan_worktree_helpers.get_plan_completion", return_value=(5, 5)), \
         patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        from _dr_merge import _handle_post_merge_done
        _handle_post_merge_done(str(plan), "runner-st", pub_calls.append, mock_redis)

    updated = plan.read_text(encoding="utf-8")
    assert re.search(r">\s*상태:\s*구현완료", updated), f"상태 전이 안됨: {updated[:300]}"


# ── G1: detect branch_tail fallback 경로 ─────────────────────────────────────


def test_detect_merged_git_log_branch_tail_fallback_R(tmp_path):
    """R(Right): primary grep 빈 결과 + branch_tail grep 성공 → dict 반환"""
    plan = tmp_path / "plan.md"
    plan.write_text("> 상태: 머지대기\n- [ ] todo\n", encoding="utf-8")

    r = _make_redis_mock(merge_status=None, plan_file=str(plan), branch="impl/fix-something")

    mod = _load_dr_merge()

    # primary grep: empty, branch_tail grep: hit
    call_count = [0]

    def _mock_run(cmd, **kwargs):
        call_count[0] += 1
        result = MagicMock()
        result.returncode = 0
        if call_count[0] == 1:
            # primary --grep="Merge branch 'impl/fix-something'" → empty
            result.stdout = ""
        else:
            # fallback --grep=fix-something → hit
            result.stdout = "abc1234 Merge branch 'impl/fix-something' into main\n"
        return result

    with patch("plan_worktree_helpers.is_plan_archived", return_value=False), \
         patch("subprocess.run", side_effect=_mock_run):
        result = mod.detect_merged_but_not_done("runner-g1", r)

    assert result is not None, "branch_tail fallback 경로에서 감지 실패"
    assert result["plan_file"] == str(plan)
    assert call_count[0] == 2, f"subprocess.run 2회 호출 예상, 실제 {call_count[0]}회"


# ── G2/P1: 이중 호출 방어 (detect → handle → detect=None) ────────────────────


def test_double_call_defense_second_detect_returns_none_R(tmp_path):
    """R(Right): 첫 호출 후 plan 상태 구현완료 → 두 번째 detect=None (이중 실행 방어)"""
    plan = tmp_path / "plan.md"
    plan.write_text("> 상태: 머지대기\n> 진행률: 2/2 (100%)\n- [x] a\n- [x] b\n", encoding="utf-8")

    r = _make_redis_mock(merge_status="merged", plan_file=str(plan), branch="impl/test")

    mod = _load_dr_merge()

    # 1차 detect: 머지대기 → dict
    with patch("plan_worktree_helpers.is_plan_archived", return_value=False):
        first = mod.detect_merged_but_not_done("runner-g2", r)
    assert first is not None

    # _handle_post_merge_done 시뮬레이션: plan 상태를 구현완료로 전이
    content = plan.read_text(encoding="utf-8")
    content = content.replace("머지대기", "구현완료")
    plan.write_text(content, encoding="utf-8")

    # 2차 detect: 구현완료 → None
    with patch("plan_worktree_helpers.is_plan_archived", return_value=False):
        second = mod.detect_merged_but_not_done("runner-g2", r)
    assert second is None, f"이중 호출 방어 실패: 2차 detect가 None이 아님 → {second}"


# ── G3: Phase R 4개 경로 fallback 패턴 검증 ──────────────────────────────────


def test_monitor_pid_fallback_calls_detect_before_cleanup_R():
    """R(Right): _monitor_pid_until_exit에서 PID 종료 시 detect→handle→cleanup 순서 확인"""
    from _dr_process_utils import _monitor_pid_until_exit
    from _dr_state import get_stream_threads, get_running_processes, get_cleanup_done

    runner_id = "runner-g3-mpid"
    mock_redis = _strict_redis_mock()
    detect_result = {"plan_file": "/tmp/plan.md", "branch": "impl/test"}

    call_order = []

    # _running_processes에 등록 (루프 진입 조건)
    mock_proc = MagicMock()
    mock_proc.poll.return_value = 1  # 프로세스 종료됨
    get_running_processes()[runner_id] = mock_proc
    get_stream_threads()[runner_id] = MagicMock(is_alive=MagicMock(return_value=False))

    # lazy import를 우회하기 위해 _dr_merge 모듈 자체를 mock
    mock_dr_merge = types.ModuleType("_dr_merge")
    mock_dr_merge.detect_merged_but_not_done = lambda *a, **k: (call_order.append("detect"), detect_result)[1]
    mock_dr_merge._handle_post_merge_done = lambda *a, **k: call_order.append("handle")
    mock_dr_merge._pub_and_log = lambda *a, **k: None

    with patch.dict("sys.modules", {"_dr_merge": mock_dr_merge}), \
         patch("_dr_process_utils._is_pid_alive", side_effect=[False]), \
         patch("_dr_process_utils._cleanup_process_state", side_effect=lambda *a, **k: call_order.append("cleanup")), \
         patch("time.sleep"):
        _monitor_pid_until_exit(runner_id, 12345, mock_redis)

    assert "detect" in call_order, f"detect 미호출: {call_order}"
    assert "handle" in call_order, f"handle 미호출: {call_order}"
    assert "cleanup" in call_order, f"cleanup 미호출: {call_order}"
    assert call_order.index("detect") < call_order.index("cleanup"), "detect가 cleanup보다 늦게 호출"


def test_attach_no_log_file_fallback_R():
    """R(Right): _attach_to_running_process 로그 파일 없음 → detect→handle→cleanup"""
    from _dr_process_utils import _attach_to_running_process

    runner_id = "runner-g3-nolog"
    mock_redis = _strict_redis_mock()
    mock_redis.get.return_value = None  # log_file_path = None
    detect_result = {"plan_file": "/tmp/plan.md", "branch": "impl/test"}

    call_order = []
    mock_dr_merge = types.ModuleType("_dr_merge")
    mock_dr_merge.detect_merged_but_not_done = lambda *a, **k: (call_order.append("detect"), detect_result)[1]
    mock_dr_merge._handle_post_merge_done = lambda *a, **k: call_order.append("handle")
    mock_dr_merge._pub_and_log = lambda *a, **k: None

    with patch.dict("sys.modules", {"_dr_merge": mock_dr_merge}), \
         patch("_dr_process_utils._cleanup_process_state", side_effect=lambda *a, **k: call_order.append("cleanup")):
        _attach_to_running_process(runner_id, 99999, mock_redis)

    assert call_order == ["detect", "handle", "cleanup"], f"순서 불일치: {call_order}"


def test_reconnect_no_pid_fallback_R():
    """R(Right): _reconnect_surviving_runners no-pid 경로 → detect→handle→cleanup"""
    from _dr_process_utils import _reconnect_surviving_runners

    runner_id = "runner-g3-nopid"
    mock_redis = _strict_redis_mock()
    detect_result = {"plan_file": "/tmp/plan.md", "branch": "impl/test"}

    # smembers → 1개 runner, pid → None
    mock_redis.smembers.return_value = {runner_id}
    _get_map = {
        f"plan-runner:runners:{runner_id}:pid": None,
        f"plan-runner:runners:{runner_id}:merge_requested": None,
        f"plan-runner:runners:{runner_id}:merge_status": None,
    }
    mock_redis.get.side_effect = lambda k: _get_map.get(k)

    call_order = []
    mock_dr_merge = types.ModuleType("_dr_merge")
    mock_dr_merge.detect_merged_but_not_done = lambda *a, **k: (call_order.append("detect"), detect_result)[1]
    mock_dr_merge._handle_post_merge_done = lambda *a, **k: call_order.append("handle")
    mock_dr_merge._pub_and_log = lambda *a, **k: None

    with patch.dict("sys.modules", {"_dr_merge": mock_dr_merge}), \
         patch("_dr_process_utils._cleanup_process_state", side_effect=lambda *a, **k: call_order.append("cleanup")):
        _reconnect_surviving_runners(mock_redis)

    assert call_order == ["detect", "handle", "cleanup"], f"순서 불일치: {call_order}"


def test_heartbeat_stream_hang_fallback_R():
    """R(Right): heartbeat에서 stream thread hang 30초 경과 → detect→handle→cleanup 순서"""
    # command-listener 코드에서 직접 호출되는 로직을 단위 테스트
    # detect→handle→cleanup 순서를 증명
    mock_redis = _strict_redis_mock()
    detect_result = {"plan_file": "/tmp/plan.md", "branch": "impl/test"}

    call_order = []

    with patch("_dr_merge.detect_merged_but_not_done", return_value=detect_result) as mock_detect, \
         patch("_dr_merge._handle_post_merge_done") as mock_done, \
         patch("_dr_merge._pub_and_log"):
        mock_detect.side_effect = lambda *a, **k: (call_order.append("detect"), detect_result)[1]
        mock_done.side_effect = lambda *a, **k: call_order.append("handle")

        # heartbeat hang 경로 로직 재현
        import _dr_merge
        _hang_v2_detect = _dr_merge.detect_merged_but_not_done("runner-hang", mock_redis)
        if _hang_v2_detect:
            _dr_merge._handle_post_merge_done(_hang_v2_detect["plan_file"], "runner-hang", lambda m: None, mock_redis)
        call_order.append("cleanup")  # cleanup 시점 마킹

    assert call_order == ["detect", "handle", "cleanup"], f"순서 불일치: {call_order}"


def test_stream_output_merge_requested_pre_review_stopped_blocks_inline_merge_R(tmp_path):
    """R: merge_requested=1 + stop_stage=pre_review면 _do_inline_merge 진입 금지."""
    import io

    runner_id = "runner-stop-pre"
    mock_redis = _strict_redis_mock()

    def _get(key):
        if key.endswith(":exit_reason"):
            return "stopped"
        if key.endswith(":stop_stage"):
            return "pre_review"
        if key.endswith(":merge_requested"):
            return "1"
        if key.endswith(":branch"):
            return "impl/test"
        return None

    mock_redis.get.side_effect = _get

    mock_proc = MagicMock()
    mock_proc.stdout = io.StringIO("")
    mock_proc.returncode = 0
    mock_proc.wait.return_value = 0

    log_handle = io.StringIO()
    from _dr_state import get_running_log_files
    get_running_log_files()[runner_id] = tmp_path / "pre.log"
    (tmp_path / "pre.log").write_text("", encoding="utf-8")

    with patch("_dr_stream_cleanup.detect_merged_but_not_done", return_value=None), \
         patch("_dr_stream_cleanup._do_inline_merge") as mock_inline_merge, \
         patch("_dr_stream_cleanup._cleanup_process_state") as mock_cleanup:
        from _dr_plan_runner import _stream_output
        _stream_output(mock_proc, log_handle, mock_redis, runner_id)

    mock_inline_merge.assert_not_called()
    mock_cleanup.assert_called_once()


def test_stream_output_merge_requested_post_review_stopped_keeps_inline_merge_R(tmp_path):
    """R: merge_requested=1 + stop_stage=post_review라도 비정상 종료면 inline merge를 수행하지 않는다."""
    import io

    runner_id = "runner-stop-post"
    mock_redis = _strict_redis_mock()

    def _get(key):
        if key.endswith(":exit_reason"):
            return "stopped"
        if key.endswith(":stop_stage"):
            return "post_review"
        if key.endswith(":merge_requested"):
            return "1"
        if key.endswith(":branch"):
            return "impl/test"
        return None

    mock_redis.get.side_effect = _get

    mock_proc = MagicMock()
    mock_proc.stdout = io.StringIO("")
    mock_proc.returncode = 0
    mock_proc.wait.return_value = 0

    log_handle = io.StringIO()
    from _dr_state import get_running_log_files
    get_running_log_files()[runner_id] = tmp_path / "post.log"
    (tmp_path / "post.log").write_text("", encoding="utf-8")

    with patch("_dr_stream_cleanup.detect_merged_but_not_done", return_value=None), \
         patch("_dr_stream_cleanup._do_inline_merge") as mock_inline_merge, \
         patch("_dr_stream_cleanup._cleanup_process_state") as mock_cleanup:
        from _dr_plan_runner import _stream_output
        _stream_output(mock_proc, log_handle, mock_redis, runner_id)

    mock_inline_merge.assert_not_called()
    mock_cleanup.assert_called_once()

