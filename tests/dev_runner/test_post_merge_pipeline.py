"""
TC: _do_inline_merge / _do_retry_merge subprocess 교체 단위 테스트

Phase T1: plan-runner post-merge subprocess 호출 패턴 검증
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

_SCRIPT_PATH = _SCRIPTS_DIR / "dev-runner-command-listener.py"
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
    """merge_lock 모듈 전체를 mock (acquire→True, release→None)"""
    mock_lock_mod = types.ModuleType("merge_lock")
    mock_lock_mod.acquire_merge_lock = MagicMock(return_value=True)
    mock_lock_mod.release_merge_lock = MagicMock()
    return patch.dict("sys.modules", {"merge_lock": mock_lock_mod})


# ── Phase T1: subprocess 교체 패턴 TC ────────────────────────────────────────

class TestDoInlineMergeSubprocess:
    def test_do_inline_merge_calls_plan_runner_subprocess_R(self, cl, tmp_path):
        """R(Right): _do_inline_merge 호출 시 subprocess.run이
        [..PLAN_RUNNER_PYTHON, '-m', 'plan_runner', 'post-merge', '--runner-id', ...] 명령으로 호출됨"""
        redis = _make_redis_mock()
        proc_result = MagicMock()
        proc_result.returncode = 0

        with _merge_lock_patch(), \
             patch.object(cl, "_cleanup_process_state"), \
             patch("subprocess.run", return_value=proc_result) as mock_run:
            cl._do_inline_merge("r1", redis)

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "-m" in cmd
        assert "plan_runner" in cmd
        assert "post-merge" in cmd
        assert "--runner-id" in cmd
        assert "r1" in cmd

    def test_do_inline_merge_subprocess_exit0_sets_merged_R(self, cl, tmp_path):
        """R(Right): subprocess returncode=0 → merge_status='merged' 설정"""
        redis = _make_redis_mock()
        set_calls = []
        redis.set.side_effect = lambda k, v: set_calls.append((k, v))

        proc_result = MagicMock()
        proc_result.returncode = 0

        with _merge_lock_patch(), \
             patch.object(cl, "_cleanup_process_state"), \
             patch("subprocess.run", return_value=proc_result):
            cl._do_inline_merge("r_exit0", redis)

        status_values = [v for k, v in set_calls if "merge_status" in k]
        assert "merged" in status_values

    def test_do_inline_merge_subprocess_exit1_sets_error_E(self, cl, tmp_path):
        """E(Error): subprocess returncode=1 → merge_status='error' 설정"""
        redis = _make_redis_mock()
        set_calls = []
        redis.set.side_effect = lambda k, v: set_calls.append((k, v))

        proc_result = MagicMock()
        proc_result.returncode = 1

        with _merge_lock_patch(), \
             patch.object(cl, "_cleanup_process_state"), \
             patch.object(cl, "_launch_general_merge_resolver_process", return_value={"success": False, "message": "fail"}), \
             patch("subprocess.run", return_value=proc_result):
            cl._do_inline_merge("r_exit1", redis)

        status_values = [v for k, v in set_calls if "merge_status" in k]
        assert "error" in status_values
        assert "merged" not in status_values

    def test_do_inline_merge_subprocess_exit3_sets_conflict_B(self, cl, tmp_path):
        """B(Boundary): subprocess returncode=3 → merge_status='conflict' 설정"""
        redis = _make_redis_mock()
        set_calls = []
        redis.set.side_effect = lambda k, v: set_calls.append((k, v))

        proc_result = MagicMock()
        proc_result.returncode = 3

        with _merge_lock_patch(), \
             patch.object(cl, "_cleanup_process_state"), \
             patch("subprocess.run", return_value=proc_result):
            cl._do_inline_merge("r_exit3", redis)

        status_values = [v for k, v in set_calls if "merge_status" in k]
        assert "conflict" in status_values

    def test_do_inline_merge_cleanup_always_runs_R(self, cl, tmp_path):
        """R(Right): subprocess 성공/실패 모두 _cleanup_process_state 호출됨"""
        # 성공 케이스
        redis_ok = _make_redis_mock()
        proc_ok = MagicMock()
        proc_ok.returncode = 0

        with _merge_lock_patch(), \
             patch.object(cl, "_cleanup_process_state") as mock_cleanup_ok, \
             patch("subprocess.run", return_value=proc_ok):
            cl._do_inline_merge("r_cleanup_ok", redis_ok)

        mock_cleanup_ok.assert_called_once()

        # 실패 케이스
        redis_fail = _make_redis_mock()
        proc_fail = MagicMock()
        proc_fail.returncode = 1

        with _merge_lock_patch(), \
             patch.object(cl, "_cleanup_process_state") as mock_cleanup_fail, \
             patch("subprocess.run", return_value=proc_fail):
            cl._do_inline_merge("r_cleanup_fail", redis_fail)

        mock_cleanup_fail.assert_called_once()

    def test_do_inline_merge_no_restart_after_merge_B(self, cl, tmp_path):
        """B(Boundary): restart_after_merge Redis 키가 설정되지 않음"""
        redis = _make_redis_mock()
        set_keys = []
        redis.set.side_effect = lambda k, v: set_keys.append(k)

        proc_result = MagicMock()
        proc_result.returncode = 0

        with _merge_lock_patch(), \
             patch.object(cl, "_cleanup_process_state"), \
             patch("subprocess.run", return_value=proc_result):
            cl._do_inline_merge("r_no_restart", redis)

        assert not any("restart_after_merge" in k for k in set_keys)

    def test_do_inline_merge_merge_results_pushed_R(self, cl, tmp_path):
        """R(Right): 완료 후 plan-runner:merge-results에 결과 push"""
        redis = _make_redis_mock()
        lpush_calls = []
        redis.lpush.side_effect = lambda k, v: lpush_calls.append((k, v))

        proc_result = MagicMock()
        proc_result.returncode = 0

        with _merge_lock_patch(), \
             patch.object(cl, "_cleanup_process_state"), \
             patch("subprocess.run", return_value=proc_result):
            cl._do_inline_merge("r_results", redis)

        pushed_keys = [k for k, v in lpush_calls]
        assert "plan-runner:merge-results" in pushed_keys


class TestDoRetryMergeSubprocess:
    def test_do_retry_merge_calls_plan_runner_subprocess_R(self, cl, tmp_path):
        """R(Right): _do_retry_merge 호출 시 subprocess.run이 post-merge 명령으로 호출됨"""
        redis = _make_redis_mock(worktree_path=tmp_path)
        proc_result = MagicMock()
        proc_result.returncode = 0

        with _merge_lock_patch(), \
             patch.object(cl, "_cleanup_process_state"), \
             patch("subprocess.run", return_value=proc_result) as mock_run:
            cl._do_retry_merge("r_retry", redis, "cmd123")

        mock_run.assert_called()
        # subprocess.run이 git rev-parse 등 내부 호출도 있으므로 post-merge 인자 포함 호출 검증
        post_merge_calls = [c for c in mock_run.call_args_list if "post-merge" in str(c)]
        assert len(post_merge_calls) >= 1, f"post-merge 호출이 없음: {mock_run.call_args_list}"
        cmd = post_merge_calls[0][0][0]
        assert "plan_runner" in cmd
        assert "--runner-id" in cmd
        assert "r_retry" in cmd

    def test_do_retry_merge_exit0_success_result_R(self, cl, tmp_path):
        """R(Right): exit_code=0 → result.success=True + merge-results push"""
        redis = _make_redis_mock(worktree_path=tmp_path)
        lpush_calls = []
        redis.lpush.side_effect = lambda k, v: lpush_calls.append((k, v))

        proc_result = MagicMock()
        proc_result.returncode = 0

        with _merge_lock_patch(), \
             patch.object(cl, "_cleanup_process_state"), \
             patch("subprocess.run", return_value=proc_result):
            cl._do_retry_merge("r_retry_ok", redis, "cmd_ok")

        # result_key에 push된 결과 확인
        result_key = f"{cl.RESULTS_KEY}:cmd_ok"
        result_pushes = [v for k, v in lpush_calls if k == result_key]
        assert len(result_pushes) > 0
        result_data = json.loads(result_pushes[-1])
        assert result_data.get("success") is True

    def test_do_retry_merge_exit3_conflict_result_B(self, cl, tmp_path):
        """B(Boundary): exit_code=3 → result.conflict=True"""
        redis = _make_redis_mock(worktree_path=tmp_path)
        lpush_calls = []
        redis.lpush.side_effect = lambda k, v: lpush_calls.append((k, v))

        proc_result = MagicMock()
        proc_result.returncode = 3

        with _merge_lock_patch(), \
             patch.object(cl, "_cleanup_process_state"), \
             patch("subprocess.run", return_value=proc_result):
            cl._do_retry_merge("r_retry_conflict", redis, "cmd_conflict")

        result_key = f"{cl.RESULTS_KEY}:cmd_conflict"
        result_pushes = [v for k, v in lpush_calls if k == result_key]
        assert len(result_pushes) > 0
        result_data = json.loads(result_pushes[-1])
        assert result_data.get("conflict") is True


class TestDeletedFunctions:
    def test_deleted_functions_not_exist_R(self, cl):
        """R(Right): _post_merge_pipeline, _restart_plan_runner_after_merge,
        _resolve_todo_file가 모듈 속성에 없음"""
        assert not hasattr(cl, "_post_merge_pipeline"), \
            "_post_merge_pipeline should be deleted (replaced by plan-runner post-merge)"
        assert not hasattr(cl, "_restart_plan_runner_after_merge"), \
            "_restart_plan_runner_after_merge should be deleted"
        assert not hasattr(cl, "_resolve_todo_file"), \
            "_resolve_todo_file should be deleted"


# ── Phase T3: E2E 테스트 ──────────────────────────────────────────────────────

class TestInlineMergeE2ESubprocessFlow:
    def test_inline_merge_e2e_subprocess_flow(self, cl):
        """T3-E2E: _do_inline_merge 전체 흐름 — subprocess mock → exit_code=0
        → merge_status='merged' → merge-results push → _cleanup_process_state 호출 확인
        """
        import fakeredis as _fakeredis
        import types as _types

        fake_r = _fakeredis.FakeRedis(decode_responses=True)
        runner_id = "e2e-inline-01"
        prefix = cl.RUNNER_KEY_PREFIX

        # per-runner 키 사전 설정
        fake_r.set(f"{prefix}:{runner_id}:merge_requested", "1")
        fake_r.set(f"{prefix}:{runner_id}:plan_file", "docs/plan/test.md")
        fake_r.set(f"{prefix}:{runner_id}:branch", "impl/test")
        fake_r.set(f"{prefix}:{runner_id}:worktree_path", "D:/tmp/wt")

        mock_lock_mod = _types.ModuleType("merge_lock")
        mock_lock_mod.acquire_merge_lock = MagicMock(return_value=True)
        mock_lock_mod.release_merge_lock = MagicMock()

        proc_result = MagicMock()
        proc_result.returncode = 0

        with patch.dict("sys.modules", {"merge_lock": mock_lock_mod}), \
             patch("subprocess.run", return_value=proc_result), \
             patch.object(cl, "_cleanup_process_state") as mock_cleanup:
            cl._do_inline_merge(runner_id, fake_r)

        # merge_status = "merged" 확인
        assert fake_r.get(f"{prefix}:{runner_id}:merge_status") == "merged"

        # merge-results push 확인
        results = fake_r.lrange("plan-runner:merge-results", 0, 0)
        assert len(results) > 0
        result_data = json.loads(results[0])
        assert result_data["runner_id"] == runner_id
        assert result_data["success"] is True

        # _cleanup_process_state 호출 확인
        mock_cleanup.assert_called_once_with(runner_id, fake_r)

    def test_retry_merge_e2e_subprocess_flow(self, cl):
        """T3-E2E: _do_retry_merge 전체 흐름 — subprocess mock → exit_code=0
        → merge_status='merged' → merge-results push → _cleanup_process_state 호출 확인
        _do_inline_merge와 동일 패턴이지만 진입 경로가 다르므로 별도 검증
        """
        import fakeredis as _fakeredis
        import types as _types

        fake_r = _fakeredis.FakeRedis(decode_responses=True)
        runner_id = "e2e-retry-01"
        prefix = cl.RUNNER_KEY_PREFIX

        fake_r.set(f"{prefix}:{runner_id}:worktree_path", "D:/tmp/wt_retry")
        fake_r.set(f"{prefix}:{runner_id}:plan_file", "docs/plan/test.md")
        fake_r.set(f"{prefix}:{runner_id}:branch", "impl/test")

        mock_lock_mod = _types.ModuleType("merge_lock")
        mock_lock_mod.acquire_merge_lock = MagicMock(return_value=True)
        mock_lock_mod.release_merge_lock = MagicMock()

        proc_result = MagicMock()
        proc_result.returncode = 0

        with patch.dict("sys.modules", {"merge_lock": mock_lock_mod}), \
             patch("subprocess.run", return_value=proc_result), \
             patch.object(cl, "_cleanup_process_state") as mock_cleanup:
            cl._do_retry_merge(runner_id, fake_r, "cmd_e2e")

        # merge_status = "merged" 확인
        assert fake_r.get(f"{prefix}:{runner_id}:merge_status") == "merged"

        # merge-results push 확인
        results = fake_r.lrange("plan-runner:merge-results", 0, 0)
        assert len(results) > 0
        result_data = json.loads(results[0])
        assert result_data["runner_id"] == runner_id
        assert result_data["success"] is True

        # _cleanup_process_state 호출 확인
        mock_cleanup.assert_called_once_with(runner_id, fake_r)

        # result_key에 push된 결과 확인
        result_key = f"{cl.RESULTS_KEY}:cmd_e2e"
        pushed = fake_r.lrange(result_key, 0, 0)
        assert len(pushed) > 0
        pushed_data = json.loads(pushed[0])
        assert pushed_data["success"] is True


# ── Phase T1 (exit_code=2): auto-impl-post-merge 자동 복구 TC ─────────────────

class TestExitCode2AutoImplPostMerge:
    def test_exit_code_2_triggers_auto_impl_post_merge_R(self, cl, tmp_path):
        """R(Right): exit_code=2 → _launch_auto_impl_post_merge_process 호출됨"""
        redis = _make_redis_mock(worktree_path=tmp_path, plan_file="docs/plan/test.md")
        proc_result = MagicMock()
        proc_result.returncode = 2

        with _merge_lock_patch(), \
             patch.object(cl, "_cleanup_process_state"), \
             patch("subprocess.run", return_value=proc_result), \
             patch.object(cl, "_launch_auto_impl_post_merge_process", return_value={"success": False, "message": "fail"}) as mock_fix:
            cl._execute_merge_with_lock("r_exit2", redis)

        mock_fix.assert_called_once()
        call_kwargs = mock_fix.call_args
        assert call_kwargs[1].get("runner_id") == "r_exit2" or call_kwargs[0][0] == "r_exit2"

    def test_exit_code_2_success_after_fix_calls_post_merge_done_R(self, cl, tmp_path):
        """R(Right): _launch_auto_impl_post_merge_process → success=True → _handle_post_merge_done 호출 + merge_status='merged'"""
        redis = _make_redis_mock(worktree_path=tmp_path, plan_file="docs/plan/test.md")
        proc_result = MagicMock()
        proc_result.returncode = 2

        with _merge_lock_patch(), \
             patch("subprocess.run", return_value=proc_result), \
             patch.object(cl, "_launch_auto_impl_post_merge_process", return_value={"success": True, "message": "ok"}), \
             patch.object(cl, "_handle_post_merge_done") as mock_done:
            result = cl._execute_merge_with_lock("r_exit2_ok", redis)

        assert result["success"] is True
        assert result["merge_status"] == "merged"
        mock_done.assert_called_once()

    def test_exit_code_2_no_plan_file_skips_auto_fix_B(self, cl, tmp_path):
        """B(Boundary): plan_file=None → _launch_auto_impl_post_merge_process 호출 없이 merge_status='test_failed'"""
        redis = _make_redis_mock(worktree_path=tmp_path, plan_file=None)
        proc_result = MagicMock()
        proc_result.returncode = 2

        with _merge_lock_patch(), \
             patch("subprocess.run", return_value=proc_result), \
             patch.object(cl, "_launch_auto_impl_post_merge_process") as mock_fix:
            result = cl._execute_merge_with_lock("r_exit2_noplan", redis)

        mock_fix.assert_not_called()
        assert result["success"] is False
        assert result["merge_status"] == "test_failed"

    def test_exit_code_2_fix_failure_sets_test_failed_status_E(self, cl, tmp_path):
        """E(Error): _launch_auto_impl_post_merge_process → success=False → merge_status='test_failed'"""
        redis = _make_redis_mock(worktree_path=tmp_path, plan_file="docs/plan/test.md")
        proc_result = MagicMock()
        proc_result.returncode = 2

        with _merge_lock_patch(), \
             patch("subprocess.run", return_value=proc_result), \
             patch.object(cl, "_launch_auto_impl_post_merge_process", return_value={"success": False, "message": "fix failed"}):
            result = cl._execute_merge_with_lock("r_exit2_fail", redis)

        assert result["success"] is False
        assert result["merge_status"] == "test_failed"

    def test_exit_code_2_retry_limit_prevents_infinite_loop_B(self, cl, tmp_path):
        """B(Boundary): _test_fix_attempt=2 → _launch_auto_impl_post_merge_process 호출 없이 즉시 test_failed"""
        redis = _make_redis_mock(worktree_path=tmp_path, plan_file="docs/plan/test.md")
        proc_result = MagicMock()
        proc_result.returncode = 2

        with _merge_lock_patch(), \
             patch("subprocess.run", return_value=proc_result), \
             patch.object(cl, "_launch_auto_impl_post_merge_process") as mock_fix:
            result = cl._execute_merge_with_lock("r_exit2_limit", redis, _test_fix_attempt=2)

        mock_fix.assert_not_called()
        assert result["success"] is False
        assert result["merge_status"] == "test_failed"

    def test_exit_code_2_merge_status_transitions_Co(self, cl, tmp_path):
        """Co(Conformance): exit_code=2 처리 중 merge_status 전이: merging → fixing → test_failed(실패 시)"""
        redis = _make_redis_mock(worktree_path=tmp_path, plan_file="docs/plan/test.md")
        proc_result = MagicMock()
        proc_result.returncode = 2
        set_calls = []
        redis.set.side_effect = lambda k, v: set_calls.append((k, v))

        with _merge_lock_patch(), \
             patch("subprocess.run", return_value=proc_result), \
             patch.object(cl, "_launch_auto_impl_post_merge_process", return_value={"success": False, "message": "fail"}):
            cl._execute_merge_with_lock("r_co", redis)

        merge_status_calls = [(k, v) for k, v in set_calls if "merge_status" in k]
        statuses = [v for _, v in merge_status_calls]
        assert "merging" in statuses
        assert "fixing" in statuses
        assert "test_failed" in statuses
        # 순서 검증: merging → fixing → test_failed
        idx_merging = next(i for i, v in enumerate(statuses) if v == "merging")
        idx_fixing = next(i for i, v in enumerate(statuses) if v == "fixing")
        idx_failed = next(i for i, v in enumerate(statuses) if v == "test_failed")
        assert idx_merging < idx_fixing < idx_failed


# ── Phase T3 (exit_code=2): fakeredis 통합 TC ─────────────────────────────────

class TestExitCode2IntegrationFakeRedis:
    def test_exit_code_2_integration_with_fakeredis(self, cl):
        """T3(통합): fakeredis로 _execute_merge_with_lock exit_code=2 시나리오 검증.

        Redis merge_status 전이: merging → fixing → test_failed
        """
        import fakeredis as _fakeredis
        import types as _types

        fake_r = _fakeredis.FakeRedis(decode_responses=True)
        runner_id = "e2e-exit2-01"
        prefix = cl.RUNNER_KEY_PREFIX

        fake_r.set(f"{prefix}:{runner_id}:worktree_path", "D:/tmp/wt_exit2")
        fake_r.set(f"{prefix}:{runner_id}:plan_file", "docs/plan/test.md")
        fake_r.set(f"{prefix}:{runner_id}:branch", "impl/test")

        mock_lock_mod = _types.ModuleType("merge_lock")
        mock_lock_mod.acquire_merge_lock = MagicMock(return_value=True)
        mock_lock_mod.release_merge_lock = MagicMock()

        proc_result = MagicMock()
        proc_result.returncode = 2

        with patch.dict("sys.modules", {"merge_lock": mock_lock_mod}), \
             patch("subprocess.run", return_value=proc_result), \
             patch.object(cl, "_launch_auto_impl_post_merge_process", return_value={"success": False, "message": "fail"}):
            result = cl._execute_merge_with_lock(runner_id, fake_r)

        # 최종 merge_status = "test_failed"
        assert fake_r.get(f"{prefix}:{runner_id}:merge_status") == "test_failed"
        assert result["success"] is False
        assert result["merge_status"] == "test_failed"

        # merge-results push 확인
        results = fake_r.lrange("plan-runner:merge-results", 0, 0)
        assert len(results) > 0
        result_data = json.loads(results[0])
        assert result_data["runner_id"] == runner_id
        assert result_data["success"] is False
