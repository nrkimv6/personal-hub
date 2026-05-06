"""
TC: unit tests for _do_inline_merge / _do_retry_merge subprocess replacement.

Phase T1: verify plan-runner post-merge subprocess invocation patterns.
- 12. test_do_inline_merge_calls_plan_runner_subprocess_R
- 13. test_do_inline_merge_subprocess_exit0_sets_merged_R
- 14. test_do_inline_merge_subprocess_exit1_sets_error_E
- 15. test_do_inline_merge_subprocess_exit3_sets_conflict_B
- 16. test_do_inline_merge_cleanup_always_runs_R
- 17. test_do_inline_merge_no_restart_after_merge_B
- 18. test_do_retry_merge_calls_plan_runner_subprocess_R
- 19. test_deleted_functions_not_exist_R
"""
import importlib.util
import json
import subprocess
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import fakeredis
import pytest

_SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
_PLAN_RUNNER_DIR = _SCRIPTS_DIR / "plan_runner"
if str(_PLAN_RUNNER_DIR) not in sys.path:
    sys.path.insert(0, str(_PLAN_RUNNER_DIR))

_SCRIPT_PATH = _PLAN_RUNNER_DIR / "dev-runner-command-listener.py"
_mock_noise = types.ModuleType("listener_noise_filter")
_mock_noise.NOISE_BLOCK_MARKERS = []
_mock_noise.is_noise_line = lambda line: False

RUNNER_KEY_PREFIX = "plan-runner:runners"


