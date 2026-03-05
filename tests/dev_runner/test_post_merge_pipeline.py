"""
TC: _post_merge_pipeline / _launch_auto_fix_process / _do_inline_merge 통합 단위 테스트

Phase T1-1: _post_merge_pipeline 단위 TC
Phase T1-2: _launch_auto_fix_process 단위 TC
Phase T1-3: _do_inline_merge 통합 TC
Phase T1-4: MergeWorkflow 수정 회귀 TC
"""
import importlib
import importlib.util
import subprocess
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import fakeredis
import pytest

# scripts/ 디렉토리를 sys.path에 추가 — merge_workflow, worktree_manager 등 import용
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


def make_redis_mock(worktree_path=None, plan_file=None, branch=None):
    """test_conflict_resolve_new.py의 make_redis_mock 복제 — _do_inline_merge 통합 TC용"""
    redis = MagicMock()

    def redis_get(key):
        if "worktree_path" in key:
            return worktree_path
        if "plan_file" in key:
            return plan_file
        if "branch" in key:
            return branch
        return None

    redis.get.side_effect = redis_get
    redis.set.return_value = True
    redis.lpush.return_value = 1
    redis.expire.return_value = True
    redis.publish.return_value = 1
    redis.sadd.return_value = 1
    redis.delete.return_value = 1
    return redis


def _pub_noop(msg):
    pass


# ── Phase T1-1: _post_merge_pipeline 단위 TC ─────────────────────────────────

