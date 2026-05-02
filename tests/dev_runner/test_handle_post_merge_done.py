"""
TC: _handle_post_merge_done 단위 + 통합 테스트

Phase T1: _handle_post_merge_done 검증
- test__handle_post_merge_done_right_calls_done_api
- test__handle_post_merge_done_right_skips_incomplete
- test__handle_post_merge_done_boundary_no_plan_file
- test__handle_post_merge_done_boundary_all_mode
- test__handle_post_merge_done_error_api_failure_no_raise

Phase T3: conflict resolver 성공 후 done flow 호출 여부 재현
- test_conflict_resolve_success_triggers_done_flow
"""
import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest
from tests.dev_runner.conftest import attach_default_redis_behaviors

_SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

_SCRIPT_PATH = _SCRIPTS_DIR / "plan_runner" / "dev-runner-command-listener.py"
_mock_noise = types.ModuleType("listener_noise_filter")
_mock_noise.NOISE_BLOCK_MARKERS = []
_mock_noise.is_noise_line = lambda line: False


def _load_listener():
    sys.modules["listener_noise_filter"] = _mock_noise
    spec = importlib.util.spec_from_file_location("_listener_pmd", _SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    mod._running_processes = {}
    mod._running_log_files = {}
    mod._stream_threads = {}
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def cl():
    return _load_listener()


# ── T1: _handle_post_merge_done 단위 테스트 ─────────────────────


def test__handle_post_merge_done_right_calls_done_api(cl, tmp_path):
    """R: plan 100% 완료 시 done API가 호출됨"""
    plan = tmp_path / "plan.md"
    plan.write_text("- [x] 항목1\n- [x] 항목2\n", encoding="utf-8")

    pub_msgs = []
    mock_redis = attach_default_redis_behaviors(MagicMock())
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"success": True}

    with patch("plan_worktree_helpers.remove_plan_header_fields"), \
         patch("requests.post", return_value=mock_resp):
        result = cl._handle_post_merge_done(str(plan), "runner1", pub_msgs.append, mock_redis)

    assert any("100%" in m for m in pub_msgs)
    assert result["success"] is True
    assert result["status"] == "done_called"
    # restart_after_merge 설정 안 됨
    restart_calls = [c for c in mock_redis.set.call_args_list if "restart_after_merge" in c.args[0]]
    assert restart_calls == []


def test__handle_post_merge_done_right_skips_incomplete(cl, tmp_path):
    """R: 미완료 태스크 있을 때 restart_after_merge 설정됨"""
    plan = tmp_path / "plan.md"
    plan.write_text("- [x] 완료\n- [ ] 미완료\n", encoding="utf-8")

    pub_msgs = []
    mock_redis = attach_default_redis_behaviors(MagicMock())

    with patch("plan_worktree_helpers.remove_plan_header_fields"), \
         patch("_dr_merge._call_done_api") as mock_done:
        result = cl._handle_post_merge_done(str(plan), "runner2", pub_msgs.append, mock_redis)

    mock_done.assert_not_called()
    assert any("추가 사이클 예약" in m for m in pub_msgs)
    assert result["success"] is True
    assert result["status"] == "restart_scheduled"
    mock_redis.set.assert_called_once()
    set_call_args = mock_redis.set.call_args[0]
    assert "restart_after_merge" in set_call_args[0]
    assert set_call_args[1] == "1"


def test__handle_post_merge_done_boundary_no_plan_file(cl):
    """B: plan_file=None → 스킵, done API 미호출"""
    pub_msgs = []
    mock_redis = attach_default_redis_behaviors(MagicMock())

    with patch("plan_worktree_helpers.remove_plan_header_fields") as mock_remove, \
         patch("_dr_merge._call_done_api") as mock_done:
        result = cl._handle_post_merge_done(None, "runner3", pub_msgs.append, mock_redis)

    mock_remove.assert_not_called()
    mock_done.assert_not_called()
    assert any("done 스킵" in m for m in pub_msgs)
    assert result["success"] is True
    assert result["status"] == "skipped_no_plan"


