"""
TC E2E: retry_merge / direct_merge end-to-end 흐름
execute_command → 함수 → MergeWorkflow mock → merge_status 전이 확인
"""
import json
import sys
import importlib
import importlib.util
import types
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

_SCRIPT_PATH = Path(__file__).parent.parent.parent / "scripts" / "dev-runner-command-listener.py"

_mock_noise = types.ModuleType("listener_noise_filter")
_mock_noise.NOISE_BLOCK_MARKERS = []
_mock_noise.is_noise_line = lambda line: False

RESULTS_KEY = "plan-runner:command_results"
ACTIVE_RUNNERS_KEY = "plan-runner:active_runners"


def _load_listener():
    sys.modules["listener_noise_filter"] = _mock_noise
    spec = importlib.util.spec_from_file_location("_listener_e2e", _SCRIPT_PATH)
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
    redis.sadd.return_value = 1
    return redis


def make_merge_result(merged=True, tests_passed=True, conflict=False, message="ok"):
    result = MagicMock()
    result.merged = merged
    result.tests_passed = tests_passed
    result.conflict = conflict
    result.message = message
    return result


class TestRetryMergeFullFlow:
    def test_retry_merge_full_flow(self, tmp_path):
        """
        E2E: execute_command(action=retry-merge) → retry_merge() →
        _do_retry_merge() (스레드) → MergeWorkflow mock → merge_status 전이
        queued → merging → merged + cleanup 호출
        """
        cl = _load_listener()

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        runner_id = "runner-e2e-01"
        command_id = "cmd-e2e-001"
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

            # retry_merge 직접 호출 (accepted → redis.lpush로 반환)
            command = {"action": "retry-merge", "runner_id": runner_id, "command_id": command_id}
            cl.retry_merge(command, redis)

        # accepted가 Redis에 LPUSH됐는지 확인
        lpush_calls = redis.lpush.call_args_list
        assert lpush_calls, "accepted LPUSH 없음"
        pushed_raw = lpush_calls[0][0][1]
        pushed = json.loads(pushed_raw)
        assert pushed.get("success") is True
        assert pushed.get("action") == "retry-merge"

    def test_retry_merge_full_flow_do_retry(self, tmp_path):
        """
        E2E: _do_retry_merge() 직접 → merge_status 전이 + cleanup 확인
        queued → merging → merged
        """
        cl = _load_listener()

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        runner_id = "runner-e2e-02"
        redis = make_redis_mock(worktree_path=str(worktree))
        merge_result = make_merge_result(merged=True, tests_passed=True)

        merge_status_sequence = []

        def track_set(key, value, *args, **kwargs):
            if "merge_status" in key:
                merge_status_sequence.append(value)
            return True

        redis.set.side_effect = track_set

        import merge_lock as ml
        with patch.object(ml, "acquire_merge_lock", return_value=True), \
             patch.object(ml, "release_merge_lock"), \
             patch("merge_workflow.MergeWorkflow") as mock_wf_cls, \
             patch.object(cl, "_cleanup_process_state") as mock_cleanup:
            mock_wf = MagicMock()
            mock_wf.run.return_value = merge_result
            mock_wf_cls.return_value = mock_wf

            cl._do_retry_merge(runner_id, redis, "cmd-e2e-002")

        # merge_status 전이: queued → merging → merged
        assert "queued" in merge_status_sequence
        assert "merging" in merge_status_sequence
        assert "merged" in merge_status_sequence
        mock_cleanup.assert_called_once()


class TestDirectMergeFullFlow:
    def test_direct_merge_full_flow(self, tmp_path):
        """
        E2E: execute_command(action=direct-merge, branch=...) →
        direct_merge() → _do_direct_merge() → 임시 runner 생성 → _do_inline_merge mock
        """
        cl = _load_listener()

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        branch = "runner/e2e-test"
        redis = make_redis_mock()

        command = {
            "action": "direct-merge",
            "branch": branch,
            "worktree_path": str(worktree),
            "command_id": "cmd-e2e-003",
        }

        with patch.object(cl, "_do_inline_merge") as mock_inline:
            cl.direct_merge(command, redis)

        # accepted가 Redis에 LPUSH됐는지 확인
        lpush_calls = redis.lpush.call_args_list
        assert lpush_calls, "accepted LPUSH 없음"
        pushed_raw = lpush_calls[0][0][1]
        pushed = json.loads(pushed_raw)
        assert pushed.get("success") is True
        assert pushed.get("action") == "direct-merge"

    def test_direct_merge_full_flow_do_direct(self, tmp_path):
        """
        E2E: _do_direct_merge() 직접 → 임시 dm- runner_id + Redis 키 + active_runners + _do_inline_merge 호출
        """
        cl = _load_listener()

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        branch = "runner/e2e-test2"
        redis = make_redis_mock()

        with patch.object(cl, "_do_inline_merge") as mock_inline:
            cl._do_direct_merge(branch, str(worktree), None, redis, "cmd-e2e-004")

        mock_inline.assert_called_once()
        runner_id_used = mock_inline.call_args[0][0]
        assert runner_id_used.startswith("dm-"), f"임시 runner_id 형식 오류: {runner_id_used}"

        sadd_calls = [str(c) for c in redis.sadd.call_args_list]
        assert any(ACTIVE_RUNNERS_KEY in c for c in sadd_calls), "active_runners SADD 없음"
