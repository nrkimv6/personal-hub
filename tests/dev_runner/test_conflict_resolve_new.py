import json
import sys
import inspect
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

# scripts 디렉토리 경로 추가
_scripts_dir = str(Path(__file__).parent.parent.parent / "scripts")
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

def _load_listener():
    import importlib.util
    from pathlib import Path
    script_path = Path(__file__).parent.parent.parent / "scripts" / "dev-runner-command-listener.py"
    spec = importlib.util.spec_from_file_location("dev_runner_command_listener", str(script_path))
    module = importlib.util.module_from_spec(spec)
    # Mock some module-level constants
    module.PROJECT_ROOT = Path(__file__).parent.parent.parent
    module.WORKTREE_BASE_DIR = module.PROJECT_ROOT / ".worktrees"
    # D:/work/project/tools/monitor-page -> D:/work/project -> D:/work/project/service/wtools/...
    module.PLAN_RUNNER_MODULE_PATH = module.PROJECT_ROOT.parent.parent / "service/wtools/common/tools/plan-runner"
    
    # Ensure PLAN_RUNNER_MODULE_PATH is in sys.path so patches work
    if str(module.PLAN_RUNNER_MODULE_PATH) not in sys.path:
        sys.path.insert(0, str(module.PLAN_RUNNER_MODULE_PATH))
        
    spec.loader.exec_module(module)
    return module

def make_redis_mock(worktree_path=None, branch=None, plan_file=None):
    mock = MagicMock()
    storage = {}
    
    def _get(key):
        if "worktree_path" in key: return worktree_path
        if "branch" in key: return branch
        if "plan_file" in key: return plan_file
        return storage.get(key)
        
    def _set(key, val, *args, **kwargs):
        storage[key] = val
        return True
        
    mock.get.side_effect = _get
    mock.set.side_effect = _set
    return mock

# ---------------------------------------------------------------------------
# Phase T1-2: _do_inline_merge conflict auto-retry
# ---------------------------------------------------------------------------