def test__handle_post_merge_done_boundary_all_mode(cl):
    """B: plan_file=--all → 스킵, done API 미호출"""
    pub_msgs = []
    mock_redis = attach_default_redis_behaviors(MagicMock())

    with patch("plan_worktree_helpers.remove_plan_header_fields") as mock_remove, \
         patch("_dr_merge._call_done_api") as mock_done:
        result = cl._handle_post_merge_done(cl.PLAN_FILE_ALL, "runner4", pub_msgs.append, mock_redis)

    mock_remove.assert_not_called()
    mock_done.assert_not_called()
    assert result["success"] is True
    assert result["status"] == "skipped_no_plan"


def test__handle_post_merge_done_error_api_failure_no_raise(cl, tmp_path):
    """E: done API 실패(500)여도 예외가 상위로 전파되지 않음"""
    plan = tmp_path / "plan.md"
    plan.write_text("- [x] 항목1\n", encoding="utf-8")

    pub_msgs = []
    mock_redis = attach_default_redis_behaviors(MagicMock())
    mock_resp = MagicMock()
    mock_resp.status_code = 500

    with patch("plan_worktree_helpers.remove_plan_header_fields"), \
         patch("requests.post", return_value=mock_resp):
        # 예외 발생 없이 정상 완료되어야 함
        result = cl._handle_post_merge_done(str(plan), "runner5", pub_msgs.append, mock_redis)

    assert result["success"] is False
    assert result["status"] == "done_failed"
    restart_calls = [c for c in mock_redis.set.call_args_list if "restart_after_merge" in c.args[0]]
    assert restart_calls, "done 실패 시 restart_after_merge 예약 필요"


def test_handle_post_merge_done_propagates_done_failure_E(cl, tmp_path):
    """E: done API 실패 시 결과/후속 신호가 호출자에 전달된다."""
    plan = tmp_path / "plan.md"
    plan.write_text("- [x] 항목1\n- [x] 항목2\n", encoding="utf-8")

    pub_msgs = []
    mock_redis = attach_default_redis_behaviors(MagicMock())

    with patch("plan_worktree_helpers.remove_plan_header_fields"), \
         patch("_dr_merge._call_done_api", return_value={"success": False, "reason": "done_api_failed", "message": "done API failed"}) as mock_done:
        result = cl._handle_post_merge_done(str(plan), "runner-fail", pub_msgs.append, mock_redis)

    assert mock_done.call_count == 1
    assert result["success"] is False
    assert result["reason"] == "done_api_failed"
    assert any("자동 done 실패" in m for m in pub_msgs)


def test_handle_post_merge_done_preserves_ownership_guard_reason_E(cl, tmp_path):
    """E: ownership_guard 실패는 redis/result에 별도 reason으로 남는다."""
    plan = tmp_path / "plan.md"
    plan.write_text("- [x] 항목1\n", encoding="utf-8")

    pub_msgs = []
    mock_redis = attach_default_redis_behaviors(MagicMock())

    with patch("plan_worktree_helpers.remove_plan_header_fields"), \
         patch("_dr_merge._register_post_merge_owned_files"), \
         patch(
             "_dr_merge._call_done_api",
             return_value={"success": False, "reason": "ownership_guard", "message": "runner ownership guard blocked auto-done"},
         ):
        result = cl._handle_post_merge_done(str(plan), "runner-own", pub_msgs.append, mock_redis)

    assert result["success"] is False
    assert result["reason"] == "ownership_guard"
    assert any("ownership_guard" in str(call.args[1]) for call in mock_redis.set.call_args_list if "done_post_merge_error" in call.args[0])
    assert any("ownership_guard" in m for m in pub_msgs)


def test_handle_post_merge_done_residue_blocked_skips_restart_E(cl, tmp_path):
    """E: merge_status=residue_blocked면 done/restart를 모두 건너뛴다."""
    plan = tmp_path / "plan.md"
    plan.write_text("- [x] 항목1\n", encoding="utf-8")

    pub_msgs = []
    mock_redis = attach_default_redis_behaviors(MagicMock())

    def redis_get(key):
        if "merge_status" in key:
            return "residue_blocked"
        return None

    mock_redis.get.side_effect = redis_get

    with patch("plan_worktree_helpers.remove_plan_header_fields") as mock_remove, \
         patch("_dr_merge._call_done_api") as mock_done:
        result = cl._handle_post_merge_done(str(plan), "runner-residue", pub_msgs.append, mock_redis)

    mock_remove.assert_not_called()
    mock_done.assert_not_called()
    assert result["success"] is False
    assert result["reason"] == "residue_guard"
    assert result["status"] == "skipped_residue"
    assert not any("restart_after_merge" in str(c) for c in mock_redis.set.call_args_list)
    assert any("residue_blocked" in m for m in pub_msgs)


