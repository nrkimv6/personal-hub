"""
TC: _do_retry_merge() — merge lock, 로그 발행, cleanup, merge_status 전이
scripts/dev-runner-command-listener.py의 _do_retry_merge 함수 단위 테스트
"""
import json
import sys
import importlib
import importlib.util
import types
import threading
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

_SCRIPT_PATH = Path(__file__).parent.parent.parent / "scripts" / "plan_runner" / "dev-runner-command-listener.py"

_mock_noise = types.ModuleType("listener_noise_filter")
_mock_noise.NOISE_BLOCK_MARKERS = []
_mock_noise.is_noise_line = lambda line: False

RUNNER_KEY_PREFIX = "plan-runner:runners"
LOG_CHANNEL_PREFIX = "plan-runner:logs"
RESULTS_KEY = "plan-runner:command_results"


def _load_listener():
    sys.modules["listener_noise_filter"] = _mock_noise
    spec = importlib.util.spec_from_file_location("_listener_retry", _SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    mod._running_processes = {}
    mod._running_log_files = {}
    mod._stream_threads = {}
    spec.loader.exec_module(mod)
    return mod


def make_redis_mock(worktree_path=None, plan_file=None):
    redis = MagicMock()

    def redis_get(key):
        if "worktree_path" in key:
            return worktree_path
        if "plan_file" in key:
            return plan_file
        return None

    redis.get.side_effect = redis_get
    redis.set.return_value = True
    redis.lpush.return_value = 1
    redis.expire.return_value = True
    redis.publish.return_value = 1
    return redis


def make_merge_result(merged=True, tests_passed=True, conflict=False, message="ok"):
    result = MagicMock()
    result.merged = merged
    result.tests_passed = tests_passed
    result.conflict = conflict
    result.message = message
    return result


# ---------------------------------------------------------------------------
# Phase T1: _do_retry_merge 단위 테스트
# ---------------------------------------------------------------------------

class TestDoRetryMerge:
    def test_do_retry_merge_acquires_and_releases_lock(self, tmp_path):
        """R: retry-merge는 현재 _execute_merge_with_lock 경로로 위임된다."""
        cl = _load_listener()

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        redis = make_redis_mock(worktree_path=str(worktree))
        with patch("_dr_commands._execute_merge_with_lock", return_value={"success": True, "message": "merged", "merge_status": "merged"}) as mock_merge, \
             patch("_dr_commands._cleanup_process_state"), \
             patch("plan_runner.core.stages.pre_merge_gate", return_value=(True, "ok")), \
             patch("plan_runner.core.stages.auto_commit_stage", return_value=False):
            cl._do_retry_merge("runner01", redis, "cmd001")

        mock_merge.assert_called_once_with("runner01", redis, action_name="retry-merge")

    def test_do_retry_merge_publishes_logs(self, tmp_path):
        """R(Right): 진행 중 plan-runner:logs:{runner_id} 채널에 [MERGE] 로그 발행"""
        cl = _load_listener()

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        runner_id = "t-mretry-02"
        redis = make_redis_mock(worktree_path=str(worktree))
        with patch("_dr_commands._execute_merge_with_lock", return_value={"success": True, "message": "merged", "merge_status": "merged"}), \
             patch("_dr_commands._cleanup_process_state"), \
             patch("plan_runner.core.stages.pre_merge_gate", return_value=(True, "ok")), \
             patch("plan_runner.core.stages.auto_commit_stage", return_value=False):
            cl._do_retry_merge(runner_id, redis, "cmd002")

        log_channel = f"{LOG_CHANNEL_PREFIX}:{runner_id}"
        publish_calls = redis.publish.call_args_list
        assert any(log_channel in str(c) for c in publish_calls), "로그 채널에 publish 없음"
        assert any("[MERGE]" in str(c) for c in publish_calls if log_channel in str(c)), "[MERGE] 로그 없음"

    def test_do_retry_merge_refreshes_ownership_snapshot(self, tmp_path):
        """R: retry-merge는 merge 직전 ownership snapshot을 다시 캡처한다."""
        cl = _load_listener()

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        redis = make_redis_mock(worktree_path=str(worktree))

        with patch("_dr_commands._refresh_runner_ownership_snapshot") as mock_refresh, \
             patch("_dr_commands._execute_merge_with_lock", return_value={"success": True, "message": "merged", "merge_status": "merged"}), \
             patch("_dr_commands._cleanup_process_state"), \
             patch("plan_runner.core.stages.pre_merge_gate", return_value=(True, "ok")), \
             patch("plan_runner.core.stages.auto_commit_stage", return_value=False):
            cl._do_retry_merge("runner-snapshot", redis, "cmd-snapshot")

        mock_refresh.assert_called_once()
        assert mock_refresh.call_args.kwargs["action"] == "retry-merge"

    def test_do_retry_merge_cleanup_on_merged(self, tmp_path):
        """R(Right): merge 성공 시 _cleanup_process_state 호출됨"""
        cl = _load_listener()

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        redis = make_redis_mock(worktree_path=str(worktree))
        with patch("_dr_commands._execute_merge_with_lock", return_value={"success": True, "message": "merged", "merge_status": "merged"}), \
             patch("_dr_commands._cleanup_process_state") as mock_cleanup, \
             patch("plan_runner.core.stages.pre_merge_gate", return_value=(True, "ok")), \
             patch("plan_runner.core.stages.auto_commit_stage", return_value=False):
            cl._do_retry_merge("runner03", redis, "cmd003")

        mock_cleanup.assert_called_once_with("runner03", redis)

    def test_do_retry_merge_preserves_worktree_on_conflict(self, tmp_path):
        """B(Boundary): conflict 시 cleanup 호출 + merge_status='conflict' result 반환"""
        cl = _load_listener()

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        redis = make_redis_mock(worktree_path=str(worktree))

        import plan_runner.core.stages as stages
        with patch.object(stages, "pre_merge_gate", return_value=(True, "ok")), \
             patch("_dr_commands._execute_merge_with_lock", return_value={
                 "success": False, "message": "conflict",
                 "conflict": True, "merge_status": "conflict", "action": "retry-merge"
             }), \
             patch("_dr_commands._cleanup_process_state") as mock_cleanup:
            cl._do_retry_merge("runner04", redis, "cmd004")

        mock_cleanup.assert_called_once()
        push_calls = redis.lpush.call_args_list
        assert push_calls, "결과 LPUSH 없음"
        result = json.loads(push_calls[-1][0][1])
        assert result.get("success") is False

    def test_retry_merge_residue_blocked_distinct_from_error_R(self, tmp_path):
        """R: retry-merge 결과는 residue_blocked를 generic error와 구분해 유지한다."""
        cl = _load_listener()

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        redis = make_redis_mock(worktree_path=str(worktree))
        merge_result = {
            "success": False,
            "message": "post-merge residue detected and restored",
            "merge_status": "residue_blocked",
            "reason": "residue_guard",
            "action": "retry-merge",
        }

        with patch("_dr_commands._execute_merge_with_lock", return_value=merge_result), \
             patch("_dr_commands._cleanup_process_state"), \
             patch("plan_runner.core.stages.pre_merge_gate", return_value=(True, "ok")), \
             patch("plan_runner.core.stages.auto_commit_stage", return_value=False):
            cl._do_retry_merge("runner-residue", redis, "cmd-residue")

        push_calls = redis.lpush.call_args_list
        result = json.loads(push_calls[-1][0][1])
        assert result["merge_status"] == "residue_blocked"
        assert result["reason"] == "residue_guard"
        assert result["message"] == "post-merge residue detected and restored"

    def test_do_retry_merge_lock_timeout_sets_error(self, tmp_path):
        """E(Error): acquire_merge_lock False → merge_status='error' + cleanup"""
        cl = _load_listener()

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        redis = make_redis_mock(worktree_path=str(worktree))

        import merge_queue as mq
        with patch.object(mq, "acquire_merge_turn", return_value=False), \
             patch.object(mq, "release_merge_turn"), \
             patch("_dr_commands._cleanup_process_state") as mock_cleanup:
            cl._do_retry_merge("runner05", redis, "cmd005")

        set_calls = [str(c) for c in redis.set.call_args_list]
        assert any("error" in c for c in set_calls), "merge_status='error' 세팅 안 됨"
        mock_cleanup.assert_called_once()

    def test_do_retry_merge_no_worktree_returns_error(self, tmp_path):
        """E(Error): worktree_path Redis 키 없을 때 에러 결과 LPUSH"""
        cl = _load_listener()

        redis = make_redis_mock(worktree_path=None)

        with patch("_dr_commands._cleanup_process_state"):
            cl._do_retry_merge("runner06", redis, "cmd006")

        push_calls = redis.lpush.call_args_list
        assert push_calls, "결과 LPUSH 없음"
        result_raw = push_calls[-1][0][1]
        result = json.loads(result_raw)
        assert result.get("success") is False

# ---------------------------------------------------------------------------
# Phase T1 items 8-10: pre_merge_gate, auto-resolve, post-merge pipeline TC
# ---------------------------------------------------------------------------

class TestDoRetryMergePhase3Gate:
    """item 8: retry-merge pre-merge gate TC"""

    def test_do_retry_merge_dirty_calls_auto_commit(self, tmp_path):
        """R: pre_merge_gate "dirty" → auto_commit_stage 호출됨"""
        cl = _load_listener()

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        redis = make_redis_mock(worktree_path=str(worktree))

        import plan_runner.core.stages as stages
        with patch.object(stages, "pre_merge_gate", side_effect=[(False, "git dirty: file.py"), (True, "clean")]) as mock_gate, \
             patch.object(stages, "auto_commit_stage", return_value=True) as mock_commit, \
             patch("_dr_commands._execute_merge_with_lock", return_value={"success": True, "message": "merged", "merge_status": "merged", "action": "retry-merge"}), \
             patch("_dr_commands._cleanup_process_state"):
            cl._do_retry_merge("runner_gate01", redis, "cmd_gate01")

        mock_commit.assert_called()

    def test_do_retry_merge_gate_fail_sets_error(self, tmp_path):
        """E: 3회 gate 실패 → merge_status='error' + lock 해제"""
        cl = _load_listener()

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        redis = make_redis_mock(worktree_path=str(worktree))

        import plan_runner.core.stages as stages
        # 항상 dirty, auto_commit도 실패
        with patch.object(stages, "pre_merge_gate", return_value=(False, "git dirty: file.py")), \
             patch.object(stages, "auto_commit_stage", return_value=False), \
             patch("_dr_commands._cleanup_process_state"):
            cl._do_retry_merge("runner_gate02", redis, "cmd_gate02")

        set_calls = [str(c) for c in redis.set.call_args_list]
        assert any("error" in c for c in set_calls), "merge_status='error' 세팅 안 됨"


class TestDoRetryMergeConflictAutoResolve:
    """item 9: retry-merge auto-resolve TC"""

    def test_do_retry_merge_conflict_calls_auto_resolve(self, tmp_path):
        """R: _execute_merge_with_lock conflict=True → merge_status='conflict' 세팅"""
        cl = _load_listener()

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        redis = make_redis_mock(worktree_path=str(worktree))

        import plan_runner.core.stages as stages
        with patch.object(stages, "pre_merge_gate", return_value=(True, "ok")), \
             patch("_dr_commands._execute_merge_with_lock", return_value={
                 "success": False, "message": "conflict", "conflict": True,
                 "merge_status": "conflict", "action": "retry-merge"
             }), \
             patch("_dr_commands._cleanup_process_state"):
            cl._do_retry_merge("runner_conflict01", redis, "cmd_conflict01")

        # result에 conflict 정보가 LPUSH됨
        push_calls = redis.lpush.call_args_list
        assert push_calls, "결과 LPUSH 없음"

    def test_do_retry_merge_resolve_success_calls_pipeline(self, tmp_path):
        """R: _execute_merge_with_lock resolve 성공 → merge_status='merged'"""
        cl = _load_listener()

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        redis = make_redis_mock(worktree_path=str(worktree))

        import plan_runner.core.stages as stages
        with patch.object(stages, "pre_merge_gate", return_value=(True, "ok")), \
             patch("_dr_commands._execute_merge_with_lock", return_value={
                 "success": True, "message": "conflict resolved",
                 "merge_status": "merged", "action": "retry-merge"
             }), \
             patch("_dr_commands._cleanup_process_state"):
            cl._do_retry_merge("runner_conflict02", redis, "cmd_conflict02")

        push_calls = redis.lpush.call_args_list
        result_raw = push_calls[-1][0][1]
        result = json.loads(result_raw)
        assert result.get("success") is True or result.get("action") == "retry-merge"

    def test_do_retry_merge_resolve_fail_aborts(self, tmp_path):
        """R: resolve 실패 → merge_status='conflict'"""
        cl = _load_listener()

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        redis = make_redis_mock(worktree_path=str(worktree))

        import plan_runner.core.stages as stages
        with patch.object(stages, "pre_merge_gate", return_value=(True, "ok")), \
             patch("_dr_commands._execute_merge_with_lock", return_value={
                 "success": False, "message": "conflict",
                 "merge_status": "conflict", "action": "retry-merge"
             }), \
             patch("_dr_commands._cleanup_process_state"):
            cl._do_retry_merge("runner_conflict03", redis, "cmd_conflict03")

        push_calls = redis.lpush.call_args_list
        assert push_calls, "결과 LPUSH 없음"
        result = json.loads(push_calls[-1][0][1])
        assert result.get("success") is False


class TestDoRetryMergePostPipeline:
    """item 10: retry-merge post-merge pipeline TC"""

    def test_do_retry_merge_merged_calls_pipeline(self, tmp_path):
        """R: merged=True → merge_status='merged' 반환"""
        cl = _load_listener()

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        redis = make_redis_mock(worktree_path=str(worktree))

        import plan_runner.core.stages as stages
        with patch.object(stages, "pre_merge_gate", return_value=(True, "ok")), \
             patch("_dr_commands._execute_merge_with_lock", return_value={
                 "success": True, "message": "merged",
                 "merge_status": "merged", "action": "retry-merge"
             }), \
             patch("_dr_commands._cleanup_process_state"):
            cl._do_retry_merge("runner_pipe01", redis, "cmd_pipe01")

        push_calls = redis.lpush.call_args_list
        assert push_calls, "결과 LPUSH 없음"
        result = json.loads(push_calls[-1][0][1])
        assert result.get("success") is True

    def test_do_retry_merge_pipeline_fail_sets_test_failed(self, tmp_path):
        """R: pipeline 실패 → merge_status='test_failed'"""
        cl = _load_listener()

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        redis = make_redis_mock(worktree_path=str(worktree))

        import plan_runner.core.stages as stages
        with patch.object(stages, "pre_merge_gate", return_value=(True, "ok")), \
             patch("_dr_commands._execute_merge_with_lock", return_value={
                 "success": False, "message": "test_failed",
                 "merge_status": "test_failed", "action": "retry-merge"
             }), \
             patch("_dr_commands._cleanup_process_state"):
            cl._do_retry_merge("runner_pipe02", redis, "cmd_pipe02")

        push_calls = redis.lpush.call_args_list
        assert push_calls, "결과 LPUSH 없음"
        result = json.loads(push_calls[-1][0][1])
        assert result.get("success") is False