class TestPostMergePipeline:
    def test_post_merge_pipeline_no_targets_returns_true_R(self, cl, fake_redis):
        """R(Right): detect_restart_targets → 빈 dict → True 반환, restart/test 미호출"""
        with patch("plan_runner.core.merge.detect_restart_targets", return_value={}) as mock_detect, \
             patch("plan_runner.core.merge.restart_services") as mock_restart, \
             patch("plan_runner.core.merge.run_http_tests") as mock_http:
            # lazy import 경로를 mock하기 위해 sys.path에 plan-runner 추가 후 patch
            plan_runner_path = cl.PLAN_RUNNER_MODULE_PATH
            sys.path.insert(0, str(plan_runner_path))
            try:
                import plan_runner.core.merge as prcm
                with patch.object(prcm, "detect_restart_targets", return_value={}), \
                     patch.object(prcm, "restart_services") as mock_restart2, \
                     patch.object(prcm, "run_http_tests") as mock_http2:
                    result = cl._post_merge_pipeline("r1", fake_redis, _pub_noop)
                assert result is True
                mock_restart2.assert_not_called()
                mock_http2.assert_not_called()
            finally:
                if str(plan_runner_path) in sys.path:
                    sys.path.remove(str(plan_runner_path))

    def test_post_merge_pipeline_api_change_restarts_and_tests_R(self, cl, fake_redis):
        """R(Right): targets={"api": True} → restart + run_http_tests 호출 → True"""
        plan_runner_path = cl.PLAN_RUNNER_MODULE_PATH
        sys.path.insert(0, str(plan_runner_path))
        try:
            import plan_runner.core.merge as prcm
            mock_test_result = MagicMock(passed=True, output="")
            with patch.object(prcm, "detect_restart_targets", return_value={"api": True}), \
                 patch.object(prcm, "restart_services") as mock_restart, \
                 patch.object(prcm, "run_http_tests", return_value=mock_test_result) as mock_http, \
                 patch.object(prcm, "run_frontend_build") as mock_build:
                result = cl._post_merge_pipeline("r2", fake_redis, _pub_noop)
            assert result is True
            mock_restart.assert_called_once()
            mock_http.assert_called_once()
            mock_build.assert_not_called()
        finally:
            if str(plan_runner_path) in sys.path:
                sys.path.remove(str(plan_runner_path))

    def test_post_merge_pipeline_frontend_change_builds_R(self, cl, fake_redis):
        """R(Right): targets={"frontend": True} → run_frontend_build 호출 → True"""
        plan_runner_path = cl.PLAN_RUNNER_MODULE_PATH
        sys.path.insert(0, str(plan_runner_path))
        try:
            import plan_runner.core.merge as prcm
            mock_build_result = MagicMock(passed=True, output="")
            with patch.object(prcm, "detect_restart_targets", return_value={"frontend": True}), \
                 patch.object(prcm, "restart_services"), \
                 patch.object(prcm, "run_frontend_build", return_value=mock_build_result) as mock_build, \
                 patch.object(prcm, "run_http_tests") as mock_http:
                result = cl._post_merge_pipeline("r3", fake_redis, _pub_noop)
            assert result is True
            mock_build.assert_called_once()
            mock_http.assert_not_called()
        finally:
            if str(plan_runner_path) in sys.path:
                sys.path.remove(str(plan_runner_path))

    def test_post_merge_pipeline_both_targets_R(self, cl, fake_redis):
        """R(Right): targets={"api": True, "frontend": True} → build + test 둘 다 실행"""
        plan_runner_path = cl.PLAN_RUNNER_MODULE_PATH
        sys.path.insert(0, str(plan_runner_path))
        try:
            import plan_runner.core.merge as prcm
            mock_ok = MagicMock(passed=True, output="")
            with patch.object(prcm, "detect_restart_targets", return_value={"api": True, "frontend": True}), \
                 patch.object(prcm, "restart_services"), \
                 patch.object(prcm, "run_frontend_build", return_value=mock_ok) as mock_build, \
                 patch.object(prcm, "run_http_tests", return_value=mock_ok) as mock_http:
                result = cl._post_merge_pipeline("r4", fake_redis, _pub_noop)
            assert result is True
            mock_build.assert_called_once()
            mock_http.assert_called_once()
        finally:
            if str(plan_runner_path) in sys.path:
                sys.path.remove(str(plan_runner_path))

    def test_post_merge_pipeline_test_fail_calls_auto_fix_E(self, cl, fake_redis):
        """E(Error): HTTP test 실패 → _launch_auto_fix_process 호출 확인"""
        plan_runner_path = cl.PLAN_RUNNER_MODULE_PATH
        sys.path.insert(0, str(plan_runner_path))
        try:
            import plan_runner.core.merge as prcm
            mock_fail = MagicMock(passed=False, output="FAILED output")
            fix_result = {"success": True, "message": "fixed"}
            with patch.object(prcm, "detect_restart_targets", return_value={"api": True}), \
                 patch.object(prcm, "restart_services"), \
                 patch.object(prcm, "run_http_tests", return_value=mock_fail), \
                 patch.object(cl, "_launch_auto_fix_process", return_value=fix_result) as mock_fix, \
                 patch.object(prcm, "run_frontend_build"):
                # fix 후 재테스트도 mock (api만 있을 때)
                cl._post_merge_pipeline("r5", fake_redis, _pub_noop)
            mock_fix.assert_called_once()
        finally:
            if str(plan_runner_path) in sys.path:
                sys.path.remove(str(plan_runner_path))

    def test_post_merge_pipeline_test_fail_fix_success_returns_true_R(self, cl, fake_redis):
        """R(Right): test 실패 → auto-fix 성공 → 재테스트 통과 → True"""
        plan_runner_path = cl.PLAN_RUNNER_MODULE_PATH
        sys.path.insert(0, str(plan_runner_path))
        try:
            import plan_runner.core.merge as prcm
            mock_fail = MagicMock(passed=False, output="FAILED")
            mock_pass = MagicMock(passed=True, output="passed")
            call_count = {"n": 0}
            def http_side(*a, **kw):
                call_count["n"] += 1
                return mock_fail if call_count["n"] == 1 else mock_pass
            fix_result = {"success": True, "message": "fixed"}
            with patch.object(prcm, "detect_restart_targets", return_value={"api": True}), \
                 patch.object(prcm, "restart_services"), \
                 patch.object(prcm, "run_http_tests", side_effect=http_side), \
                 patch.object(cl, "_launch_auto_fix_process", return_value=fix_result):
                result = cl._post_merge_pipeline("r6", fake_redis, _pub_noop)
            assert result is True
        finally:
            if str(plan_runner_path) in sys.path:
                sys.path.remove(str(plan_runner_path))

    def test_post_merge_pipeline_test_fail_fix_fail_reverts_E(self, cl, fake_redis):
        """E(Error): test 실패 → auto-fix 실패 → revert + False 반환"""
        plan_runner_path = cl.PLAN_RUNNER_MODULE_PATH
        sys.path.insert(0, str(plan_runner_path))
        try:
            import plan_runner.core.merge as prcm
            mock_fail = MagicMock(passed=False, output="FAILED")
            fix_result = {"success": False, "message": "fix failed"}
            with patch.object(prcm, "detect_restart_targets", return_value={"api": True}), \
                 patch.object(prcm, "restart_services"), \
                 patch.object(prcm, "run_http_tests", return_value=mock_fail), \
                 patch.object(cl, "_launch_auto_fix_process", return_value=fix_result), \
                 patch.object(prcm, "revert_merge") as mock_revert:
                result = cl._post_merge_pipeline("r7", fake_redis, _pub_noop)
            assert result is False
            mock_revert.assert_called_once()
        finally:
            if str(plan_runner_path) in sys.path:
                sys.path.remove(str(plan_runner_path))

    def test_post_merge_pipeline_frontend_build_fail_reverts_E(self, cl, fake_redis):
        """E(Error): frontend build 실패 → revert + False"""
        plan_runner_path = cl.PLAN_RUNNER_MODULE_PATH
        sys.path.insert(0, str(plan_runner_path))
        try:
            import plan_runner.core.merge as prcm
            mock_fail = MagicMock(passed=False, output="BUILD FAILED")
            fix_result = {"success": False, "message": "failed"}
            with patch.object(prcm, "detect_restart_targets", return_value={"frontend": True}), \
                 patch.object(prcm, "restart_services"), \
                 patch.object(prcm, "run_frontend_build", return_value=mock_fail), \
                 patch.object(cl, "_launch_auto_fix_process", return_value=fix_result), \
                 patch.object(prcm, "revert_merge") as mock_revert:
                result = cl._post_merge_pipeline("r8", fake_redis, _pub_noop)
            assert result is False
            mock_revert.assert_called_once()
        finally:
            if str(plan_runner_path) in sys.path:
                sys.path.remove(str(plan_runner_path))

    def test_post_merge_pipeline_revert_failure_still_returns_false_E(self, cl, fake_redis):
        """E(Error): revert_merge 예외 → False 반환 (예외 전파 없음)"""
        plan_runner_path = cl.PLAN_RUNNER_MODULE_PATH
        sys.path.insert(0, str(plan_runner_path))
        try:
            import plan_runner.core.merge as prcm
            mock_fail = MagicMock(passed=False, output="FAIL")
            fix_result = {"success": False, "message": "failed"}
            with patch.object(prcm, "detect_restart_targets", return_value={"api": True}), \
                 patch.object(prcm, "restart_services"), \
                 patch.object(prcm, "run_http_tests", return_value=mock_fail), \
                 patch.object(cl, "_launch_auto_fix_process", return_value=fix_result), \
                 patch.object(prcm, "revert_merge", side_effect=Exception("git error")):
                result = cl._post_merge_pipeline("r9", fake_redis, _pub_noop)
            assert result is False
        finally:
            if str(plan_runner_path) in sys.path:
                sys.path.remove(str(plan_runner_path))

    def test_post_merge_pipeline_docs_only_change_B(self, cl, fake_redis):
        """B(Boundary): targets 빈 dict (docs만 변경) → 즉시 True, 재시작/테스트 없음"""
        plan_runner_path = cl.PLAN_RUNNER_MODULE_PATH
        sys.path.insert(0, str(plan_runner_path))
        try:
            import plan_runner.core.merge as prcm
            with patch.object(prcm, "detect_restart_targets", return_value={}), \
                 patch.object(prcm, "restart_services") as mock_restart:
                result = cl._post_merge_pipeline("r10", fake_redis, _pub_noop)
            assert result is True
            mock_restart.assert_not_called()
        finally:
            if str(plan_runner_path) in sys.path:
                sys.path.remove(str(plan_runner_path))


