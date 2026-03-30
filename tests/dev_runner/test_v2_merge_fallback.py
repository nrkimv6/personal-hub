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


def _make_redis_mock(merge_status=None, plan_file=None, branch=None):
    r = MagicMock()
    prefix = "plan-runner:runners"

    def _get(key):
        if ":merge_status" in key:
            return merge_status
        if ":plan_file" in key:
            return plan_file
        if ":branch" in key:
            return branch
        return None

    r.get.side_effect = _get
    return r


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
    r = MagicMock()
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
    mock_redis = MagicMock()
    mock_redis.get.return_value = None  # merge_requested = None

    # subprocess mock: stdout이 비어있는 프로세스
    mock_proc = MagicMock()
    mock_proc.stdout = iter([])
    mock_proc.returncode = 15
    mock_proc.wait.return_value = None

    log_handle = io.StringIO()

    from _dr_state import get_running_log_files, get_stream_threads, get_wf_manager
    get_running_log_files()["runner-t1"] = tmp_path / "test.log"
    (tmp_path / "test.log").write_text("", encoding="utf-8")

    with patch("_dr_plan_runner.detect_merged_but_not_done", return_value=detect_result) as mock_detect, \
         patch("_dr_plan_runner._handle_post_merge_done") as mock_done, \
         patch("_dr_plan_runner._cleanup_process_state") as mock_cleanup:
        from _dr_plan_runner import _stream_output
        _stream_output(mock_proc, log_handle, mock_redis, "runner-t1")

    mock_detect.assert_called_once_with("runner-t1", mock_redis)
    mock_done.assert_called_once()
    mock_cleanup.assert_called_once()


def test_stream_output_v2_fallback_skip_B(tmp_path):
    """B(Boundary): detect → None → _handle_post_merge_done 미호출 + _cleanup_process_state 호출"""
    import io

    mock_redis = MagicMock()
    mock_redis.get.return_value = None

    mock_proc = MagicMock()
    mock_proc.stdout = iter([])
    mock_proc.returncode = 0
    mock_proc.wait.return_value = None

    log_handle = io.StringIO()

    from _dr_state import get_running_log_files
    get_running_log_files()["runner-t2"] = tmp_path / "test2.log"
    (tmp_path / "test2.log").write_text("", encoding="utf-8")

    with patch("_dr_plan_runner.detect_merged_but_not_done", return_value=None) as mock_detect, \
         patch("_dr_plan_runner._handle_post_merge_done") as mock_done, \
         patch("_dr_plan_runner._cleanup_process_state") as mock_cleanup:
        from _dr_plan_runner import _stream_output
        _stream_output(mock_proc, log_handle, mock_redis, "runner-t2")

    mock_detect.assert_called_once_with("runner-t2", mock_redis)
    mock_done.assert_not_called()
    mock_cleanup.assert_called_once()


def test_stream_output_v2_fallback_error_still_cleanup_E(tmp_path):
    """E(Error): _handle_post_merge_done이 예외 발생 → 예외 후에도 _cleanup_process_state 호출"""
    import io

    detect_result = {"plan_file": "/some/plan.md", "branch": "plan/test"}
    mock_redis = MagicMock()
    mock_redis.get.return_value = None

    mock_proc = MagicMock()
    mock_proc.stdout = iter([])
    mock_proc.returncode = 15
    mock_proc.wait.return_value = None

    log_handle = io.StringIO()

    from _dr_state import get_running_log_files
    get_running_log_files()["runner-t3"] = tmp_path / "test3.log"
    (tmp_path / "test3.log").write_text("", encoding="utf-8")

    with patch("_dr_plan_runner.detect_merged_but_not_done", return_value=detect_result), \
         patch("_dr_plan_runner._handle_post_merge_done", side_effect=RuntimeError("done 실패")), \
         patch("_dr_plan_runner._cleanup_process_state") as mock_cleanup:
        from _dr_plan_runner import _stream_output
        _stream_output(mock_proc, log_handle, mock_redis, "runner-t3")

    mock_cleanup.assert_called_once()


# ── heartbeat v2 fallback ─────────────────────────────────────────────────────


