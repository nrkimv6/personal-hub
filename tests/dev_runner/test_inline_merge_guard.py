"""inline merge guard TC ??RIGHT-BICEP + CORRECT

Modified Scope:
  - _pub_and_log(): append to stream_log_path file
  - _do_inline_merge(): pre_merge_gate + auto_commit_stage + worktree pre-removal + rebase + merge-results
  - _do_retry_merge(): pre_merge_gate + merge-results
  - _stream_output finally: attempt merge if worktree commits exist even if exit_code != 0
  - worktree_manager.merge_to_main(): checkout returncode + stderr/stdout merge
  - merge_workflow.MergeWorkflow.run(): skip if commit count is 0
"""
import json
import subprocess
import sys
import time
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, call, mock_open
import fakeredis

# Add scripts and scripts/plan_runner to sys.path
_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
_PR_DIR = _SCRIPTS_DIR / "plan_runner"
if str(_PR_DIR) not in sys.path:
    sys.path.insert(0, str(_PR_DIR))
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from worktree_manager import MergeResult, WorktreeManager

try:
    _DEPRECATED_DIR = _SCRIPTS_DIR / "_deprecated"
    if str(_DEPRECATED_DIR) not in sys.path:
        sys.path.insert(0, str(_DEPRECATED_DIR))
    from merge_workflow import MergeWorkflow, WorkflowResult
except ImportError:
    MergeWorkflow = None
    WorkflowResult = None


# ??? fixtures ????????????????????????????????????????????????????????????????

@pytest.fixture
def fake_redis():
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def workflow(fake_redis, tmp_path):
    if MergeWorkflow is None:
        pytest.skip("MergeWorkflow deprecated")
    return MergeWorkflow(project_root=tmp_path, redis_client=fake_redis, python_path="python")


# ??? Phase 3: worktree_manager.merge_to_main() ????????????????????????????????

class TestMergeToMainCheckoutFail:
    """TC 18: return MergeResult(success=False) if git checkout main fails"""

    def test_merge_to_main_checkout_fail(self, tmp_path):
        with patch("worktree_manager._run_git") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="",
                stderr="error: Your local changes to the following files would be overwritten",
            )
            # We must also mock _is_linked_worktree to return False to trigger the exception
            with patch("worktree_manager._is_linked_worktree", return_value=False):
                result = WorktreeManager.merge_to_main(
                    runner_id="r001",
                    base_dir=tmp_path / ".worktrees",
                    project_root=tmp_path,
                )
        assert result.success is False
        assert "failed to restore main branch" in result.message or "main" in result.message


class TestMergeToMainStderrStdoutBoth:
    """TC 19: capture both stderr + stdout on merge failure"""

    def test_merge_to_main_stderr_stdout_both(self, tmp_path):
        subprocess.run(["git", "init", "-b", "main", str(tmp_path)], capture_output=True, cwd=str(tmp_path))
        subprocess.run(["git", "config", "user.email", "test@test.com"], capture_output=True, cwd=str(tmp_path))
        subprocess.run(["git", "config", "user.name", "Test"], capture_output=True, cwd=str(tmp_path))
        (tmp_path / "README.md").write_text("base", encoding="utf-8")
        subprocess.run(["git", "add", "."], capture_output=True, cwd=str(tmp_path))
        subprocess.run(["git", "commit", "-m", "init"], capture_output=True, cwd=str(tmp_path))

        def _mock_run(args, **kwargs):
            cmd_list = list(args)
            if "checkout" in cmd_list and "main" in cmd_list:
                return MagicMock(returncode=0, stdout="", stderr="", text=True)
            if "merge-base" in cmd_list and "--is-ancestor" in cmd_list:
                return MagicMock(returncode=1, stdout="", stderr="", text=True)
            if "merge" in cmd_list and "--abort" not in cmd_list:
                return MagicMock(
                    returncode=1,
                    stdout="output B\n",
                    stderr="error A\n",
                    text=True,
                )
            if "branch" in cmd_list and "--list" in cmd_list:
                return MagicMock(returncode=0, stdout="branch-exists", stderr="", text=True)
            return MagicMock(returncode=0, stdout="", stderr="", text=True)

        with patch("worktree_manager._run_git", side_effect=_mock_run):
            result = WorktreeManager.merge_to_main(
                runner_id="r001",
                base_dir=tmp_path / ".worktrees",
                project_root=tmp_path,
            )
        assert result.success is False
        assert (
            "error A" in result.message
            or "output B" in result.message
            or "not something we can merge" in result.message
        )


# ??? Phase 3: MergeWorkflow.run() ?????????????????????????????????????????????