# ── Phase T1-2: _launch_auto_fix_process 단위 TC ─────────────────────────────

class TestLaunchAutoFixProcess:
    def test_launch_auto_fix_process_cmd_build_R(self, cl, fake_redis):
        """R(Right): 커맨드에 auto-fix, --skip-test, --error-file, --target 포함"""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
            cl._launch_auto_fix_process("r1", "error output", {"api": True}, fake_redis, _pub_noop)
        cmd = mock_run.call_args[0][0]
        assert "auto-fix" in cmd
        assert "--skip-test" in cmd
        assert "--error-file" in cmd
        assert "--target" in cmd
        assert "api" in cmd

    def test_launch_auto_fix_process_success_R(self, cl, fake_redis):
        """R(Right): returncode=0 → {"success": True}"""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = cl._launch_auto_fix_process("r2", "", {"api": True}, fake_redis)
        assert result["success"] is True

    def test_launch_auto_fix_process_failure_E(self, cl, fake_redis):
        """E(Error): returncode=1 → {"success": False} + message에 내용"""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="SomeError occurred")
            result = cl._launch_auto_fix_process("r3", "", {}, fake_redis)
        assert result["success"] is False
        assert len(result["message"]) > 0

    def test_launch_auto_fix_process_timeout_E(self, cl, fake_redis):
        """E(Error): TimeoutExpired → {"success": False, "message": contains "timeout"}"""
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="cmd", timeout=300)):
            result = cl._launch_auto_fix_process("r4", "", {}, fake_redis)
        assert result["success"] is False
        assert "timeout" in result["message"].lower()

    def test_launch_auto_fix_process_writes_error_file_R(self, cl, fake_redis, tmp_path):
        """R(Right): test_output이 error-file에 기록됨"""
        test_output = "ERROR: something went wrong\nline 2"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            # logs 디렉토리가 PROJECT_ROOT/logs이므로 PROJECT_ROOT를 tmp_path로 patch
            original_root = cl.PROJECT_ROOT
            cl.PROJECT_ROOT = tmp_path
            try:
                cl._launch_auto_fix_process("r5", test_output, {}, fake_redis)
            finally:
                cl.PROJECT_ROOT = original_root
        error_file = tmp_path / "logs" / "auto-fix-r5.log"
        assert error_file.exists()
        assert test_output in error_file.read_text(encoding="utf-8")

    def test_launch_auto_fix_process_env_settings_R(self, cl, fake_redis):
        """R(Right): env에 PYTHONIOENCODING, PLAN_RUNNER_RUNNER_ID 설정 + CLAUDECODE 미포함"""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            cl._launch_auto_fix_process("r6", "", {}, fake_redis)
        call_kwargs = mock_run.call_args[1]
        env = call_kwargs.get("env", {})
        assert env.get("PYTHONIOENCODING") == "utf-8"
        assert env.get("PLAN_RUNNER_RUNNER_ID") == "r6"
        assert "CLAUDECODE" not in env


