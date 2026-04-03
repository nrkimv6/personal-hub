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

_SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

_SCRIPT_PATH = _SCRIPTS_DIR / "dev-runner-command-listener.py"
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
    mock_redis = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200

    with patch("plan_worktree_helpers.remove_plan_header_fields"), \
         patch("requests.post", return_value=mock_resp):
        cl._handle_post_merge_done(str(plan), "runner1", pub_msgs.append, mock_redis)

    assert any("100%" in m for m in pub_msgs)
    # restart_after_merge 설정 안 됨
    mock_redis.set.assert_not_called()


def test__handle_post_merge_done_right_skips_incomplete(cl, tmp_path):
    """R: 미완료 태스크 있을 때 restart_after_merge 설정됨"""
    plan = tmp_path / "plan.md"
    plan.write_text("- [x] 완료\n- [ ] 미완료\n", encoding="utf-8")

    pub_msgs = []
    mock_redis = MagicMock()

    with patch("plan_worktree_helpers.remove_plan_header_fields"), \
         patch("_dr_merge._call_done_api") as mock_done:
        cl._handle_post_merge_done(str(plan), "runner2", pub_msgs.append, mock_redis)

    mock_done.assert_not_called()
    assert any("추가 사이클 예약" in m for m in pub_msgs)
    mock_redis.set.assert_called_once()
    set_call_args = mock_redis.set.call_args[0]
    assert "restart_after_merge" in set_call_args[0]
    assert set_call_args[1] == "1"


def test__handle_post_merge_done_boundary_no_plan_file(cl):
    """B: plan_file=None → 스킵, done API 미호출"""
    pub_msgs = []
    mock_redis = MagicMock()

    with patch("plan_worktree_helpers.remove_plan_header_fields") as mock_remove, \
         patch("_dr_merge._call_done_api") as mock_done:
        cl._handle_post_merge_done(None, "runner3", pub_msgs.append, mock_redis)

    mock_remove.assert_not_called()
    mock_done.assert_not_called()
    assert any("done 스킵" in m for m in pub_msgs)


def test__handle_post_merge_done_boundary_all_mode(cl):
    """B: plan_file=--all → 스킵, done API 미호출"""
    pub_msgs = []
    mock_redis = MagicMock()

    with patch("plan_worktree_helpers.remove_plan_header_fields") as mock_remove, \
         patch("_dr_merge._call_done_api") as mock_done:
        cl._handle_post_merge_done(cl.PLAN_FILE_ALL, "runner4", pub_msgs.append, mock_redis)

    mock_remove.assert_not_called()
    mock_done.assert_not_called()


def test__handle_post_merge_done_error_api_failure_no_raise(cl, tmp_path):
    """E: done API 실패(500)여도 예외가 상위로 전파되지 않음"""
    plan = tmp_path / "plan.md"
    plan.write_text("- [x] 항목1\n", encoding="utf-8")

    pub_msgs = []
    mock_redis = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 500

    with patch("plan_worktree_helpers.remove_plan_header_fields"), \
         patch("requests.post", return_value=mock_resp):
        # 예외 발생 없이 정상 완료되어야 함
        cl._handle_post_merge_done(str(plan), "runner5", pub_msgs.append, mock_redis)


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

    mock_redis = MagicMock()
    mock_redis.get.side_effect = redis_get_side_effect

    # subprocess: exit_code=3(충돌)
    merge_result_conflict = MagicMock()
    merge_result_conflict.returncode = 3

    resolver_success = {"success": True, "message": "resolved"}

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
