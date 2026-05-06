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

# plan_runner.core.stages mock (모듈이 없는 환경 대비)
_mock_stages_mod = types.ModuleType("plan_runner.core.stages")
_mock_stages_mod.pre_merge_gate = MagicMock(return_value=(True, "OK"))
_mock_stages_mod.auto_commit_stage = MagicMock(return_value=True)
sys.modules.setdefault("plan_runner.core.stages", _mock_stages_mod)
sys.modules.setdefault("plan_runner", types.ModuleType("plan_runner"))
sys.modules.setdefault("plan_runner.core", types.ModuleType("plan_runner.core"))

_SCRIPT_PATH = Path(__file__).parent.parent.parent / "scripts" / "plan_runner" / "dev-runner-command-listener.py"

_mock_noise = types.ModuleType("listener_noise_filter")
_mock_noise.NOISE_BLOCK_MARKERS = []
_mock_noise.is_noise_line = lambda line: False

RESULTS_KEY = "plan-runner:command_results"
ACTIVE_RUNNERS_KEY = "plan-runner:active_runners"
_LOAD_COUNTER = 0


def _load_listener():
    global _LOAD_COUNTER
    _LOAD_COUNTER += 1
    module_name = f"_listener_e2e_{_LOAD_COUNTER}"
    sys.modules["listener_noise_filter"] = _mock_noise
    spec = importlib.util.spec_from_file_location(module_name, _SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    mod._running_processes = {}
    mod._running_log_files = {}
    mod._stream_threads = {}
    spec.loader.exec_module(mod)
    if hasattr(mod, "_refresh_state_refs"):
        mod._refresh_state_refs(reset=True)
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


def test_load_listener_resets_global_state_between_imports():
    """R: _load_listener() 반복 호출 시 전역 상태 dict가 누적되지 않아야 한다."""
    first = _load_listener()
    first._running_processes["old"] = object()
    first._stream_threads["old"] = object()

    second = _load_listener()

    assert second._running_processes == {}
    assert second._stream_threads == {}
    assert "old" not in second._running_processes
    assert "old" not in second._stream_threads


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
        runner_id = "t-mretry-e2e01"
        command_id = "cmd-e2e-001"
        redis = make_redis_mock(worktree_path=str(worktree))
        merge_result = make_merge_result(merged=True, tests_passed=True)

        # retry_merge는 background thread를 시작하므로 테스트에서는 thread 실행을 막아야
        # 잔류 스레드(600s 대기)로 인한 hang/메모리 급증을 방지할 수 있다.
        with patch("_dr_commands.threading.Thread") as mock_thread:
            # retry_merge 직접 호출 (accepted → redis.lpush로 반환)
            command = {"action": "retry-merge", "runner_id": runner_id, "command_id": command_id}
            cl.retry_merge(command, redis)

            mock_thread.assert_called_once()
            mock_thread.return_value.start.assert_called_once()

        # accepted가 Redis에 LPUSH됐는지 확인
        lpush_calls = redis.lpush.call_args_list
        assert lpush_calls, "accepted LPUSH 없음"
        pushed_raw = lpush_calls[0][0][1]
        pushed = json.loads(pushed_raw)
        assert pushed.get("success") is True
        assert pushed.get("action") == "retry-merge"

    @pytest.mark.memory_spike_repro
    def test_retry_merge_full_flow_do_retry(self, tmp_path):
        """
        E2E: _do_retry_merge() 직접 → merge_status 전이 + cleanup 확인
        queued → merging → merged
        (_execute_merge_with_lock 내 subprocess.run을 mock하여 exit_code=0 반환)
        """
        cl = _load_listener()

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        runner_id = "t-mretry-e2e02"
        redis = make_redis_mock(worktree_path=str(worktree))

        merge_status_sequence = []
        publish_calls = []

        def track_set(key, value, *args, **kwargs):
            if "merge_status" in key:
                merge_status_sequence.append(value)
            return True

        redis.set.side_effect = track_set
        redis.publish.side_effect = lambda channel, payload: publish_calls.append((channel, payload))

        import merge_queue as mq

        proc_mock = MagicMock()
        proc_mock.returncode = 0  # exit_code=0 → merged

        with patch.object(mq, "acquire_merge_turn", return_value=True), \
             patch.object(mq, "release_merge_turn"), \
             patch("subprocess.run", return_value=proc_mock), \
             patch("_dr_commands._cleanup_process_state") as mock_cleanup:
            cl._do_retry_merge(runner_id, redis, "cmd-e2e-002")

        # merge_status 전이: queued → merging → merged
        assert "queued" in merge_status_sequence
        assert "merging" in merge_status_sequence
        assert "merged" in merge_status_sequence
        mock_cleanup.assert_called_once()
        merge_publish_calls = [
            c for c in publish_calls
            if c[0] == f"plan-runner:merge-log:{runner_id}"
        ]
        assert merge_publish_calls == [
            (f"plan-runner:merge-log:{runner_id}", "__MERGE_COMPLETED__")
        ]


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

        with patch("_dr_commands.threading.Thread") as mock_thread:
            cl.direct_merge(command, redis)
            mock_thread.assert_called_once()
            mock_thread.return_value.start.assert_called_once()

        # accepted가 Redis에 LPUSH됐는지 확인
        lpush_calls = redis.lpush.call_args_list
        assert lpush_calls, "accepted LPUSH 없음"
        pushed_raw = lpush_calls[0][0][1]
        pushed = json.loads(pushed_raw)
        assert pushed.get("success") is True
        assert pushed.get("action") == "direct-merge"

    @pytest.mark.memory_spike_repro
    def test_direct_merge_full_flow_do_direct(self, tmp_path):
        """
        E2E: _do_direct_merge() 직접 → 임시 dm- runner_id + Redis 키 + active_runners + _do_inline_merge 호출
        """
        cl = _load_listener()

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        branch = "runner/e2e-test2"
        redis = make_redis_mock()

        with patch("_dr_commands._do_inline_merge") as mock_inline:
            cl._do_direct_merge(branch, str(worktree), None, redis, "cmd-e2e-004")

        mock_inline.assert_called_once()
        runner_id_used = mock_inline.call_args[0][0]
        assert runner_id_used.startswith("dm-"), f"임시 runner_id 형식 오류: {runner_id_used}"

        sadd_calls = [str(c) for c in redis.sadd.call_args_list]
        assert any(ACTIVE_RUNNERS_KEY in c for c in sadd_calls), "active_runners SADD 없음"


class TestDirectMergeConflictResolverCrashSafe:
    """E2E: direct-merge 시 plan-runner resolve 실패 → conflict 유지 확인"""

    def test_direct_merge_conflict_resolver_crash_safe(self, tmp_path):
        """
        E2E: _do_direct_merge → _do_inline_merge → MergeWorkflow conflict →
        _launch_conflict_resolver_process 실패 (plan-runner resolve 실패 시뮬레이션) →
        merge_status="conflict" 전이 + 크래시 없음

        (구버전: ConflictResolver.try_resolve mock → 신버전: _launch_conflict_resolver_process mock)
        """
        cl = _load_listener()

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        branch = "plan/test"
        redis = make_redis_mock(worktree_path=str(worktree))

        # merge_status 전이 추적
        merge_status_sequence = []

        def track_set(key, value, *args, **kwargs):
            if "merge_status" in key:
                merge_status_sequence.append(value)
            return True

        redis.set.side_effect = track_set

        # redis.get에 branch도 반환하도록 확장
        original_get = redis.get.side_effect

        def extended_get(key):
            if "branch" in key:
                return branch
            if "worktree_path" in key:
                return str(worktree)
            return original_get(key) if original_get else None

        redis.get.side_effect = extended_get

        mock_merge_lock = types.ModuleType("merge_queue")
        mock_merge_lock.acquire_merge_turn = MagicMock(return_value=True)
        mock_merge_lock.release_merge_turn = MagicMock(return_value=True)
        mock_merge_lock._get_repo_id = MagicMock(return_value="monitor-page")

        with patch.dict(sys.modules, {"merge_queue": mock_merge_lock}), \
             patch("_dr_merge._check_stale_merge_gate", return_value=(None, None)), \
             patch("subprocess.run", return_value=MagicMock(returncode=3)), \
             patch("_dr_merge._launch_conflict_resolver_process",
                         return_value={"success": False, "message": "resolve 실패 시뮬레이션", "merge_status": "conflict", "conflict": True}), \
             patch("_dr_plan_runner._cleanup_process_state", MagicMock()):

            # 크래시 없이 실행 완료되어야 함
            cl._do_inline_merge("dm-crash-test", redis)

        # merge_status가 "conflict"로 전이
        assert "conflict" in merge_status_sequence, \
            f"merge_status에 'conflict' 없음: {merge_status_sequence}"
        # 크래시 없이 여기까지 도달 = success

    def test_retry_merge_safe_doc_conflict_transitions_to_merged(self, tmp_path):
        """E2E: retry-merge에서 safe-doc conflict는 merged로 전이된다."""
        cl = _load_listener()

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        branch = "plan/test"
        redis = make_redis_mock(worktree_path=str(worktree))

        merge_status_sequence = []

        def track_set(key, value, *args, **kwargs):
            if "merge_status" in key:
                merge_status_sequence.append(value)
            return True

        redis.set.side_effect = track_set
        original_get = redis.get.side_effect

        def extended_get(key):
            if "branch" in key:
                return branch
            if "worktree_path" in key:
                return str(worktree)
            return original_get(key) if original_get else None

        redis.get.side_effect = extended_get

        mock_merge_lock = types.ModuleType("merge_queue")
        mock_merge_lock.acquire_merge_turn = MagicMock(return_value=True)
        mock_merge_lock.release_merge_turn = MagicMock(return_value=True)
        mock_merge_lock._get_repo_id = MagicMock(return_value="monitor-page")

        with patch.dict(sys.modules, {"merge_queue": mock_merge_lock}), \
             patch("_dr_merge._check_stale_merge_gate", return_value=(None, None)), \
             patch("subprocess.run", return_value=MagicMock(returncode=3)), \
             patch(
                 "_dr_merge._launch_conflict_resolver_process",
                 return_value={"success": True, "message": "safe-doc auto-resolved", "merge_status": "merged"},
             ), \
             patch("_dr_merge._handle_post_merge_done", return_value={"success": True, "status": "done_called"}), \
             patch("_dr_commands._cleanup_process_state", MagicMock()):
            cl._do_retry_merge("retry-safe-doc", redis, "cmd-retry-safe-doc")

        assert "resolving" in merge_status_sequence
        assert "merged" in merge_status_sequence


class TestRetryMergeExitCode2AutoFix:
    """E2E: retry-merge → exit_code=2 → _launch_auto_impl_post_merge_process 자동 트리거"""

    @pytest.mark.e2e
    def test_retry_merge_exit_code_2_triggers_auto_fix_e2e(self, tmp_path):
        """E2E: _do_retry_merge → _execute_merge_with_lock(exit_code=2) →
        _launch_auto_impl_post_merge_process 호출 → success=True → merge_status='merged'
        """
        cl = _load_listener()

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        plan_file = "docs/plan/test.md"

        redis = make_redis_mock(worktree_path=str(worktree), plan_file=plan_file)

        merge_status_sequence = []

        def track_set(key, value, *args, **kwargs):
            if "merge_status" in key:
                merge_status_sequence.append(value)
            return True

        redis.set.side_effect = track_set

        mock_lock_mod = types.ModuleType("merge_queue")
        mock_lock_mod.acquire_merge_turn = MagicMock(return_value=True)
        mock_lock_mod.release_merge_turn = MagicMock()
        mock_lock_mod._get_repo_id = MagicMock(return_value="monitor-page")

        with patch.dict(sys.modules, {"merge_queue": mock_lock_mod}), \
             patch("subprocess.run", return_value=MagicMock(returncode=2)), \
             patch("_dr_merge._launch_auto_impl_post_merge_process",
                          return_value={"success": True, "message": "fixed"}) as mock_fix, \
             patch("_dr_merge._handle_post_merge_done"), \
             patch("_dr_commands._cleanup_process_state", MagicMock()):

            cl._do_retry_merge("r-e2e-exit2", redis, "cmd-e2e-exit2")

        # _launch_auto_impl_post_merge_process 호출 확인
        mock_fix.assert_called_once()

        # merge_status 전이: merging → fixing → merged
        assert "fixing" in merge_status_sequence, \
            f"merge_status에 'fixing' 없음: {merge_status_sequence}"
        assert "merged" in merge_status_sequence, \
            f"merge_status에 'merged' 없음: {merge_status_sequence}"
