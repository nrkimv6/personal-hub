"""
TC: ConflictResolver → plan-runner resolve 전환 단위/통합 테스트

Phase T1: _launch_conflict_resolver_process 단위 테스트
Phase T1-2: _do_inline_merge conflict auto-retry
Phase T1-3: _do_resolve_conflict 전환
Phase T1-4: worktree_manager / MergeWorkflow 정리
"""
import inspect
import json
import subprocess
import sys
import types
import importlib
import importlib.util
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

_SCRIPT_PATH = Path(__file__).parent.parent.parent / "scripts" / "dev-runner-command-listener.py"
_mock_noise = types.ModuleType("listener_noise_filter")
_mock_noise.NOISE_BLOCK_MARKERS = []
_mock_noise.is_noise_line = lambda line: False

RESULTS_KEY = "plan-runner:command_results"
RUNNER_KEY_PREFIX = "plan-runner:runners"
ACTIVE_RUNNERS_KEY = "plan-runner:active_runners"


def _load_listener():
    sys.modules["listener_noise_filter"] = _mock_noise
    spec = importlib.util.spec_from_file_location("_listener_cr", _SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    mod._running_processes = {}
    mod._running_log_files = {}
    mod._stream_threads = {}
    spec.loader.exec_module(mod)
    return mod


def make_redis_mock(worktree_path=None, plan_file=None, branch=None):
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


# ---------------------------------------------------------------------------
# Phase T1: _launch_conflict_resolver_process 단위 테스트
# ---------------------------------------------------------------------------

class TestLaunchConflictResolverProcess:
    def test_launch_conflict_resolver_process_cmd_R(self, tmp_path):
        """R(Right): plan-runner resolve 커맨드 빌드 확인"""
        cl = _load_listener()
        redis = make_redis_mock(worktree_path=str(tmp_path))

        with patch.object(cl, "_run_subprocess_streaming", return_value={"success": True, "message": "ok", "output": "ok"}) as mock_run:
            result = cl._launch_conflict_resolver_process(
                "runner-01", "plan/test", tmp_path, redis
            )

        assert result["success"] is True
        call_args = mock_run.call_args[1].get("cmd")
        assert "resolve" in call_args
        assert "--branch" in call_args
        assert "plan/test" in call_args
        assert "--project-dir" in call_args

    def test_launch_conflict_resolver_process_env_R(self, tmp_path):
        """R(Right): 환경변수 세팅 확인"""
        cl = _load_listener()
        redis = make_redis_mock()

        with patch.object(cl, "_run_subprocess_streaming", return_value={"success": True, "message": "ok", "output": ""}) as mock_run:
            cl._launch_conflict_resolver_process("runner-01", "plan/test", tmp_path, redis)

        call_kwargs = mock_run.call_args[1]
        env = call_kwargs.get("env", {})
        assert env.get("PYTHONIOENCODING") == "utf-8"
        assert env.get("PLAN_RUNNER_RUNNER_ID") == "runner-01"
        assert "PLAN_RUNNER_WORK_DIR" in env
        assert "CLAUDECODE" not in env

    def test_launch_conflict_resolver_process_success_R(self, tmp_path):
        """R(Right): exit_code=0 → 성공 반환"""
        cl = _load_listener()
        redis = make_redis_mock()

        with patch.object(cl, "_run_subprocess_streaming", return_value={"success": True, "message": "ok", "output": "auto-resolve 성공"}):
            result = cl._launch_conflict_resolver_process("r01", "plan/test", tmp_path, redis)

        assert result["success"] is True

    def test_launch_conflict_resolver_process_failure_E(self, tmp_path):
        """E(Error): exit_code=1 → 실패 반환"""
        cl = _load_listener()
        redis = make_redis_mock()

        with patch.object(cl, "_run_subprocess_streaming", return_value={"success": False, "message": "conflict markers remain", "output": ""}):
            result = cl._launch_conflict_resolver_process("r01", "plan/test", tmp_path, redis)

        assert result["success"] is False
        assert "message" in result

    def test_launch_conflict_resolver_process_timeout_E(self, tmp_path):
        """E(Error): 타임아웃 시 실패 반환"""
        cl = _load_listener()
        redis = make_redis_mock()

        with patch.object(cl, "_run_subprocess_streaming", return_value={"success": False, "message": "RESOLVE timeout (300s)", "output": ""}):
            result = cl._launch_conflict_resolver_process("r01", "plan/test", tmp_path, redis)

        assert result["success"] is False
        assert "timeout" in result["message"].lower()

    def test_launch_conflict_resolver_process_logs_stdout_B(self, tmp_path):
        """B(Boundary): pub_fn에 stdout 전달 확인"""
        cl = _load_listener()
        redis = make_redis_mock()
        pub_fn = MagicMock()

        def mock_run_streaming(cmd, env, cwd, pub_fn, tag, timeout):
            pub_fn(f"[{tag}] resolve log output")
            return {"success": True, "message": "ok", "output": "resolve log output"}

        with patch.object(cl, "_run_subprocess_streaming", side_effect=mock_run_streaming):
            cl._launch_conflict_resolver_process("r01", "plan/test", tmp_path, redis, pub_fn=pub_fn)

        pub_fn.assert_called()
        all_calls = " ".join(str(c) for c in pub_fn.call_args_list)
        assert "resolve log output" in all_calls


# ---------------------------------------------------------------------------
# Phase T1-2: _do_inline_merge conflict auto-retry
# ---------------------------------------------------------------------------

class TestInlineMergeConflictAutoRetry:
    def test_inline_merge_conflict_auto_retry_R(self, tmp_path):
        """R(Right): conflict 시 _launch_conflict_resolver_process 자동 호출"""
        cl = _load_listener()

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        runner_id = "t-conflict-01"
        redis = make_redis_mock(worktree_path=str(worktree), branch="plan/test")

        from merge_workflow import WorkflowResult
        mock_result = WorkflowResult(merged=False, tests_passed=False, conflict=True, message="conflict")

        with patch("merge_workflow.MergeWorkflow") as mock_wf_cls, \
             patch("merge_lock.acquire_merge_lock", return_value=True), \
             patch("merge_lock.release_merge_lock"), \
             patch("plan_runner.core.pipeline.pre_merge_gate", return_value=(True, "ok")), \
             patch.object(cl, "_launch_conflict_resolver_process", return_value={"success": False, "message": "fail"}) as mock_resolve, \
             patch.object(cl, "_cleanup_process_state"):
            mock_wf = MagicMock()
            mock_wf.run.return_value = mock_result
            mock_wf_cls.return_value = mock_wf
            cl._do_inline_merge(runner_id, redis)

        mock_resolve.assert_called_once()

    def test_inline_merge_conflict_auto_retry_success_R(self, tmp_path):
        """R(Right): resolve 성공 → merge_status='merged' 전이"""
        cl = _load_listener()

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        runner_id = "t-conflict-02"
        redis = make_redis_mock(worktree_path=str(worktree), branch="plan/test")

        merge_status_sequence = []

        def track_set(key, value, *args, **kwargs):
            if "merge_status" in key:
                merge_status_sequence.append(value)
            return True

        redis.set.side_effect = track_set

        from merge_workflow import WorkflowResult
        mock_result = WorkflowResult(merged=False, tests_passed=False, conflict=True, message="conflict")

        mock_proc = MagicMock()
        mock_proc.stdout = "merge: plan/test"
        mock_proc.returncode = 0

        with patch("merge_workflow.MergeWorkflow") as mock_wf_cls, \
             patch("merge_lock.acquire_merge_lock", return_value=True), \
             patch("merge_lock.release_merge_lock"), \
             patch("plan_runner.core.pipeline.pre_merge_gate", return_value=(True, "ok")), \
             patch.object(cl, "_launch_conflict_resolver_process", return_value={"success": True, "message": "ok"}), \
             patch.object(cl, "_post_merge_pipeline", return_value=True), \
             patch.object(cl, "_cleanup_process_state"), \
             patch("subprocess.run", return_value=mock_proc), \
             patch("worktree_manager.WorktreeManager.remove", return_value=True):
            mock_wf = MagicMock()
            mock_wf.run.return_value = mock_result
            mock_wf_cls.return_value = mock_wf
            cl._do_inline_merge(runner_id, redis)

        assert "resolving" in merge_status_sequence
        assert "merged" in merge_status_sequence

    def test_inline_merge_conflict_auto_retry_failure_E(self, tmp_path):
        """E(Error): resolve 실패 → merge_status='conflict' 최종"""
        cl = _load_listener()

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        runner_id = "t-conflict-03"
        redis = make_redis_mock(worktree_path=str(worktree), branch="plan/test")

        merge_status_sequence = []

        def track_set(key, value, *args, **kwargs):
            if "merge_status" in key:
                merge_status_sequence.append(value)
            return True

        redis.set.side_effect = track_set

        from merge_workflow import WorkflowResult
        mock_result = WorkflowResult(merged=False, tests_passed=False, conflict=True, message="conflict")

        with patch("merge_workflow.MergeWorkflow") as mock_wf_cls, \
             patch("merge_lock.acquire_merge_lock", return_value=True), \
             patch("merge_lock.release_merge_lock"), \
             patch("plan_runner.core.pipeline.pre_merge_gate", return_value=(True, "ok")), \
             patch.object(cl, "_launch_conflict_resolver_process", return_value={"success": False, "message": "markers remain"}), \
             patch.object(cl, "_cleanup_process_state"):
            mock_wf = MagicMock()
            mock_wf.run.return_value = mock_result
            mock_wf_cls.return_value = mock_wf
            cl._do_inline_merge(runner_id, redis)

        assert merge_status_sequence[-1] == "conflict"

    def test_inline_merge_conflict_resolve_success_removes_worktree_R(self, tmp_path):
        """R(Right): auto-resolve 성공 시 WorktreeManager.remove() 호출됨"""
        cl = _load_listener()

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        runner_id = "t-conflict-04"
        redis = make_redis_mock(worktree_path=str(worktree), branch="plan/test")

        from merge_workflow import WorkflowResult
        mock_result = WorkflowResult(merged=False, tests_passed=False, conflict=True, message="conflict")

        mock_proc = MagicMock()
        mock_proc.stdout = "merge: plan/test"
        mock_proc.returncode = 0

        with patch("merge_workflow.MergeWorkflow") as mock_wf_cls, \
             patch("merge_lock.acquire_merge_lock", return_value=True), \
             patch("merge_lock.release_merge_lock"), \
             patch("plan_runner.core.pipeline.pre_merge_gate", return_value=(True, "ok")), \
             patch.object(cl, "_launch_conflict_resolver_process", return_value={"success": True, "message": "ok"}), \
             patch.object(cl, "_post_merge_pipeline", return_value=True), \
             patch.object(cl, "_cleanup_process_state"), \
             patch("subprocess.run", return_value=mock_proc), \
             patch("worktree_manager.WorktreeManager.remove") as mock_remove:
            mock_wf = MagicMock()
            mock_wf.run.return_value = mock_result
            mock_wf_cls.return_value = mock_wf
            cl._do_inline_merge(runner_id, redis)

        mock_remove.assert_called_once()
        call_kwargs = mock_remove.call_args
        assert call_kwargs[0][0] == runner_id
        assert call_kwargs[1].get("branch") == "plan/test"

    def test_inline_merge_conflict_resolve_success_remove_failure_ignored_E(self, tmp_path):
        """E(Error): WorktreeManager.remove() 예외 시 merge_status 여전히 'merged'"""
        cl = _load_listener()

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        runner_id = "t-conflict-05"
        redis = make_redis_mock(worktree_path=str(worktree), branch="plan/test")

        merge_status_sequence = []

        def track_set(key, value, *args, **kwargs):
            if "merge_status" in key:
                merge_status_sequence.append(value)
            return True

        redis.set.side_effect = track_set

        from merge_workflow import WorkflowResult
        mock_result = WorkflowResult(merged=False, tests_passed=False, conflict=True, message="conflict")

        mock_proc = MagicMock()
        mock_proc.stdout = "merge: plan/test"
        mock_proc.returncode = 0

        with patch("merge_workflow.MergeWorkflow") as mock_wf_cls, \
             patch("merge_lock.acquire_merge_lock", return_value=True), \
             patch("merge_lock.release_merge_lock"), \
             patch("plan_runner.core.pipeline.pre_merge_gate", return_value=(True, "ok")), \
             patch.object(cl, "_launch_conflict_resolver_process", return_value={"success": True, "message": "ok"}), \
             patch.object(cl, "_post_merge_pipeline", return_value=True), \
             patch.object(cl, "_cleanup_process_state"), \
             patch("subprocess.run", return_value=mock_proc), \
             patch("worktree_manager.WorktreeManager.remove", side_effect=Exception("rm fail")):
            mock_wf = MagicMock()
            mock_wf.run.return_value = mock_result
            mock_wf_cls.return_value = mock_wf
            cl._do_inline_merge(runner_id, redis)

        assert "merged" in merge_status_sequence

    def test_inline_merge_conflict_verify_exception_removes_worktree_B(self, tmp_path):
        """B(Boundary): verify 예외 경로에서도 WorktreeManager.remove() 호출됨"""
        cl = _load_listener()

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        runner_id = "t-conflict-06"
        redis = make_redis_mock(worktree_path=str(worktree), branch="plan/test")

        from merge_workflow import WorkflowResult
        mock_result = WorkflowResult(merged=False, tests_passed=False, conflict=True, message="conflict")

        with patch("merge_workflow.MergeWorkflow") as mock_wf_cls, \
             patch("merge_lock.acquire_merge_lock", return_value=True), \
             patch("merge_lock.release_merge_lock"), \
             patch("plan_runner.core.pipeline.pre_merge_gate", return_value=(True, "ok")), \
             patch.object(cl, "_launch_conflict_resolver_process", return_value={"success": True, "message": "ok"}), \
             patch.object(cl, "_post_merge_pipeline", return_value=True), \
             patch.object(cl, "_cleanup_process_state"), \
             patch("subprocess.run", side_effect=Exception("verify fail")), \
             patch("worktree_manager.WorktreeManager.remove") as mock_remove:
            mock_wf = MagicMock()
            mock_wf.run.return_value = mock_result
            mock_wf_cls.return_value = mock_wf
            cl._do_inline_merge(runner_id, redis)

        mock_remove.assert_called_once()


# ---------------------------------------------------------------------------
# Phase T1-3: _do_resolve_conflict 전환
# ---------------------------------------------------------------------------

class TestDoResolveConflictTransition:
    def test_do_resolve_conflict_uses_plan_runner_R(self, tmp_path):
        """R(Right): plan-runner resolve 호출 (ConflictResolver.try_resolve 미호출)"""
        cl = _load_listener()
        redis = make_redis_mock(worktree_path=str(tmp_path), branch="plan/test")

        with patch.object(cl, "_launch_conflict_resolver_process", return_value={"success": True, "message": "ok"}) as mock_resolve:
            cl._do_resolve_conflict("runner-01", redis, "cmd-001")

        mock_resolve.assert_called_once()

    def test_do_resolve_conflict_success_sets_merged_R(self, tmp_path):
        """R(Right): 성공 시 merge_status='merged' + result_key에 push"""
        cl = _load_listener()
        redis = make_redis_mock(worktree_path=str(tmp_path), branch="plan/test")

        with patch.object(cl, "_launch_conflict_resolver_process", return_value={"success": True, "message": "ok"}):
            cl._do_resolve_conflict("runner-01", redis, "cmd-001")

        set_calls = [c for c in redis.set.call_args_list if "merge_status" in str(c)]
        assert any("merged" in str(c) for c in set_calls)
        lpush_calls = [c for c in redis.lpush.call_args_list]
        assert lpush_calls
        pushed = json.loads(lpush_calls[-1][0][1])
        assert pushed["success"] is True

    def test_do_resolve_conflict_failure_sets_conflict_E(self, tmp_path):
        """E(Error): 실패 시 merge_status='conflict' + 실패 result push"""
        cl = _load_listener()
        redis = make_redis_mock(worktree_path=str(tmp_path), branch="plan/test")

        with patch.object(cl, "_launch_conflict_resolver_process", return_value={"success": False, "message": "fail"}):
            cl._do_resolve_conflict("runner-01", redis, "cmd-001")

        set_calls = [c for c in redis.set.call_args_list if "merge_status" in str(c)]
        assert any("conflict" in str(c) for c in set_calls)
        lpush_calls = [c for c in redis.lpush.call_args_list]
        assert lpush_calls
        pushed = json.loads(lpush_calls[-1][0][1])
        assert pushed["success"] is False


# ---------------------------------------------------------------------------
# Phase T1-4: worktree_manager / MergeWorkflow 정리
# ---------------------------------------------------------------------------

class TestWorktreeManagerMergeWorkflowCleanup:
    def test_merge_to_main_no_auto_resolve_B(self):
        """B(Boundary): merge_to_main 시그니처에 auto_resolve 없음"""
        from worktree_manager import WorktreeManager
        sig = inspect.signature(WorktreeManager.merge_to_main)
        assert "auto_resolve" not in sig.parameters

    def test_merge_to_main_conflict_returns_abort_R(self, tmp_path):
        """R(Right): conflict 시 abort + MergeResult(conflict=True) 반환"""
        from worktree_manager import WorktreeManager

        with patch("subprocess.run") as mock_run:
            # 1. checkout main
            # 2. is-ancestor
            # 3. merge (fail)
            # 4. merge --abort
            mock_run.side_effect = [
                MagicMock(returncode=0),  # git checkout main
                MagicMock(returncode=1),  # git merge-base --is-ancestor (not ancestor)
                MagicMock(returncode=1, stderr="conflict", stdout="CONFLICT (content): Merge conflict in a.py"),  # git merge → fail
                MagicMock(returncode=0),  # git merge --abort
            ]
            result = WorktreeManager.merge_to_main("runner-01", tmp_path, tmp_path)

        assert result.conflict is True
        assert result.success is False
        abort_calls = [c for c in mock_run.call_args_list if "--abort" in str(c)]
        assert abort_calls

    def test_merge_workflow_sets_merge_status_R(self, tmp_path):
        """R(Right): MergeWorkflow.run()이 merge_status를 직접 설정함"""
        from merge_workflow import MergeWorkflow

        redis = MagicMock()
        wf = MergeWorkflow(project_root=tmp_path, redis_client=redis, workflow_manager=None)

        with patch("worktree_manager.WorktreeManager.merge_to_main") as mock_merge, \
             patch("subprocess.run"):
            from worktree_manager import MergeResult
            mock_merge.return_value = MergeResult(success=False, conflict=True, message="conflict")
            wf.run("runner-01", tmp_path, tmp_path)

        set_calls = [c for c in redis.set.call_args_list if "merge_status" in str(c)]
        assert any("conflict" in str(c) for c in set_calls), f"MergeWorkflow가 conflict 상태를 설정하지 않음: {set_calls}"

    def test_conflict_analyzer_preserved_R(self, tmp_path):
        """R(Right): ConflictAnalyzer 유틸 기능 유지 확인 (회귀)"""
        from conflict_resolver import ConflictAnalyzer
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="a.py\nb.py\n")
            files = ConflictAnalyzer.get_conflict_files(tmp_path)
        assert "a.py" in files
        assert "b.py" in files

    def test_conflict_resolver_deprecated_docstring_R(self):
        """R(Right): deprecated 주석 존재"""
        import conflict_resolver
        assert conflict_resolver.__doc__ is not None
        assert "DEPRECATED" in conflict_resolver.__doc__