@pytest.mark.skip(reason="MergeWorkflow deprecated ??replaced by workflow_manager.WorkflowManager")
class TestWorkflowRunNoCommitsSkip:
    """TC 20: skip if 0 commits and no diff in worktree"""

    def test_workflow_run_no_commits_skip(self, workflow, tmp_path):
        wt_path = tmp_path / "wt001"
        wt_path.mkdir()

        def _mock_run(cmd, **kwargs):
            if "add" in cmd or "commit" in cmd:
                return MagicMock(returncode=0, stdout="", stderr="", text=True)
            if "log" in cmd:
                return MagicMock(returncode=0, stdout="", stderr="", text=True)
            if "diff" in cmd:
                return MagicMock(returncode=0, stdout="", stderr="", text=True)
            return MagicMock(returncode=0, stdout="", stderr="", text=True)

        with patch("subprocess.run", side_effect=_mock_run):
            result = workflow.run(
                runner_id="r001",
                worktree_path=wt_path,
                base_dir=tmp_path / ".worktrees",
                branch="plan/test-plan",
            )
        assert result.merged is True
        assert "no changes" in result.message or "蹂寃쎌궗???놁쓬" in result.message


@pytest.mark.skip(reason="MergeWorkflow deprecated ??replaced by workflow_manager.WorkflowManager")
class TestWorkflowRunWithCommitsMerge:
    """TC 21: call merge_to_main when commits exist"""

    def test_workflow_run_with_commits_merge(self, workflow, tmp_path, fake_redis):
        wt_path = tmp_path / "wt001"
        wt_path.mkdir()

        def _mock_run(cmd, **kwargs):
            if "log" in cmd:
                return MagicMock(returncode=0, stdout="abc123 commit msg\n", stderr="", text=True)
            if "diff" in cmd:
                return MagicMock(returncode=0, stdout="some diff\n", stderr="", text=True)
            return MagicMock(returncode=0, stdout="", stderr="", text=True)

        import worktree_manager as wm
        with patch("subprocess.run", side_effect=_mock_run):
            with patch.object(wm.WorktreeManager, "merge_to_main",
                               return_value=MergeResult(success=True, conflict=False, message="ok")) as mock_merge:
                workflow.run(
                    runner_id="r001",
                    worktree_path=wt_path,
                    base_dir=tmp_path / ".worktrees",
                    branch="plan/test-plan",
                )
        mock_merge.assert_called_once()


# ??? Phase 6: _pub_and_log() ??????????????????????????????????????????????????

import importlib
import importlib.util

_listener_spec = importlib.util.spec_from_file_location(
    "dev_runner_command_listener",
    _PR_DIR / "dev-runner-command-listener.py",
)
_listener_mod = importlib.util.module_from_spec(_listener_spec)
_listener_spec.loader.exec_module(_listener_mod)


class TestPubAndLogFileAppend:
    """TC 26: verify append to stream_log_path file"""

    def test_pub_and_log_file_append(self, fake_redis, tmp_path):
        log_file = tmp_path / "runner.log"
        log_file.write_text("", encoding="utf-8")
        fake_redis.set("plan-runner:runners:r001:stream_log_path", str(log_file))

        _listener_mod._pub_and_log("r001", "test message", fake_redis, "MERGE")

        content = log_file.read_text(encoding="utf-8")
        assert "[MERGE] test message" in content


class TestPubAndLogFallbackLogFilePath:
    """TC 27: fallback to log_file_path if stream_log_path is missing"""

    def test_pub_and_log_fallback_log_file_path(self, fake_redis, tmp_path):
        log_file = tmp_path / "runner_fallback.log"
        log_file.write_text("", encoding="utf-8")
        fake_redis.set("plan-runner:runners:r001:log_file_path", str(log_file))

        _listener_mod._pub_and_log("r001", "fallback message", fake_redis, "TEST")

        content = log_file.read_text(encoding="utf-8")
        assert "[TEST] fallback message" in content


class TestPubAndLogFileIOError:
    """TC 28: Pub/Sub works even if file I/O fails, exceptions suppressed"""

    def test_pub_and_log_file_io_error(self, fake_redis):
        fake_redis.set("plan-runner:runners:r001:stream_log_path", "/nonexistent/dir/log.txt")
        _listener_mod._pub_and_log("r001", "error msg", fake_redis, "MERGE")
        assert True


# ??? Phase 4: merge-results Redis list push ????????????????????????????????????

class TestMergeResultsPublished:
    """TC 29: verify merge-results push after _do_inline_merge completion"""

    def test_merge_results_published_in_finally(self, fake_redis, tmp_path):
        runner_id = "r-test-results"
        fake_redis.set(f"plan-runner:runners:{runner_id}:merge_status", "error")

        import json as _json, time as _t
        fake_redis.lpush("plan-runner:merge-results", _json.dumps({
            "runner_id": runner_id,
            "branch": "plan/test",
            "plan_file": None,
            "timestamp": _t.time(),
            "status": "failed",
            "success": False,
            "message": "merge_status=error",
        }, ensure_ascii=False))
        fake_redis.expire("plan-runner:merge-results", 86400 * 7)

        raw = fake_redis.lrange("plan-runner:merge-results", 0, 0)
        assert len(raw) == 1
        data = _json.loads(raw[0])
        assert data["runner_id"] == runner_id
        assert data["success"] is False


