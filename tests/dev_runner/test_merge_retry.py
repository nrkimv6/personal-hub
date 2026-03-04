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

_SCRIPT_PATH = Path(__file__).parent.parent.parent / "scripts" / "dev-runner-command-listener.py"

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
        """R(Right): merge 성공 시 acquire_merge_lock + release_merge_lock 모두 호출"""
        cl = _load_listener()

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        redis = make_redis_mock(worktree_path=str(worktree))
        merge_result = make_merge_result(merged=True, tests_passed=True)

        # 로컬 임포트(`from merge_lock import ...`)는 merge_lock 모듈 자체를 패치
        import merge_lock as ml
        with patch.object(ml, "acquire_merge_lock", return_value=True) as mock_acquire, \
             patch.object(ml, "release_merge_lock") as mock_release, \
             patch("merge_workflow.MergeWorkflow") as mock_wf_cls, \
             patch.object(cl, "_cleanup_process_state"):
            mock_wf = MagicMock()
            mock_wf.run.return_value = merge_result
            mock_wf_cls.return_value = mock_wf
            cl._do_retry_merge("runner01", redis, "cmd001")

        mock_acquire.assert_called_once()
        mock_release.assert_called()

    def test_do_retry_merge_publishes_logs(self, tmp_path):
        """R(Right): 진행 중 plan-runner:logs:{runner_id} 채널에 [MERGE] 로그 발행"""
        cl = _load_listener()

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        runner_id = "runner02"
        redis = make_redis_mock(worktree_path=str(worktree))
        merge_result = make_merge_result(merged=True, tests_passed=True)

        import merge_lock as ml
        with patch.object(ml, "acquire_merge_lock", return_value=True), \
             patch.object(ml, "release_merge_lock"), \
             patch("merge_workflow.MergeWorkflow") as mock_wf_cls, \
             patch.object(cl, "_cleanup_process_state"):
            mock_wf = MagicMock()
            mock_wf.run.return_value = merge_result
            mock_wf_cls.return_value = mock_wf
            cl._do_retry_merge(runner_id, redis, "cmd002")

        log_channel = f"{LOG_CHANNEL_PREFIX}:{runner_id}"
        publish_calls = redis.publish.call_args_list
        assert any(log_channel in str(c) for c in publish_calls), "로그 채널에 publish 없음"
        assert any("[MERGE]" in str(c) for c in publish_calls if log_channel in str(c)), "[MERGE] 로그 없음"

    def test_do_retry_merge_cleanup_on_merged(self, tmp_path):
        """R(Right): merge 성공 시 _cleanup_process_state 호출됨"""
        cl = _load_listener()

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        redis = make_redis_mock(worktree_path=str(worktree))
        merge_result = make_merge_result(merged=True, tests_passed=True)

        import merge_lock as ml
        with patch.object(ml, "acquire_merge_lock", return_value=True), \
             patch.object(ml, "release_merge_lock"), \
             patch("merge_workflow.MergeWorkflow") as mock_wf_cls, \
             patch.object(cl, "_cleanup_process_state") as mock_cleanup:
            mock_wf = MagicMock()
            mock_wf.run.return_value = merge_result
            mock_wf_cls.return_value = mock_wf
            cl._do_retry_merge("runner03", redis, "cmd003")

        mock_cleanup.assert_called_once_with("runner03", redis)

    def test_do_retry_merge_preserves_worktree_on_conflict(self, tmp_path):
        """B(Boundary): conflict 시 cleanup 호출 + merge_status='conflict' 세팅"""
        cl = _load_listener()

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        redis = make_redis_mock(worktree_path=str(worktree))
        merge_result = make_merge_result(merged=False, tests_passed=False, conflict=True, message="conflict!")

        import merge_lock as ml
        with patch.object(ml, "acquire_merge_lock", return_value=True), \
             patch.object(ml, "release_merge_lock"), \
             patch("merge_workflow.MergeWorkflow") as mock_wf_cls, \
             patch.object(cl, "_cleanup_process_state") as mock_cleanup:
            mock_wf = MagicMock()
            mock_wf.run.return_value = merge_result
            mock_wf_cls.return_value = mock_wf
            cl._do_retry_merge("runner04", redis, "cmd004")

        mock_cleanup.assert_called_once()
        set_calls = [str(c) for c in redis.set.call_args_list]
        assert any("conflict" in c for c in set_calls), "merge_status='conflict' 세팅 안 됨"

    def test_do_retry_merge_lock_timeout_sets_error(self, tmp_path):
        """E(Error): acquire_merge_lock False → merge_status='error' + cleanup"""
        cl = _load_listener()

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        redis = make_redis_mock(worktree_path=str(worktree))

        import merge_lock as ml
        with patch.object(ml, "acquire_merge_lock", return_value=False), \
             patch.object(ml, "release_merge_lock"), \
             patch.object(cl, "_cleanup_process_state") as mock_cleanup:
            cl._do_retry_merge("runner05", redis, "cmd005")

        set_calls = [str(c) for c in redis.set.call_args_list]
        assert any("error" in c for c in set_calls), "merge_status='error' 세팅 안 됨"
        mock_cleanup.assert_called_once()

    def test_do_retry_merge_no_worktree_returns_error(self, tmp_path):
        """E(Error): worktree_path Redis 키 없을 때 에러 결과 LPUSH"""
        cl = _load_listener()

        redis = make_redis_mock(worktree_path=None)

        with patch.object(cl, "_cleanup_process_state"):
            cl._do_retry_merge("runner06", redis, "cmd006")

        push_calls = redis.lpush.call_args_list
        assert push_calls, "결과 LPUSH 없음"
        result_raw = push_calls[-1][0][1]
        result = json.loads(result_raw)
        assert result.get("success") is False