# ── Phase T1-3: _do_inline_merge 통합 TC ─────────────────────────────────────

class TestDoInlineMergeIntegration:
    def _make_redis(self, worktree_path=None, plan_file=None, branch=None):
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

    def _merge_lock_patch(self):
        """merge_lock 모듈 전체를 mock (acquire→True, release→None)"""
        import types
        mock_lock_mod = types.ModuleType("merge_lock")
        mock_lock_mod.acquire_merge_lock = MagicMock(return_value=True)
        mock_lock_mod.release_merge_lock = MagicMock()
        return patch.dict("sys.modules", {"merge_lock": mock_lock_mod})

    def test_inline_merge_success_calls_post_merge_pipeline_R(self, cl, tmp_path):
        """R(Right): merge 성공 → _post_merge_pipeline 호출"""
        from merge_workflow import WorkflowResult
        wt_path = tmp_path / "wt_test"
        wt_path.mkdir()
        redis = self._make_redis(worktree_path=wt_path)

        with self._merge_lock_patch(), \
             patch.object(cl, "_post_merge_pipeline", return_value=True) as mock_pipeline, \
             patch("merge_workflow.MergeWorkflow.run",
                   return_value=WorkflowResult(merged=True, tests_passed=True, conflict=False, message="")):
            cl._do_inline_merge("r_success", redis)

        mock_pipeline.assert_called_once()

    def test_inline_merge_pipeline_fail_sets_test_failed_E(self, cl, tmp_path):
        """E(Error): _post_merge_pipeline → False → merge_status="merged" 미설정"""
        from merge_workflow import WorkflowResult
        wt_path = tmp_path / "wt_fail"
        wt_path.mkdir()
        redis = self._make_redis(worktree_path=wt_path)
        set_calls = []
        redis.set.side_effect = lambda k, v: set_calls.append((k, v))

        with self._merge_lock_patch(), \
             patch.object(cl, "_post_merge_pipeline", return_value=False), \
             patch("merge_workflow.MergeWorkflow.run",
                   return_value=WorkflowResult(merged=True, tests_passed=True, conflict=False, message="")):
            cl._do_inline_merge("r_fail", redis)

        # pipeline=False → _do_inline_merge가 return → merge_status="merged" 미설정
        merged_key = f"{cl.RUNNER_KEY_PREFIX}:r_fail:merge_status"
        set_values = {k: v for k, v in set_calls}
        assert set_values.get(merged_key) != "merged"

    def test_inline_merge_pipeline_success_sets_merged_R(self, cl, tmp_path):
        """R(Right): pipeline → True → merge_status="merged" 설정"""
        from merge_workflow import WorkflowResult
        wt_path = tmp_path / "wt_ok"
        wt_path.mkdir()
        redis = self._make_redis(worktree_path=wt_path)
        set_calls = []
        redis.set.side_effect = lambda k, v: set_calls.append((k, v))

        with self._merge_lock_patch(), \
             patch.object(cl, "_post_merge_pipeline", return_value=True), \
             patch.object(cl, "_cleanup_process_state"), \
             patch("merge_workflow.MergeWorkflow.run",
                   return_value=WorkflowResult(merged=True, tests_passed=True, conflict=False, message="")):
            cl._do_inline_merge("r_ok", redis)

        set_values = [v for k, v in set_calls if "merge_status" in k]
        assert "merged" in set_values

    def test_inline_merge_resolve_success_calls_pipeline_R(self, cl, tmp_path):
        """R(Right): conflict → resolve 성공 → _post_merge_pipeline 호출"""
        from merge_workflow import WorkflowResult
        wt_path = tmp_path / "wt_resolve"
        wt_path.mkdir()
        redis = self._make_redis(worktree_path=wt_path, branch="plan/test")

        with self._merge_lock_patch(), \
             patch.object(cl, "_post_merge_pipeline", return_value=True) as mock_pipeline, \
             patch.object(cl, "_cleanup_process_state"), \
             patch.object(cl, "_launch_conflict_resolver_process",
                          return_value={"success": True, "message": "ok"}), \
             patch("subprocess.run") as mock_sp, \
             patch("worktree_manager.WorktreeManager.remove", return_value=True), \
             patch("merge_workflow.MergeWorkflow.run",
                   return_value=WorkflowResult(merged=False, tests_passed=False, conflict=True, message="conflict")):
            mock_sp.return_value = MagicMock(returncode=0, stdout="merge: plan/test", stderr="")
            cl._do_inline_merge("r_resolve", redis)

        mock_pipeline.assert_called_once()

    def test_inline_merge_status_sequence_testing_then_merged_R(self, cl, tmp_path):
        """R(Right): 상태 전이 순서: queued→merging (do_inline_merge) + testing (pipeline 내부) 후 merged"""
        from merge_workflow import WorkflowResult
        wt_path = tmp_path / "wt_seq"
        wt_path.mkdir()
        redis = self._make_redis(worktree_path=wt_path)
        set_calls = []

        runner_id = "t-postmrg-seq"
        RUNNER_KEY_PREFIX = cl.RUNNER_KEY_PREFIX

        def pipeline_side(*a, **kw):
            # pipeline 내부에서 "testing" 설정 (실제 구현과 동일)
            redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "testing")
            set_calls.append((f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "testing"))
            return True

        def set_side(k, v):
            set_calls.append((k, v))

        redis.set.side_effect = set_side

        with self._merge_lock_patch(), \
             patch.object(cl, "_post_merge_pipeline", side_effect=pipeline_side), \
             patch.object(cl, "_cleanup_process_state"), \
             patch("merge_workflow.MergeWorkflow.run",
                   return_value=WorkflowResult(merged=True, tests_passed=True, conflict=False, message="")):
            cl._do_inline_merge(runner_id, redis)

        merge_status_values = [v for k, v in set_calls if "merge_status" in k]
        assert "testing" in merge_status_values
        assert "merged" in merge_status_values
        testing_idx = next(i for i, v in enumerate(merge_status_values) if v == "testing")
        merged_idx = next(i for i, v in enumerate(merge_status_values) if v == "merged")
        assert testing_idx < merged_idx