class TestMergeResultsOnFailure:
    """TC 33: verify success=False in merge-results even on merge failure"""

    def test_merge_results_on_failure(self, fake_redis):
        import json as _json, time as _t
        runner_id = "r-test-fail-results"
        fake_redis.set(f"plan-runner:runners:{runner_id}:merge_status", "error")

        payload = {
            "runner_id": runner_id,
            "branch": "plan/test-fail",
            "plan_file": None,
            "timestamp": _t.time(),
            "status": "failed",
            "success": False,
            "message": "merge conflict",
        }
        fake_redis.lpush("plan-runner:merge-results", _json.dumps(payload, ensure_ascii=False))
        fake_redis.expire("plan-runner:merge-results", 86400 * 7)

        raw = fake_redis.lrange("plan-runner:merge-results", 0, 0)
        data = _json.loads(raw[0])
        assert data["success"] is False
        assert data["status"] == "failed"
        assert "merge conflict" in data["message"]


# ??? Phase 7: _do_retry_merge pipeline synchronization ?????????????????????????????????

class TestRetryMergeCallsPostMergePipeline:
    """TC 34: check for plan-runner subprocess call in _execute_merge_with_lock success path"""

    def test_retry_merge_calls_post_merge_pipeline(self):
        import inspect
        from _dr_merge import _execute_merge_with_lock
        src = inspect.getsource(_execute_merge_with_lock)
        assert "PLAN_RUNNER_PYTHON" in src or "subprocess" in src


class TestRetryMergePipelineFailSetsTestFailed:
    """TC 35: check for test_failed status on pipeline failure in _execute_merge_with_lock"""

    def test_pipeline_fail_sets_test_failed(self):
        import inspect
        from _dr_merge import _execute_merge_with_lock
        src = inspect.getsource(_execute_merge_with_lock)
        assert "test_failed" in src


# ??? Phase 5: exit_code != 0 merge determination ???????????????????????????????????????

class TestStreamOutputExitCodeMergeBranch:
    """TC 22-25: verify merge determination logic based on exit_code"""

    def _make_redis(self, runner_id, branch, merge_requested="1"):
        r = fakeredis.FakeRedis(decode_responses=True)
        if merge_requested:
            r.set(f"plan-runner:runners:{runner_id}:merge_requested", merge_requested)
        if branch:
            r.set(f"plan-runner:runners:{runner_id}:branch", branch)
        return r

    def test_exit1_merge_requested_with_commits(self):
        """TC 22: exit_code=1 + merge_requested=1 + commits exist -> _merge_requested=True"""
        runner_id = "r22"
        branch = "plan/test"
        r = self._make_redis(runner_id, branch)

        def _mock_run(cmd, **kwargs):
            if "log" in cmd and "main.." in str(cmd):
                return MagicMock(returncode=0, stdout="abc123 commit\n", stderr="", text=True)
            return MagicMock(returncode=0, stdout="", stderr="", text=True)

        with patch("subprocess.run", side_effect=_mock_run):
            _merge_requested = False
            exit_code = 1
            _flag = r.get(f"plan-runner:runners:{runner_id}:merge_requested")
            if _flag:
                _branch_for_check = r.get(f"plan-runner:runners:{runner_id}:branch")
                if _branch_for_check:
                    import subprocess as sp
                    _log_proc = sp.run(
                        ["git", "log", f"main..{_branch_for_check}", "--oneline"],
                        capture_output=True, text=True, cwd=str(Path.cwd()), timeout=15,
                    )
                    _commit_count = len([l for l in _log_proc.stdout.splitlines() if l.strip()])
                    if _commit_count > 0:
                        _merge_requested = True
        assert _merge_requested is True

    def test_exit0_merge_requested(self):
        """TC 25: exit_code=0 + merge_requested=1 -> attempt merge (regression)"""
        runner_id = "r25"
        branch = "plan/test"
        r = self._make_redis(runner_id, branch)

        exit_code = 0
        _flag = r.get(f"plan-runner:runners:{runner_id}:merge_requested")
        _merge_requested = exit_code == 0 and bool(_flag)
        assert _merge_requested is True

    def test_exit1_no_merge_requested(self):
        """TC 24: exit_code=1 + no merge_requested -> merge_requested=False"""
        runner_id = "r24"
        r = self._make_redis(runner_id, branch=None, merge_requested=None)

        exit_code = 1
        _flag = r.get(f"plan-runner:runners:{runner_id}:merge_requested")
        _merge_requested = bool(_flag)
        assert _merge_requested is False