# ── T3: conflict resolver 성공 후 done flow 재현 TC ─────────────


def test_conflict_resolve_success_triggers_done_flow(cl, tmp_path):
    """T3: conflict resolver 성공 후 _handle_post_merge_done이 호출됨을 검증

    근본 원인 재현: exit_code=3 → resolver 성공 → done flow 호출
    mock: subprocess(merge), lock, resolver, redis
    실물: plan 파일 파싱(_get_plan_completion)
    """
    plan = tmp_path / "plan.md"
    plan.write_text("- [x] 항목1\n- [x] 항목2\n", encoding="utf-8")
    plan_path_str = str(plan)

    # redis.get이 plan_file 반환, 나머지는 None
    def redis_get_side_effect(key):
        if key.endswith(":plan_file"):
            return plan_path_str
        if key.endswith(":branch"):
            return "plan/test-branch"
        if key.endswith(":worktree_path"):
            return str(tmp_path / "worktree")
        return None

    mock_redis = attach_default_redis_behaviors(MagicMock())
    mock_redis.get.side_effect = redis_get_side_effect

    # subprocess: exit_code=3(충돌)
    merge_result_conflict = MagicMock()
    merge_result_conflict.returncode = 3

    resolver_success = {"success": True, "message": "safe-doc auto-resolved", "merge_status": "merged"}

    handled = []

    def mock_handle(plan_file, runner_id, pub_fn, redis_client):
        handled.append(plan_file)

    mock_resp = MagicMock()
    mock_resp.status_code = 200

    with patch("_dr_merge._launch_conflict_resolver_process", return_value=resolver_success), \
         patch("_dr_merge._handle_post_merge_done", side_effect=mock_handle), \
         patch("subprocess.run", return_value=merge_result_conflict), \
         patch("merge_queue.acquire_merge_turn", return_value=True), \
         patch("merge_queue.release_merge_turn"):
        cl._execute_merge_with_lock(
            runner_id="test_runner",
            redis_client=mock_redis,
            action_name="merge",
        )

    # conflict resolver 성공 후 _handle_post_merge_done이 호출됐는지 검증
    assert len(handled) == 1, \
        f"_handle_post_merge_done이 1번 호출돼야 함, 실제: {len(handled)}번"
    assert handled[0] == plan_path_str


def test_conflict_resolve_unsafe_does_not_trigger_done_flow(cl, tmp_path):
    """T3: unsafe conflict 유지 시 _handle_post_merge_done은 호출되면 안 된다."""
    plan = tmp_path / "plan.md"
    plan.write_text("- [x] 항목1\n- [x] 항목2\n", encoding="utf-8")
    plan_path_str = str(plan)

    def redis_get_side_effect(key):
        if key.endswith(":plan_file"):
            return plan_path_str
        if key.endswith(":branch"):
            return "plan/test-branch"
        if key.endswith(":worktree_path"):
            return str(tmp_path / "worktree")
        return None

    mock_redis = attach_default_redis_behaviors(MagicMock())
    mock_redis.get.side_effect = redis_get_side_effect

    merge_result_conflict = MagicMock()
    merge_result_conflict.returncode = 3
    handled = []

    with patch(
        "_dr_merge._launch_conflict_resolver_process",
        return_value={
            "success": False,
            "message": "unsafe conflict requires manual resolution",
            "merge_status": "conflict",
            "conflict": True,
        },
    ), \
         patch("_dr_merge._handle_post_merge_done", side_effect=lambda *args, **kwargs: handled.append(args[0])), \
         patch("subprocess.run", return_value=merge_result_conflict), \
         patch("merge_queue.acquire_merge_turn", return_value=True), \
         patch("merge_queue.release_merge_turn"):
        result = cl._execute_merge_with_lock(
            runner_id="test_runner_conflict",
            redis_client=mock_redis,
            action_name="merge",
        )

    assert handled == []
    assert result["success"] is False
    assert result["merge_status"] == "conflict"