# ── Phase T1-4: MergeWorkflow 수정 회귀 TC ───────────────────────────────────

class TestMergeWorkflowRegression:
    def test_merge_workflow_run_no_longer_calls_tests_R(self, tmp_path):
        """R(Right): MergeWorkflow.run() 호출 후 run_post_merge_tests 미호출"""
        import fakeredis
        from merge_workflow import MergeWorkflow, TestResult
        import worktree_manager as wm

        wt_path = tmp_path / "wt_reg"
        wt_path.mkdir()
        base_dir = tmp_path / ".worktrees"
        base_dir.mkdir()

        fake_r = fakeredis.FakeRedis(decode_responses=True)
        wf = MergeWorkflow(project_root=tmp_path, redis_client=fake_r, python_path="python")

        with patch("subprocess.run") as mock_run, \
             patch.object(wf, "run_post_merge_tests") as mock_tests, \
             patch.object(wm.WorktreeManager, "merge_to_main",
                          return_value=wm.MergeResult(success=True, conflict=False, message="ok")), \
             patch.object(wm.WorktreeManager, "remove", return_value=True):
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            wf.run("reg1", wt_path, base_dir)

        mock_tests.assert_not_called()

    def test_merge_workflow_run_success_always_tests_passed_true_R(self, tmp_path):
        """R(Right): merge 성공 시 WorkflowResult.tests_passed 항상 True"""
        import fakeredis
        from merge_workflow import MergeWorkflow
        import worktree_manager as wm

        wt_path = tmp_path / "wt_tp"
        wt_path.mkdir()
        base_dir = tmp_path / ".worktrees"
        base_dir.mkdir()

        fake_r = fakeredis.FakeRedis(decode_responses=True)
        wf = MergeWorkflow(project_root=tmp_path, redis_client=fake_r, python_path="python")

        with patch("subprocess.run") as mock_run, \
             patch.object(wm.WorktreeManager, "merge_to_main",
                          return_value=wm.MergeResult(success=True, conflict=False, message="ok")), \
             patch.object(wm.WorktreeManager, "remove", return_value=True):
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = wf.run("reg2", wt_path, base_dir)

        assert result.tests_passed is True