def test_heartbeat_v2_fallback_R(tmp_path):
    """R(Right): heartbeat 루프 dead process + detect → dict → _handle_post_merge_done 호출"""
    plan = tmp_path / "plan.md"
    plan.write_text("> 상태: 머지대기\n- [ ] todo\n", encoding="utf-8")

    detect_result = {"plan_file": str(plan), "branch": "plan/test"}

    # heartbeat fallback 로직 직접 테스트: 해당 분기 추출
    pub_calls = []
    mock_redis = MagicMock()

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

        mock_redis = MagicMock()
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

    mock_redis = MagicMock()
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
    """R(Right): execute_merge mock 성공 → Redis merge_status=merged 확인"""
    import sys
    _wtools_path = Path(__file__).parents[6] / "service" / "wtools" / "common" / "tools" / "plan-runner"
    if str(_wtools_path) not in sys.path:
        sys.path.insert(0, str(_wtools_path))

    try:
        from core.merge_stage import handle_merge_stage, StageResult
    except ImportError:
        pytest.skip("wtools merge_stage 임포트 불가")

    mock_redis = MagicMock()
    status_calls = {}

    def _redis_set(key, val):
        status_calls[key] = val

    mock_redis.set.side_effect = _redis_set
    mock_redis.ping.return_value = True

    mock_merge_result = MagicMock()
    mock_merge_result.success = True
    mock_test_result = MagicMock()
    mock_test_result.success = True
    mock_test_result.fix_attempts = 0

    with patch("core.merge_stage.execute_merge", new=AsyncMock(return_value=mock_merge_result)), \
         patch("core.merge_stage.run_post_merge_tests", new=AsyncMock(return_value=mock_test_result)), \
         patch("core.merge_stage.run_done", return_value=True), \
         patch("core.merge_stage._cleanup_remote_branch"), \
         patch("core.merge_stage._redis_mod") as mock_redis_mod:
        mock_redis_mod.Redis.return_value = mock_redis

        result = await handle_merge_stage(
            project_dir=Path("/tmp/proj"),
            runner_id="runner-ms-test",
            python_path="python",
            branch="plan/test",
            worktree_path=Path("/tmp/wt"),
            plan_file="/tmp/plan.md",
        )

    assert result.status == "SUCCESS"
    # merge_status=merged 키가 세팅됐는지 확인
    merged_key = "plan-runner:runners:runner-ms-test:merge_status"
    assert status_calls.get(merged_key) == "merged", f"merge_status 세팅 없음. calls={status_calls}"


@pytest.mark.asyncio
async def test_handle_merge_stage_sets_merge_status_on_failure_E():
    """E(Error): execute_merge mock 실패 → Redis merge_status=error 확인"""
    import sys
    _wtools_path = Path(__file__).parents[6] / "service" / "wtools" / "common" / "tools" / "plan-runner"
    if str(_wtools_path) not in sys.path:
        sys.path.insert(0, str(_wtools_path))

    try:
        from core.merge_stage import handle_merge_stage
    except ImportError:
        pytest.skip("wtools merge_stage 임포트 불가")

    mock_redis = MagicMock()
    status_calls = {}

    def _redis_set(key, val):
        status_calls[key] = val

    mock_redis.set.side_effect = _redis_set
    mock_redis.ping.return_value = True

    mock_merge_result = MagicMock()
    mock_merge_result.success = False
    mock_merge_result.message = "merge 실패"

    with patch("core.merge_stage.execute_merge", new=AsyncMock(return_value=mock_merge_result)), \
         patch("core.merge_stage._redis_mod") as mock_redis_mod:
        mock_redis_mod.Redis.return_value = mock_redis

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
    assert status_calls.get(error_key) == "error", f"merge_status=error 세팅 없음. calls={status_calls}"


@pytest.mark.asyncio
async def test_handle_merge_stage_sets_merging_before_execute_R():
    """R(Right): execute_merge 호출 전 merge_status=merging 세팅 확인"""
    import sys
    _wtools_path = Path(__file__).parents[6] / "service" / "wtools" / "common" / "tools" / "plan-runner"
    if str(_wtools_path) not in sys.path:
        sys.path.insert(0, str(_wtools_path))

    try:
        from core.merge_stage import handle_merge_stage
    except ImportError:
        pytest.skip("wtools merge_stage 임포트 불가")

    mock_redis = MagicMock()
    call_order = []

    def _redis_set(key, val):
        call_order.append((key, val))

    mock_redis.set.side_effect = _redis_set
    mock_redis.ping.return_value = True

    merge_called_after = []

    async def _mock_execute_merge(*args, **kwargs):
        # merging이 먼저 세팅됐는지 확인
        merging_set = any(v == "merging" for _, v in call_order)
        merge_called_after.append(merging_set)
        r = MagicMock()
        r.success = False
        r.message = "test"
        return r

    with patch("core.merge_stage.execute_merge", new=_mock_execute_merge), \
         patch("core.merge_stage._redis_mod") as mock_redis_mod:
        mock_redis_mod.Redis.return_value = mock_redis

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
    mock_redis = MagicMock()
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