@pytest.mark.skip(reason="_do_inline_merge가 plan-runner post-merge subprocess로 교체됨 (unify-merge-pipeline todo-4). conflict 처리는 plan-runner 내부에서 수행. exit_code=3→conflict는 test_post_merge_pipeline.py에서 커버.")
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
             patch("core.merge._rebase_branch_onto_main", return_value={"success": True}), \
             patch.object(cl, "_launch_conflict_resolver_process", return_value={"success": False, "message": "fail"}) as mock_resolve, \
             patch.object(cl, "_cleanup_process_state"), \
             patch.object(cl.WorktreeManager, "remove", return_value=True):
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
            if "merge_status" in key: merge_status_sequence.append(value)
            return True
        redis.set.side_effect = track_set

        from merge_workflow import WorkflowResult
        mock_result = WorkflowResult(merged=False, tests_passed=False, conflict=True, message="conflict")

        def mock_run_fn(cmd, *args, **kwargs):
            m = MagicMock()
            m.returncode = 0
            if "log" in cmd: m.stdout = "merge: plan/test"
            else: m.stdout = ""
            return m

        with patch("merge_workflow.MergeWorkflow") as mock_wf_cls, \
             patch("merge_lock.acquire_merge_lock", return_value=True), \
             patch("merge_lock.release_merge_lock"), \
             patch("plan_runner.core.pipeline.pre_merge_gate", return_value=(True, "ok")), \
             patch("core.merge._rebase_branch_onto_main", return_value={"success": True}), \
             patch.object(cl, "_launch_conflict_resolver_process", return_value={"success": True, "message": "ok"}), \
             patch.object(cl, "_post_merge_pipeline", return_value=True), \
             patch.object(cl, "_cleanup_process_state"), \
             patch("subprocess.run", side_effect=mock_run_fn), \
             patch.object(cl.WorktreeManager, "remove", return_value=True):
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
            if "merge_status" in key: merge_status_sequence.append(value)
            return True
        redis.set.side_effect = track_set

        from merge_workflow import WorkflowResult
        mock_result = WorkflowResult(merged=False, tests_passed=False, conflict=True, message="conflict")

        with patch("merge_workflow.MergeWorkflow") as mock_wf_cls, \
             patch("merge_lock.acquire_merge_lock", return_value=True), \
             patch("merge_lock.release_merge_lock"), \
             patch("plan_runner.core.pipeline.pre_merge_gate", return_value=(True, "ok")), \
             patch("core.merge._rebase_branch_onto_main", return_value={"success": True}), \
             patch.object(cl, "_launch_conflict_resolver_process", return_value={"success": False, "message": "markers remain"}), \
             patch.object(cl, "_cleanup_process_state"), \
             patch("subprocess.run", return_value=MagicMock(returncode=0)), \
             patch.object(cl.WorktreeManager, "remove", return_value=True):
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

        def mock_run_fn(cmd, *args, **kwargs):
            m = MagicMock()
            m.returncode = 0
            if "log" in cmd: m.stdout = "merge: plan/test"
            else: m.stdout = ""
            return m

        with patch("merge_workflow.MergeWorkflow") as mock_wf_cls, \
             patch("merge_lock.acquire_merge_lock", return_value=True), \
             patch("merge_lock.release_merge_lock"), \
             patch("plan_runner.core.pipeline.pre_merge_gate", return_value=(True, "ok")), \
             patch("core.merge._rebase_branch_onto_main", return_value={"success": True}), \
             patch.object(cl, "_launch_conflict_resolver_process", return_value={"success": True, "message": "ok"}), \
             patch.object(cl, "_post_merge_pipeline", return_value=True), \
             patch.object(cl, "_cleanup_process_state"), \
             patch("subprocess.run", side_effect=mock_run_fn), \
             patch.object(cl.WorktreeManager, "remove") as mock_remove:
            mock_wf = MagicMock()
            mock_wf.run.return_value = mock_result
            mock_wf_cls.return_value = mock_wf
            cl._do_inline_merge(runner_id, redis)

        assert mock_remove.called

    def test_inline_merge_conflict_resolve_success_remove_failure_ignored_E(self, tmp_path):
        """E(Error): WorktreeManager.remove() 예외 시 merge_status 여전히 'merged'"""
        cl = _load_listener()

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        runner_id = "t-conflict-05"
        redis = make_redis_mock(worktree_path=str(worktree), branch="plan/test")

        merge_status_sequence = []
        def track_set(key, value, *args, **kwargs):
            if "merge_status" in key: merge_status_sequence.append(value)
            return True
        redis.set.side_effect = track_set

        from merge_workflow import WorkflowResult
        mock_result = WorkflowResult(merged=False, tests_passed=False, conflict=True, message="conflict")

        def mock_run_fn(cmd, *args, **kwargs):
            m = MagicMock()
            m.returncode = 0
            if "log" in cmd: m.stdout = "merge: plan/test"
            else: m.stdout = ""
            return m

        with patch("merge_workflow.MergeWorkflow") as mock_wf_cls, \
             patch("merge_lock.acquire_merge_lock", return_value=True), \
             patch("merge_lock.release_merge_lock"), \
             patch("plan_runner.core.pipeline.pre_merge_gate", return_value=(True, "ok")), \
             patch("core.merge._rebase_branch_onto_main", return_value={"success": True}), \
             patch.object(cl, "_launch_conflict_resolver_process", return_value={"success": True, "message": "ok"}), \
             patch.object(cl, "_post_merge_pipeline", return_value=True), \
             patch.object(cl, "_cleanup_process_state"), \
             patch("subprocess.run", side_effect=mock_run_fn), \
             patch.object(cl.WorktreeManager, "remove", side_effect=Exception("rm fail")):
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

        def mock_run_fail(cmd, *args, **kwargs):
            if "log" in cmd:
                raise Exception("verify fail")
            return MagicMock(returncode=0, stdout="")

        with patch("merge_workflow.MergeWorkflow") as mock_wf_cls, \
             patch("merge_lock.acquire_merge_lock", return_value=True), \
             patch("merge_lock.release_merge_lock"), \
             patch("plan_runner.core.pipeline.pre_merge_gate", return_value=(True, "ok")), \
             patch("core.merge._rebase_branch_onto_main", return_value={"success": True}), \
             patch.object(cl, "_launch_conflict_resolver_process", return_value={"success": True, "message": "ok"}), \
             patch.object(cl, "_post_merge_pipeline", return_value=True), \
             patch.object(cl, "_cleanup_process_state"), \
             patch("subprocess.run", side_effect=mock_run_fail), \
             patch.object(cl.WorktreeManager, "remove") as mock_remove:
            mock_wf = MagicMock()
            mock_wf.run.return_value = mock_result
            mock_wf_cls.return_value = mock_wf
            cl._do_inline_merge(runner_id, redis)

        assert mock_remove.called