def _load_listener():
    sys.modules["listener_noise_filter"] = _mock_noise
    spec = importlib.util.spec_from_file_location("_listener_pmp", _SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    mod._running_processes = {}
    mod._running_log_files = {}
    mod._stream_threads = {}
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def cl():
    return _load_listener()


@pytest.fixture(scope="module")
def dr_merge_mod(cl):  # noqa: F811 - cl loads _dr_merge into sys.modules.
    """Return the _dr_merge module loaded by the listener."""
    return sys.modules["_dr_merge"]


@pytest.fixture
def fake_redis():
    return fakeredis.FakeRedis(decode_responses=True)


def _make_redis_mock(worktree_path=None, plan_file=None, branch=None):
    redis = MagicMock()

    def redis_get(key):
        if "worktree_path" in key:
            return str(worktree_path) if worktree_path else None
        if "plan_file" in key:
            return plan_file
        if "branch" in key:
            return branch
        if "merge_requested" in key:
            return "1"
        return None

    redis.get.side_effect = redis_get
    redis.set = MagicMock()
    redis.delete = MagicMock()
    redis.publish = MagicMock()
    redis.lrange = MagicMock(return_value=[])
    redis.lpush = MagicMock()
    redis.expire = MagicMock()
    redis.srem = MagicMock()
    redis.smembers = MagicMock(return_value=set())
    return redis


def _merge_lock_patch():
    """Mock the merge_queue module with acquire=True and a no-op release."""
    mock_lock_mod = types.ModuleType("merge_queue")
    mock_lock_mod.acquire_merge_turn = MagicMock(return_value=True)
    mock_lock_mod.release_merge_turn = MagicMock()
    mock_lock_mod._get_repo_id = MagicMock(return_value="repo-test")
    return patch.dict("sys.modules", {"merge_queue": mock_lock_mod})


# Phase T1: subprocess replacement pattern tests

class TestDoInlineMergeSubprocess:
    def test_do_inline_merge_calls_plan_runner_subprocess_R(self, cl, tmp_path):
        """R(Right): _do_inline_merge calls subprocess.run with plan_runner post-merge."""
        redis = _make_redis_mock()
        proc_result = MagicMock()
        proc_result.returncode = 0

        with _merge_lock_patch(), \
             patch("_dr_stream_cleanup._cleanup_process_state"), \
             patch("subprocess.run", return_value=proc_result) as mock_run:
            cl._do_inline_merge("r1", redis)

        post_merge_calls = [
            c for c in mock_run.call_args_list
            if "plan_runner" in str(c) and "post-merge" in str(c)
        ]
        assert len(post_merge_calls) >= 1, f"plan_runner post-merge ?몄텧???놁쓬: {mock_run.call_args_list}"
        cmd = post_merge_calls[0][0][0]
        assert "-m" in cmd
        assert "plan_runner" in cmd
        assert "post-merge" in cmd
        assert "--runner-id" in cmd
        assert "r1" in cmd

    def test_do_inline_merge_subprocess_exit0_sets_merged_R(self, cl, tmp_path):
        """R(Right): subprocess returncode=0 sets merge_status='merged'."""
        redis = _make_redis_mock()
        set_calls = []
        redis.set.side_effect = lambda k, v: set_calls.append((k, v))

        proc_result = MagicMock()
        proc_result.returncode = 0

        with _merge_lock_patch(), \
             patch("_dr_stream_cleanup._cleanup_process_state"), \
             patch("subprocess.run", return_value=proc_result):
            cl._do_inline_merge("r_exit0", redis)

        status_values = [v for k, v in set_calls if "merge_status" in k]
        assert "merged" in status_values

    def test_do_inline_merge_subprocess_exit1_sets_error_E(self, cl, tmp_path):
        """E(Error): subprocess returncode=1 sets merge_status='error'."""
        redis = _make_redis_mock()
        set_calls = []
        redis.set.side_effect = lambda k, v: set_calls.append((k, v))

        proc_result = MagicMock()
        proc_result.returncode = 1

        with _merge_lock_patch(), \
             patch("_dr_stream_cleanup._cleanup_process_state"), \
             patch("_dr_merge._launch_general_merge_resolver_process", return_value={"success": False, "message": "fail"}), \
             patch("subprocess.run", return_value=proc_result):
            cl._do_inline_merge("r_exit1", redis)

        status_values = [v for k, v in set_calls if "merge_status" in k]
        assert "error" in status_values
        assert "merged" not in status_values

    def test_do_inline_merge_subprocess_exit3_sets_conflict_B(self, cl, tmp_path):
        """B(Boundary): subprocess returncode=3 sets merge_status='conflict'."""
        redis = _make_redis_mock()
        set_calls = []
        redis.set.side_effect = lambda k, v: set_calls.append((k, v))

        proc_result = MagicMock()
        proc_result.returncode = 3

        with _merge_lock_patch(), \
             patch("_dr_stream_cleanup._cleanup_process_state"), \
             patch("subprocess.run", return_value=proc_result), \
             patch("_dr_merge._launch_conflict_resolver_process",
                   return_value={"success": False, "message": "mocked", "merge_status": "conflict", "conflict": True}):
            cl._do_inline_merge("r_exit3", redis)

        status_values = [v for k, v in set_calls if "merge_status" in k]
        assert "conflict" in status_values

    def test_do_inline_merge_cleanup_always_runs_R(self, cl, tmp_path):
        """R(Right): _cleanup_process_state runs for subprocess success and failure."""
        # Success case.
        redis_ok = _make_redis_mock()
        proc_ok = MagicMock()
        proc_ok.returncode = 0

        with _merge_lock_patch(), \
             patch("_dr_stream_cleanup._cleanup_process_state") as mock_cleanup_ok, \
             patch("subprocess.run", return_value=proc_ok):
            cl._do_inline_merge("r_cleanup_ok", redis_ok)

        mock_cleanup_ok.assert_called_once()

        # Failure case.
        redis_fail = _make_redis_mock()
        proc_fail = MagicMock()
        proc_fail.returncode = 1

        with _merge_lock_patch(), \
             patch("_dr_stream_cleanup._cleanup_process_state") as mock_cleanup_fail, \
             patch("subprocess.run", return_value=proc_fail), \
             patch("_dr_merge._launch_general_merge_resolver_process",
                   return_value={"success": False, "message": "mocked"}):
            cl._do_inline_merge("r_cleanup_fail", redis_fail)

        mock_cleanup_fail.assert_called_once()

    def test_do_inline_merge_no_restart_after_merge_B(self, cl, tmp_path):
        """B(Boundary): restart_after_merge Redis keys are not set."""
        redis = _make_redis_mock()
        set_keys = []
        redis.set.side_effect = lambda k, v: set_keys.append(k)

        proc_result = MagicMock()
        proc_result.returncode = 0

        with _merge_lock_patch(), \
             patch("_dr_stream_cleanup._cleanup_process_state"), \
             patch("subprocess.run", return_value=proc_result):
            cl._do_inline_merge("r_no_restart", redis)

        assert not any("restart_after_merge" in k for k in set_keys)

    def test_do_inline_merge_merge_results_pushed_R(self, cl, tmp_path):
        """R(Right): completion pushes a result to plan-runner:merge-results."""
        redis = _make_redis_mock()
        lpush_calls = []
        redis.lpush.side_effect = lambda k, v: lpush_calls.append((k, v))

        proc_result = MagicMock()
        proc_result.returncode = 0

        with _merge_lock_patch(), \
             patch("_dr_stream_cleanup._cleanup_process_state"), \
             patch("subprocess.run", return_value=proc_result):
            cl._do_inline_merge("r_results", redis)

        pushed_keys = [k for k, v in lpush_calls]
        assert "plan-runner:merge-results" in pushed_keys

    def test_do_inline_merge_subprocess_exit0_emits_merge_completed_sentinel_R(self, cl, tmp_path):
        """R(Right): _do_inline_merge 성공 시 merge-log completed sentinel이 1회 publish된다."""
        redis = _make_redis_mock()
        publish_calls = []
        redis.publish.side_effect = lambda channel, payload: publish_calls.append((channel, payload))

        proc_result = MagicMock()
        proc_result.returncode = 0

        with _merge_lock_patch(), \
             patch("_dr_stream_cleanup._cleanup_process_state"), \
             patch("subprocess.run", return_value=proc_result):
            result = cl._do_inline_merge("r_inline_ok", redis)

        assert result is None
        merge_publish_calls = [
            c for c in publish_calls
            if c[0] == "plan-runner:merge-log:r_inline_ok"
        ]
        assert merge_publish_calls == [
            ("plan-runner:merge-log:r_inline_ok", "__MERGE_COMPLETED__")
        ]

    def test_do_inline_merge_subprocess_exit3_emits_merge_failed_sentinel_B(self, cl, tmp_path):
        """B(Boundary): _do_inline_merge conflict 시 merge-log merge_failed sentinel이 1회 publish된다."""
        redis = _make_redis_mock()
        publish_calls = []
        redis.publish.side_effect = lambda channel, payload: publish_calls.append((channel, payload))

        proc_result = MagicMock()
        proc_result.returncode = 3

        with _merge_lock_patch(), \
             patch("_dr_stream_cleanup._cleanup_process_state"), \
             patch("subprocess.run", return_value=proc_result), \
             patch("_dr_merge._launch_conflict_resolver_process",
                   return_value={"success": False, "message": "mocked", "merge_status": "conflict", "conflict": True}):
            cl._do_inline_merge("r_inline_fail", redis)

        merge_publish_calls = [
            c for c in publish_calls
            if c[0] == "plan-runner:merge-log:r_inline_fail"
        ]
        assert merge_publish_calls == [
            ("plan-runner:merge-log:r_inline_fail", "__MERGE_COMPLETED::merge_failed__")
        ]


class TestMergeCompletedSentinelEmission:
    def test_build_merge_completed_sentinel_success_R(self, dr_merge_mod):
        """R: 성공 결과는 __MERGE_COMPLETED__로 정규화된다."""
        sentinel = dr_merge_mod._build_merge_completed_sentinel({"success": True, "merge_status": "merged"})
        assert sentinel == "__MERGE_COMPLETED__"

    def test_build_merge_completed_sentinel_failure_B(self, dr_merge_mod):
        """B: 실패 결과는 __MERGE_COMPLETED::merge_failed__로 정규화된다."""
        sentinel = dr_merge_mod._build_merge_completed_sentinel({"success": False, "merge_status": "conflict"})
        assert sentinel == "__MERGE_COMPLETED::merge_failed__"

    def test_build_merge_completed_sentinel_conflict_like_success_B(self, dr_merge_mod):
        """B: success=True여도 merge_status=conflict면 merge_failed sentinel이어야 한다."""
        sentinel = dr_merge_mod._build_merge_completed_sentinel({"success": True, "merge_status": "conflict"})
        assert sentinel == "__MERGE_COMPLETED::merge_failed__"

    def test_publish_merge_completed_sentinel_success_to_merge_log_only_R(self, dr_merge_mod):
        """R: terminal success sentinel은 merge-log 채널에만 publish된다."""
        redis = _make_redis_mock()

        dr_merge_mod._publish_merge_completed_sentinel(
            "r_merge_ok",
            redis,
            {"success": True, "merge_status": "merged"},
        )

        redis.publish.assert_called_once_with(
            "plan-runner:merge-log:r_merge_ok",
            "__MERGE_COMPLETED__",
        )

    def test_publish_merge_completed_sentinel_failure_to_merge_log_only_B(self, dr_merge_mod):
        """B: terminal failure sentinel은 merge-log 채널에만 publish된다."""
        redis = _make_redis_mock()

        dr_merge_mod._publish_merge_completed_sentinel(
            "r_merge_fail",
            redis,
            {"success": False, "merge_status": "conflict"},
        )

        redis.publish.assert_called_once_with(
            "plan-runner:merge-log:r_merge_fail",
            "__MERGE_COMPLETED::merge_failed__",
        )

    def test_execute_merge_with_lock_publishes_success_merge_completed_sentinel_R(self, cl, tmp_path):
        """R: _execute_merge_with_lock 성공 경로에서 merge-log completed sentinel이 1회 publish된다."""
        redis = _make_redis_mock(worktree_path=tmp_path, plan_file=None, branch=None)
        publish_calls = []
        redis.publish.side_effect = lambda channel, payload: publish_calls.append((channel, payload))
        proc_result = MagicMock()
        proc_result.returncode = 0

        with _merge_lock_patch(), \
             patch("subprocess.run", return_value=proc_result):
            result = cl._execute_merge_with_lock("r_merge_ok", redis)

        assert result["success"] is True
        merge_publish_calls = [
            c for c in publish_calls
            if c[0] == "plan-runner:merge-log:r_merge_ok"
        ]
        assert merge_publish_calls == [
            ("plan-runner:merge-log:r_merge_ok", "__MERGE_COMPLETED__")
        ]

    def test_execute_merge_with_lock_publishes_failure_merge_completed_sentinel_B(self, cl, tmp_path):
        """B: _execute_merge_with_lock 실패 경로에서 merge-log merge_failed sentinel이 1회 publish된다."""
        redis = _make_redis_mock(worktree_path=tmp_path, plan_file=None, branch=None)
        publish_calls = []
        redis.publish.side_effect = lambda channel, payload: publish_calls.append((channel, payload))
        proc_result = MagicMock()
        proc_result.returncode = 3

        with _merge_lock_patch(), \
             patch("subprocess.run", return_value=proc_result), \
             patch("_dr_merge._launch_conflict_resolver_process", return_value={"success": False, "message": "mocked", "merge_status": "conflict", "conflict": True}):
            result = cl._execute_merge_with_lock("r_merge_fail", redis)

        assert result["success"] is False
        assert result["merge_status"] == "conflict"
        merge_publish_calls = [
            c for c in publish_calls
            if c[0] == "plan-runner:merge-log:r_merge_fail"
        ]
        assert merge_publish_calls == [
            ("plan-runner:merge-log:r_merge_fail", "__MERGE_COMPLETED::merge_failed__")
        ]

    def test_execute_merge_with_lock_retry_action_emits_merge_completed_sentinel_R(self, cl, tmp_path):
        """R(Right): retry-merge action도 동일한 merge-log completed sentinel 계약을 공유한다."""
        redis = _make_redis_mock(worktree_path=tmp_path, plan_file=None, branch=None)
        publish_calls = []
        redis.publish.side_effect = lambda channel, payload: publish_calls.append((channel, payload))
        proc_result = MagicMock()
        proc_result.returncode = 0

        with _merge_lock_patch(), \
             patch("subprocess.run", return_value=proc_result):
            result = cl._execute_merge_with_lock("r_retry_ok", redis, action_name="retry-merge")

        assert result["success"] is True
        assert result["action"] == "retry-merge"
        merge_publish_calls = [
            c for c in publish_calls
            if c[0] == "plan-runner:merge-log:r_retry_ok"
        ]
        assert merge_publish_calls == [
            ("plan-runner:merge-log:r_retry_ok", "__MERGE_COMPLETED__")
        ]

    def test_execute_merge_with_lock_blocks_stale_branch_before_subprocess_E(self, cl, tmp_path):
        """E: stale gate BLOCK이면 plan-runner post-merge subprocess를 실행하지 않는다."""
        redis = _make_redis_mock(worktree_path=tmp_path, plan_file=None, branch="plan/stale-branch")

        with _merge_lock_patch(), \
             patch("plan_worktree_helpers.get_branch_divergence", return_value=(301, 1)), \
             patch("subprocess.run") as mock_run:
            result = cl._execute_merge_with_lock("r_stale_block", redis)

        assert result["success"] is False
        assert result["merge_status"] == "error"
        assert result["reason"] == "stale_merge_blocked"
        assert result["stale_merge"] == {
            "risk": "BLOCK",
            "behind": 301,
            "ahead": 1,
            "branch": "plan/stale-branch",
        }
        post_merge_calls = [
            c for c in mock_run.call_args_list
            if "plan_runner" in str(c) and "post-merge" in str(c)
        ]
        assert post_merge_calls == []


class TestConflictResolverWrapperNormalization:
    def test_launch_conflict_resolver_process_normalizes_safe_doc_R(self, cl):
        """R: resolve subprocess 성공은 safe-doc auto-resolved + merged로 정규화된다."""
        dr_subprocess_mod = sys.modules["_dr_subprocess"]
        redis = _make_redis_mock()

        with patch.object(dr_subprocess_mod, "_run_subprocess_streaming", return_value={
            "success": True,
            "message": "RESOLVE 성공",
            "output": "[RESOLVE] safe-doc auto-resolved",
        }):
            result = dr_subprocess_mod._launch_conflict_resolver_process(
                runner_id="runner-safe-doc",
                branch="impl/test",
                worktree_path=Path("D:/tmp/worktree"),
                redis_client=redis,
            )

        assert result == {
            "success": True,
            "message": "safe-doc auto-resolved",
            "merge_status": "merged",
            "conflict": False,
        }

    def test_launch_conflict_resolver_process_normalizes_unsafe_conflict_B(self, cl):
        """B: unsafe/mixed 수동 해결 요구는 conflict 상태로 정규화된다."""
        dr_subprocess_mod = sys.modules["_dr_subprocess"]
        redis = _make_redis_mock()

        with patch.object(dr_subprocess_mod, "_run_subprocess_streaming", return_value={
            "success": False,
            "message": "mixed conflict requires manual resolution",
            "output": "[RESOLVE] unsafe/mixed conflict requires manual resolution",
        }):
            result = dr_subprocess_mod._launch_conflict_resolver_process(
                runner_id="runner-unsafe-conflict",
                branch="impl/test",
                worktree_path=Path("D:/tmp/worktree"),
                redis_client=redis,
            )

        assert result == {
            "success": False,
            "message": "unsafe conflict requires manual resolution",
            "merge_status": "conflict",
            "conflict": True,
        }


class TestDoRetryMergeSubprocess:
    def test_do_retry_merge_calls_plan_runner_subprocess_R(self, cl, tmp_path):
        """R(Right): _do_retry_merge calls subprocess.run with post-merge."""
        redis = _make_redis_mock(worktree_path=tmp_path)
        proc_result = MagicMock()
        proc_result.returncode = 0

        with _merge_lock_patch(), \
             patch("_dr_commands._cleanup_process_state"), \
             patch("subprocess.run", return_value=proc_result) as mock_run:
            cl._do_retry_merge("r_retry", redis, "cmd123")

        mock_run.assert_called()
        # subprocess.run may also be used for git rev-parse and worktree cleanup,
        # so filter for calls containing both plan_runner and post-merge.
        post_merge_calls = [
            c for c in mock_run.call_args_list
            if "plan_runner" in str(c) and "post-merge" in str(c)
        ]
        assert len(post_merge_calls) >= 1, f"plan_runner post-merge ?몄텧???놁쓬: {mock_run.call_args_list}"
        cmd = post_merge_calls[0][0][0]
        assert "--runner-id" in cmd
        assert "r_retry" in cmd

    def test_do_retry_merge_exit0_success_result_R(self, cl, tmp_path):
        """R(Right): exit_code=0 records result.success=True and pushes merge results."""
        redis = _make_redis_mock(worktree_path=tmp_path)
        lpush_calls = []
        redis.lpush.side_effect = lambda k, v: lpush_calls.append((k, v))

        proc_result = MagicMock()
        proc_result.returncode = 0

        with _merge_lock_patch(), \
             patch("_dr_commands._cleanup_process_state"), \
             patch("subprocess.run", return_value=proc_result):
            cl._do_retry_merge("r_retry_ok", redis, "cmd_ok")

        # Verify the pushed result for result_key.
        result_key = f"{cl.RESULTS_KEY}:cmd_ok"
        result_pushes = [v for k, v in lpush_calls if k == result_key]
        assert len(result_pushes) > 0
        result_data = json.loads(result_pushes[-1])
        assert result_data.get("success") is True

    def test_do_retry_merge_exit3_conflict_result_B(self, cl, tmp_path):
        """B(Boundary): exit_code=3 records result.conflict=True."""
        redis = _make_redis_mock(worktree_path=tmp_path)
        lpush_calls = []
        redis.lpush.side_effect = lambda k, v: lpush_calls.append((k, v))

        proc_result = MagicMock()
        proc_result.returncode = 3

        with _merge_lock_patch(), \
             patch("_dr_commands._cleanup_process_state"), \
             patch("subprocess.run", return_value=proc_result), \
             patch("_dr_merge._launch_conflict_resolver_process",
                   return_value={"success": False, "message": "mocked", "merge_status": "conflict", "conflict": True}):
            cl._do_retry_merge("r_retry_conflict", redis, "cmd_conflict")

        result_key = f"{cl.RESULTS_KEY}:cmd_conflict"
        result_pushes = [v for k, v in lpush_calls if k == result_key]
        assert len(result_pushes) > 0
        result_data = json.loads(result_pushes[-1])
        assert result_data.get("conflict") is True


class TestCleanupNoPopenCreated:
    def test_cleanup_runs_R_no_popen_created(self, cl):
        """T3 regression: launcher mocks must prevent Popen creation.

        In the _do_inline_merge failure case (returncode=1), mocking
        _launch_general_merge_resolver_process should prevent real
        subprocess.Popen calls.

        If this test fails with Popen.call_count > 0, the launcher mock is
        incomplete and a real process may be created, which can cause timeouts.
        """
        redis_fail = _make_redis_mock()
        proc_fail = MagicMock()
        proc_fail.returncode = 1

        with _merge_lock_patch(), \
             patch("_dr_stream_cleanup._cleanup_process_state"), \
             patch("subprocess.run", return_value=proc_fail), \
             patch("_dr_merge._launch_general_merge_resolver_process",
                   return_value={"success": False, "message": "mocked"}) as mock_launcher, \
             patch("subprocess.Popen") as mock_popen:
            cl._do_inline_merge("r_no_popen", redis_fail)

        # The launcher mock should prevent Popen from being called.
        assert mock_popen.call_count == 0, (
            f"subprocess.Popen??{mock_popen.call_count}???몄텧????"
            "_launch_general_merge_resolver_process mock??Popen 李⑤떒???ㅽ뙣?덇굅??"
            "launcher mock ?놁씠 ?ㅼ젣 ?꾨줈?몄뒪媛 ?앹꽦?섍퀬 ?덉쓬 (timeout ?щ컻 ?꾪뿕)"
        )
        # The launcher mock should be called exactly once.
        mock_launcher.assert_called_once()


class TestDeletedFunctions:
    def test_deleted_functions_not_exist_R(self, cl):
        """R(Right): deleted helpers are no longer module attributes."""
        assert not hasattr(cl, "_post_merge_pipeline"), \
            "_post_merge_pipeline should be deleted (replaced by plan-runner post-merge)"
        assert not hasattr(cl, "_restart_plan_runner_after_merge"), \
            "_restart_plan_runner_after_merge should be deleted"
        assert not hasattr(cl, "_resolve_todo_file"), \
            "_resolve_todo_file should be deleted"


# Phase T3: E2E-style tests with mocked subprocesses

class TestInlineMergeE2ESubprocessFlow:
    def test_inline_merge_e2e_subprocess_flow(self, cl):
        """T3-E2E: _do_inline_merge happy path with mocked subprocess exit_code=0.

        Verifies merge_status='merged', merge-results push, and cleanup call.
        """
        import fakeredis as _fakeredis
        import types as _types

        fake_r = _fakeredis.FakeRedis(decode_responses=True)
        runner_id = "e2e-inline-01"
        prefix = cl.RUNNER_KEY_PREFIX

        # Per-runner setup.
        fake_r.set(f"{prefix}:{runner_id}:merge_requested", "1")
        fake_r.set(f"{prefix}:{runner_id}:plan_file", "docs/plan/test.md")
        fake_r.set(f"{prefix}:{runner_id}:branch", "impl/test")
        fake_r.set(f"{prefix}:{runner_id}:worktree_path", "D:/tmp/wt")

        mock_lock_mod = _types.ModuleType("merge_queue")
        mock_lock_mod.acquire_merge_turn = MagicMock(return_value=True)
        mock_lock_mod.release_merge_turn = MagicMock()
        mock_lock_mod._get_repo_id = MagicMock(return_value="repo-test")

        proc_result = MagicMock()
        proc_result.returncode = 0

        with patch.dict("sys.modules", {"merge_queue": mock_lock_mod}), \
             patch("plan_worktree_helpers.get_branch_divergence", return_value=(0, 1)), \
             patch("_dr_merge._write_pre_merge_snapshot", return_value="logs/snapshot.md"), \
             patch("subprocess.run", return_value=proc_result), \
             patch("_dr_stream_cleanup._cleanup_process_state") as mock_cleanup:
            cl._do_inline_merge(runner_id, fake_r)

        # Verify merge_status = "merged".
        assert fake_r.get(f"{prefix}:{runner_id}:merge_status") == "merged"

        # Verify merge-results push.
        results = fake_r.lrange("plan-runner:merge-results", 0, 0)
        assert len(results) > 0
        result_data = json.loads(results[0])
        assert result_data["runner_id"] == runner_id
        assert result_data["success"] is True

        # Verify _cleanup_process_state call.
        mock_cleanup.assert_called_once()

    def test_retry_merge_e2e_subprocess_flow(self, cl):
        """T3-E2E: _do_retry_merge happy path with mocked subprocess exit_code=0.

        Verifies merge_status='merged', merge-results push, and cleanup call.
        The pattern matches _do_inline_merge, but the entry path is separate.
        """
        import fakeredis as _fakeredis
        import types as _types

        fake_r = _fakeredis.FakeRedis(decode_responses=True)
        runner_id = "e2e-retry-01"
        prefix = cl.RUNNER_KEY_PREFIX

        fake_r.set(f"{prefix}:{runner_id}:worktree_path", "D:/tmp/wt_retry")
        fake_r.set(f"{prefix}:{runner_id}:plan_file", "docs/plan/test.md")
        fake_r.set(f"{prefix}:{runner_id}:branch", "impl/test")

        mock_lock_mod = _types.ModuleType("merge_queue")
        mock_lock_mod.acquire_merge_turn = MagicMock(return_value=True)
        mock_lock_mod.release_merge_turn = MagicMock()
        mock_lock_mod._get_repo_id = MagicMock(return_value="repo-test")

        proc_result = MagicMock()
        proc_result.returncode = 0

        with patch.dict("sys.modules", {"merge_queue": mock_lock_mod}), \
             patch("plan_worktree_helpers.get_branch_divergence", return_value=(0, 1)), \
             patch("_dr_merge._write_pre_merge_snapshot", return_value="logs/snapshot.md"), \
             patch("subprocess.run", return_value=proc_result), \
             patch("_dr_commands._cleanup_process_state") as mock_cleanup:
            cl._do_retry_merge(runner_id, fake_r, "cmd_e2e")

        # Verify merge_status = "merged".
        assert fake_r.get(f"{prefix}:{runner_id}:merge_status") == "merged"

        # Verify merge-results push.
        results = fake_r.lrange("plan-runner:merge-results", 0, 0)
        assert len(results) > 0
        result_data = json.loads(results[0])
        assert result_data["runner_id"] == runner_id
        assert result_data["success"] is True

        # Verify _cleanup_process_state call.
        mock_cleanup.assert_called_once()

        # Verify the pushed result for result_key.
        result_key = f"{cl.RESULTS_KEY}:cmd_e2e"
        pushed = fake_r.lrange(result_key, 0, 0)
        assert len(pushed) > 0
        pushed_data = json.loads(pushed[0])
        assert pushed_data["success"] is True

    def test_execute_merge_with_lock_residue_blocked_persists_quarantine_T3(self, cl, dr_merge_mod):
        """T3: residue helper 실패 시 result/Redis/merge-results가 residue_blocked로 고정된다."""
        import fakeredis as _fakeredis
        import types as _types

        fake_r = _fakeredis.FakeRedis(decode_responses=True)
        runner_id = "e2e-residue-01"
        prefix = cl.RUNNER_KEY_PREFIX

        fake_r.set(f"{prefix}:{runner_id}:worktree_path", "D:/tmp/wt_residue")
        fake_r.set(f"{prefix}:{runner_id}:plan_file", "docs/plan/test.md")
        fake_r.set(f"{prefix}:{runner_id}:branch", "impl/test")

        mock_lock_mod = _types.ModuleType("merge_queue")
        mock_lock_mod.acquire_merge_turn = MagicMock(return_value=True)
        mock_lock_mod.release_merge_turn = MagicMock()
        mock_lock_mod._get_repo_id = MagicMock(return_value="repo-test")

        proc_result = MagicMock()
        proc_result.returncode = 0

        residue_result = {
            "success": False,
            "status": "residue_blocked",
            "reason": "residue_guard",
            "message": "post-merge residue detected and restored",
            "quarantine_diff_path": "logs/dev_runner/residue/e2e-residue-01.diff",
        }

        with patch.dict("sys.modules", {"merge_queue": mock_lock_mod}), \
             patch("plan_worktree_helpers.get_branch_divergence", return_value=(0, 1)), \
             patch("_dr_merge._write_pre_merge_snapshot", return_value="logs/snapshot.md"), \
             patch("subprocess.run", return_value=proc_result), \
             patch.object(dr_merge_mod, "_check_post_merge_residue", return_value=residue_result):
            result = cl._execute_merge_with_lock(runner_id, fake_r)

        assert result["success"] is False
        assert result["merge_status"] == "residue_blocked"
        assert result["reason"] == "residue_guard"
        assert result["quarantine_diff_path"].endswith("e2e-residue-01.diff")
        assert fake_r.get(f"{prefix}:{runner_id}:merge_status") == "residue_blocked"
        assert fake_r.get(f"{prefix}:{runner_id}:done_post_merge_status") == "skipped_residue"
        assert fake_r.get(f"{prefix}:{runner_id}:done_post_merge_error") == "residue_guard"
        assert fake_r.get(f"{prefix}:{runner_id}:quarantine_diff_path").endswith("e2e-residue-01.diff")

        results = fake_r.lrange("plan-runner:merge-results", 0, 0)
        assert len(results) > 0
        result_data = json.loads(results[0])
        assert result_data["runner_id"] == runner_id
        assert result_data["status"] == "residue_blocked"
        assert result_data["success"] is False
        assert result_data["reason"] == "residue_guard"


# Phase T1 (exit_code=2): auto-impl-post-merge recovery tests

class TestExitCode2AutoImplPostMerge:
    def test_exit_code_2_triggers_auto_impl_post_merge_R(self, cl, dr_merge_mod, tmp_path):
        """R(Right): exit_code=2 calls _launch_auto_impl_post_merge_process."""
        redis = _make_redis_mock(worktree_path=tmp_path, plan_file="docs/plan/test.md")
        proc_result = MagicMock()
        proc_result.returncode = 2

        with _merge_lock_patch(), \
             patch("_dr_stream_cleanup._cleanup_process_state"), \
             patch("subprocess.run", return_value=proc_result), \
             patch.object(dr_merge_mod, "_launch_auto_impl_post_merge_process", return_value={"success": False, "message": "fail"}) as mock_fix:
            cl._execute_merge_with_lock("r_exit2", redis)

        mock_fix.assert_called_once()
        call_kwargs = mock_fix.call_args
        assert call_kwargs[1].get("runner_id") == "r_exit2" or call_kwargs[0][0] == "r_exit2"

    def test_exit_code_2_success_after_fix_calls_post_merge_done_R(self, cl, dr_merge_mod, tmp_path):
        """R(Right): successful auto-impl fix calls done handling and sets merged."""
        redis = _make_redis_mock(worktree_path=tmp_path, plan_file="docs/plan/test.md")
        proc_result = MagicMock()
        proc_result.returncode = 2

        with _merge_lock_patch(), \
             patch("subprocess.run", return_value=proc_result), \
             patch.object(dr_merge_mod, "_launch_auto_impl_post_merge_process", return_value={"success": True, "message": "ok"}), \
             patch.object(dr_merge_mod, "_handle_post_merge_done") as mock_done:
            result = cl._execute_merge_with_lock("r_exit2_ok", redis)

        assert result["success"] is True
        assert result["merge_status"] == "merged"
        mock_done.assert_called_once()

    def test_exit_code_2_no_plan_file_skips_auto_fix_B(self, cl, dr_merge_mod, tmp_path):
        """B(Boundary): plan_file=None skips auto fix and sets test_failed."""
        redis = _make_redis_mock(worktree_path=tmp_path, plan_file=None)
        proc_result = MagicMock()
        proc_result.returncode = 2

        with _merge_lock_patch(), \
             patch("subprocess.run", return_value=proc_result), \
             patch.object(dr_merge_mod, "_launch_auto_impl_post_merge_process") as mock_fix:
            result = cl._execute_merge_with_lock("r_exit2_noplan", redis)

        mock_fix.assert_not_called()
        assert result["success"] is False
        assert result["merge_status"] == "test_failed"

    def test_exit_code_2_fix_failure_sets_test_failed_status_E(self, cl, dr_merge_mod, tmp_path):
        """E(Error): failed auto fix sets merge_status='test_failed'."""
        redis = _make_redis_mock(worktree_path=tmp_path, plan_file="docs/plan/test.md")
        proc_result = MagicMock()
        proc_result.returncode = 2

        with _merge_lock_patch(), \
             patch("subprocess.run", return_value=proc_result), \
             patch.object(dr_merge_mod, "_launch_auto_impl_post_merge_process", return_value={"success": False, "message": "fix failed"}):
            result = cl._execute_merge_with_lock("r_exit2_fail", redis)

        assert result["success"] is False
        assert result["merge_status"] == "test_failed"

    def test_exit_code_2_retry_limit_prevents_infinite_loop_B(self, cl, dr_merge_mod, tmp_path):
        """B(Boundary): _test_fix_attempt=2 skips auto fix and fails immediately."""
        redis = _make_redis_mock(worktree_path=tmp_path, plan_file="docs/plan/test.md")
        proc_result = MagicMock()
        proc_result.returncode = 2

        with _merge_lock_patch(), \
             patch("subprocess.run", return_value=proc_result), \
             patch.object(dr_merge_mod, "_launch_auto_impl_post_merge_process") as mock_fix:
            result = cl._execute_merge_with_lock("r_exit2_limit", redis, _test_fix_attempt=2)

        mock_fix.assert_not_called()
        assert result["success"] is False
        assert result["merge_status"] == "test_failed"

    def test_exit_code_2_merge_status_transitions_Co(self, cl, dr_merge_mod, tmp_path):
        """Co(Conformance): exit_code=2 transitions merging to fixing to test_failed."""
        redis = _make_redis_mock(worktree_path=tmp_path, plan_file="docs/plan/test.md")
        proc_result = MagicMock()
        proc_result.returncode = 2
        set_calls = []
        redis.set.side_effect = lambda k, v: set_calls.append((k, v))

        with _merge_lock_patch(), \
             patch("subprocess.run", return_value=proc_result), \
             patch.object(dr_merge_mod, "_launch_auto_impl_post_merge_process", return_value={"success": False, "message": "fail"}):
            cl._execute_merge_with_lock("r_co", redis)

        merge_status_calls = [(k, v) for k, v in set_calls if "merge_status" in k]
        statuses = [v for _, v in merge_status_calls]
        assert "merging" in statuses
        assert "fixing" in statuses
        assert "test_failed" in statuses
        # Verify transition order: merging -> fixing -> test_failed.
        idx_merging = next(i for i, v in enumerate(statuses) if v == "merging")
        idx_fixing = next(i for i, v in enumerate(statuses) if v == "fixing")
        idx_failed = next(i for i, v in enumerate(statuses) if v == "test_failed")
        assert idx_merging < idx_fixing < idx_failed


# Phase T3 (exit_code=2): fakeredis integration test

class TestExitCode2IntegrationFakeRedis:
    def test_exit_code_2_integration_with_fakeredis(self, cl, dr_merge_mod):
        """T3 integration: verify _execute_merge_with_lock exit_code=2 with fakeredis.

        Redis merge_status transition: merging -> fixing -> test_failed.
        """
        import fakeredis as _fakeredis
        import types as _types

        fake_r = _fakeredis.FakeRedis(decode_responses=True)
        runner_id = "e2e-exit2-01"
        prefix = cl.RUNNER_KEY_PREFIX

        fake_r.set(f"{prefix}:{runner_id}:worktree_path", "D:/tmp/wt_exit2")
        fake_r.set(f"{prefix}:{runner_id}:plan_file", "docs/plan/test.md")
        fake_r.set(f"{prefix}:{runner_id}:branch", "impl/test")

        mock_lock_mod = _types.ModuleType("merge_queue")
        mock_lock_mod.acquire_merge_turn = MagicMock(return_value=True)
        mock_lock_mod.release_merge_turn = MagicMock()
        mock_lock_mod._get_repo_id = MagicMock(return_value="repo-test")

        proc_result = MagicMock()
        proc_result.returncode = 2

        with patch.dict("sys.modules", {"merge_queue": mock_lock_mod}), \
             patch("plan_worktree_helpers.get_branch_divergence", return_value=(0, 1)), \
             patch("_dr_merge._write_pre_merge_snapshot", return_value="logs/snapshot.md"), \
             patch("subprocess.run", return_value=proc_result), \
             patch.object(dr_merge_mod, "_launch_auto_impl_post_merge_process", return_value={"success": False, "message": "fail"}):
            result = cl._execute_merge_with_lock(runner_id, fake_r)

        # Final merge_status = "test_failed".
        assert fake_r.get(f"{prefix}:{runner_id}:merge_status") == "test_failed"
        assert result["success"] is False
        assert result["merge_status"] == "test_failed"

        # Verify merge-results push.
        results = fake_r.lrange("plan-runner:merge-results", 0, 0)
        assert len(results) > 0
        result_data = json.loads(results[0])
        assert result_data["runner_id"] == runner_id
        assert result_data["success"] is False


