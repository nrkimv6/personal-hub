"""MergeWorkflow 유닛 테스트 — RIGHT-BICEP + CORRECT"""
import subprocess
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, call
import fakeredis
import logging

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from merge_workflow import MergeWorkflow, WorkflowResult, TestResult
from worktree_manager import MergeResult, WorktreeManager


@pytest.fixture
def fake_redis():
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def workflow(fake_redis, tmp_path):
    return MergeWorkflow(project_root=tmp_path, redis_client=fake_redis, python_path="python")


# ── run() ────────────────────────────────────────────────────────────────────

class TestMergeWorkflowRun:
    def test_right_success_calls_merge_and_tests(self, workflow, tmp_path):
        """TC-Right: runner 성공 → 머지 성공 → WorkflowResult(merged=True, tests_passed=True)"""
        wt_path = tmp_path / "wt001"
        wt_path.mkdir()
        base_dir = tmp_path / ".worktrees"
        base_dir.mkdir()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            import worktree_manager as wm
            with patch.object(wm.WorktreeManager, "merge_to_main",
                               return_value=MergeResult(success=True, conflict=False, message="ok")):
                result = workflow.run("wt001", wt_path, base_dir)

        assert result.merged is True
        assert result.tests_passed is True

    def test_right_success_calls_remove(self, workflow, tmp_path):
        """TC-Right: 머지 성공 + 테스트 통과 → WorktreeManager.remove() 호출"""
        wt_path = tmp_path / "wt002"
        wt_path.mkdir()
        base_dir = tmp_path / ".worktrees"
        base_dir.mkdir()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            # WorktreeManager는 scripts/ sys.path로 import됨
            import worktree_manager as wm
            with patch.object(wm.WorktreeManager, "merge_to_main",
                               return_value=MergeResult(success=True, conflict=False, message="ok")):
                with patch.object(wm.WorktreeManager, "remove", return_value=True) as mock_remove:
                    workflow.run("wt002", wt_path, base_dir)

        mock_remove.assert_called_once_with("wt002", base_dir, plan_file=None, branch=None)

    def test_workflow_run_passes_branch_to_merge(self, workflow, tmp_path):
        """TC-Right: branch='plan/x' 전달 시 merge_to_main(branch='plan/x') 호출"""
        wt_path = tmp_path / "wt_branch1"
        wt_path.mkdir()
        base_dir = tmp_path / ".worktrees"
        base_dir.mkdir()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            import worktree_manager as wm
            with patch.object(wm.WorktreeManager, "merge_to_main",
                               return_value=MergeResult(success=True, conflict=False, message="ok")) as mock_merge:
                with patch.object(wm.WorktreeManager, "remove", return_value=True):
                    workflow.run("wt_branch1", wt_path, base_dir, branch="plan/x")

        # merge_to_main에 branch="plan/x" 전달 확인
        call_kwargs = mock_merge.call_args[1]
        assert call_kwargs.get("branch") == "plan/x", f"branch 전달 오류: {call_kwargs}"

    def test_workflow_run_passes_branch_to_remove(self, workflow, tmp_path):
        """TC-Right: 머지 성공 후 remove(branch='plan/x') 호출 확인"""
        wt_path = tmp_path / "wt_branch2"
        wt_path.mkdir()
        base_dir = tmp_path / ".worktrees"
        base_dir.mkdir()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            import worktree_manager as wm
            with patch.object(wm.WorktreeManager, "merge_to_main",
                               return_value=MergeResult(success=True, conflict=False, message="ok")):
                with patch.object(wm.WorktreeManager, "remove", return_value=True) as mock_remove:
                    workflow.run("wt_branch2", wt_path, base_dir, branch="plan/x")

        mock_remove.assert_called_once_with("wt_branch2", base_dir, plan_file=None, branch="plan/x")

    def test_error_merge_conflict_stores_redis(self, workflow, fake_redis, tmp_path):
        """TC-Error: 머지 충돌 → Redis merge_status='conflict' 저장"""
        wt_path = tmp_path / "wt003"
        wt_path.mkdir()
        base_dir = tmp_path / ".worktrees"
        base_dir.mkdir()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            import worktree_manager as wm
            with patch.object(wm.WorktreeManager, "merge_to_main",
                               return_value=MergeResult(success=False, conflict=True, message="conflict")):
                result = workflow.run("wt003", wt_path, base_dir)

        assert result.merged is False
        assert result.conflict is True
        status = fake_redis.get("plan-runner:runners:wt003:merge_status")
        assert status == "conflict"


# ── run_post_merge_tests() ────────────────────────────────────────────────────

class TestRunPostMergeTests:
    def test_right_passed_returns_true(self, workflow):
        """TC-Right: pytest -m http 통과 → TestResult(passed=True, exit_code=0)"""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="passed", stderr="")
            result = workflow.run_post_merge_tests()
        assert result.passed is True
        assert result.exit_code == 0

    def test_error_failed_returns_false(self, workflow):
        """TC-Error: pytest -m http 실패 → TestResult(passed=False, exit_code=1)"""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="FAILED")
            result = workflow.run_post_merge_tests()
        assert result.passed is False
        assert result.exit_code == 1
        assert "FAILED" in result.output

    def test_boundary_file_not_found(self, workflow):
        """TC-Boundary: pytest 명령 자체가 없음 → FileNotFoundError 또는 안전한 에러 반환"""
        # merge_workflow.run_post_merge_tests()는 FileNotFoundError를 catch하지 않으므로
        # 예외가 전파될 수 있음 — 이것이 현재 구현 동작
        with patch("subprocess.run", side_effect=FileNotFoundError("python not found")):
            try:
                result = workflow.run_post_merge_tests()
                # 예외를 잡는 경우: 실패 결과 반환
                assert result.passed is False
            except FileNotFoundError:
                # 예외를 잡지 않는 경우: 호출자가 처리
                pass

    def test_correct_reference_command(self, workflow, tmp_path):
        """TC-CORRECT-Reference: 실행 명령에 pytest -m http --timeout=120 포함"""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            workflow.run_post_merge_tests()
        args = mock_run.call_args[0][0]  # cmd list
        assert "-m" in args
        assert "http" in args
        assert "--timeout=120" in args


# ── merge_to_main() — plan_file 파라미터 ────────────────────────────────────

def _find_merge_branch(call_args_list):
    """call_args_list에서 'git merge <branch>' args를 찾아 branch명 반환. 없으면 None."""
    for c in call_args_list:
        args = c.args[0] if c.args else []
        if isinstance(args, list) and args[:2] == ["git", "merge"] and "--abort" not in args:
            # args[2] = branch명
            return args[2] if len(args) > 2 else None
    return None


class TestMergeToMainPlanFile:
    def test_merge_to_main_right_with_plan_file(self, tmp_path):
        """TC-Right: plan_file 전달 시 plan/{stem} 브랜치로 git merge 실행"""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0),  # git checkout main
                MagicMock(returncode=1),  # git merge-base --is-ancestor (not ancestor, proceed)
                MagicMock(returncode=0, stdout="", stderr=""),  # git merge (success)
            ]
            WorktreeManager.merge_to_main(
                "abc123", tmp_path / ".worktrees", tmp_path,
                plan_file="2026-02-27_foo-bar.md"
            )
        branch = _find_merge_branch(mock_run.call_args_list)
        assert branch is not None
        assert branch == "plan/2026-02-27_foo-bar"

    def test_merge_to_main_right_without_plan_file(self, tmp_path):
        """TC-Right: plan_file 미지정 시 runner/{id} 브랜치로 git merge 실행 (기존 동작 유지)"""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0),  # git checkout main
                MagicMock(returncode=1),  # git merge-base --is-ancestor (not ancestor, proceed)
                MagicMock(returncode=0, stdout="", stderr=""),  # git merge (success)
            ]
            WorktreeManager.merge_to_main("abc123", tmp_path / ".worktrees", tmp_path)
        branch = _find_merge_branch(mock_run.call_args_list)
        assert branch is not None
        assert branch == "runner/abc123"

    def test_merge_to_main_boundary_plan_file_empty_string(self, tmp_path):
        """TC-Boundary: plan_file='' 전달 시 falsy → runner/{id} fallback"""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0),  # git checkout main
                MagicMock(returncode=1),  # git merge-base --is-ancestor (not ancestor, proceed)
                MagicMock(returncode=0, stdout="", stderr=""),  # git merge (success)
            ]
            WorktreeManager.merge_to_main("abc123", tmp_path / ".worktrees", tmp_path, plan_file="")
        branch = _find_merge_branch(mock_run.call_args_list)
        assert branch is not None
        assert branch == "runner/abc123"

    def test_merge_to_main_error_merge_conflict(self, tmp_path):
        """TC-Error: git merge returncode=1 → MergeResult(success=False, conflict=True) + abort 호출"""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0),  # git checkout main
                MagicMock(returncode=1),  # git merge-base --is-ancestor (not ancestor, proceed)
                MagicMock(returncode=1, stdout="", stderr="CONFLICT"),  # git merge (conflict)
                MagicMock(returncode=0),  # git merge --abort
            ]
            result = WorktreeManager.merge_to_main("abc123", tmp_path / ".worktrees", tmp_path)
        assert result.success is False
        assert result.conflict is True
        abort_calls = [c for c in mock_run.call_args_list if "--abort" in str(c)]
        assert len(abort_calls) == 1

    def test_merge_to_main_error_exception(self, tmp_path):
        """TC-Error: subprocess.run Exception → MergeResult(success=False, conflict=False)"""
        with patch("subprocess.run", side_effect=OSError("git not found")):
            result = WorktreeManager.merge_to_main("abc123", tmp_path / ".worktrees", tmp_path)
        assert result.success is False
        assert result.conflict is False
        assert "git not found" in result.message


# ── MergeWorkflow.run() — plan_file 전달 ─────────────────────────────────────

class TestMergeWorkflowRunPlanFile:
    def test_workflow_run_right_passes_plan_file_to_merge(self, workflow, tmp_path):
        """TC-Right: wf.run(plan_file=X) → merge_to_main(plan_file=X) 전달 검증"""
        wt_path = tmp_path / "wt_pf1"
        wt_path.mkdir()
        base_dir = tmp_path / ".worktrees"
        base_dir.mkdir()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            import worktree_manager as wm
            with patch.object(wm.WorktreeManager, "merge_to_main",
                               return_value=MergeResult(success=True, conflict=False, message="ok")) as mock_merge, \
                 patch.object(wm.WorktreeManager, "remove", return_value=True):
                workflow.run("wt_pf1", wt_path, base_dir, plan_file="2026-02-27_test.md")

        mock_merge.assert_called_once()
        _, kwargs = mock_merge.call_args
        assert kwargs.get("plan_file") == "2026-02-27_test.md"

    def test_workflow_run_right_passes_plan_file_to_remove(self, workflow, tmp_path):
        """TC-Right: 성공 경로에서 remove(plan_file=X) 호출 검증"""
        wt_path = tmp_path / "wt_pf2"
        wt_path.mkdir()
        base_dir = tmp_path / ".worktrees"
        base_dir.mkdir()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            import worktree_manager as wm
            with patch.object(wm.WorktreeManager, "merge_to_main",
                               return_value=MergeResult(success=True, conflict=False, message="ok")), \
                 patch.object(wm.WorktreeManager, "remove", return_value=True) as mock_remove:
                workflow.run("wt_pf2", wt_path, base_dir, plan_file="2026-02-27_test.md")

        mock_remove.assert_called_once()
        _, kwargs = mock_remove.call_args
        assert kwargs.get("plan_file") == "2026-02-27_test.md"

    def test_workflow_run_boundary_no_plan_file(self, workflow, tmp_path):
        """TC-Boundary: plan_file 미지정 시 merge_to_main/remove 에 plan_file=None 전달"""
        wt_path = tmp_path / "wt_pf3"
        wt_path.mkdir()
        base_dir = tmp_path / ".worktrees"
        base_dir.mkdir()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            import worktree_manager as wm
            with patch.object(wm.WorktreeManager, "merge_to_main",
                               return_value=MergeResult(success=True, conflict=False, message="ok")) as mock_merge, \
                 patch.object(wm.WorktreeManager, "remove", return_value=True) as mock_remove:
                workflow.run("wt_pf3", wt_path, base_dir)

        _, merge_kwargs = mock_merge.call_args
        assert merge_kwargs.get("plan_file") is None
        _, remove_kwargs = mock_remove.call_args
        assert remove_kwargs.get("plan_file") is None


# ── _publish_log() — 파일 로깅 ───────────────────────────────────────────────

class TestPublishLogFileLogging:
    def test_publish_log_right_writes_to_logger(self, workflow):
        """TC-Right: _publish_log() 호출 시 logger.info()도 호출됨"""
        import merge_workflow as mw
        with patch.object(mw.logger, "info") as mock_info:
            workflow._publish_log("r1", "MERGE", "test message")
        mock_info.assert_called_once_with("[MERGE][MERGE] test message")

    def test_publish_log_error_redis_down_still_logs_file(self, tmp_path):
        """TC-Error: Redis publish 실패해도 logger.info()는 호출됨"""
        broken_redis = MagicMock()
        broken_redis.publish.side_effect = Exception("Redis down")
        wf = MergeWorkflow(project_root=tmp_path, redis_client=broken_redis)
        import merge_workflow as mw
        with patch.object(mw.logger, "info") as mock_info:
            wf._publish_log("r1", "ERROR", "failure msg")
        mock_info.assert_called_once_with("[MERGE][ERROR] failure msg")


# ── E2E 테스트 ───────────────────────────────────────────────────────────────

class TestMergeWorkflowE2E:
    def test_e2e_merge_workflow_with_plan_file(self, workflow, fake_redis, tmp_path):
        """TC-E2E: plan_file 포함 전체 흐름 — 커밋 → merge_to_main(plan_file) → remove(plan_file)"""
        wt_path = tmp_path / "2026-02-27_my-feature"
        wt_path.mkdir()
        base_dir = tmp_path / ".worktrees"
        base_dir.mkdir()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            import worktree_manager as wm
            with patch.object(wm.WorktreeManager, "merge_to_main",
                               return_value=MergeResult(success=True, conflict=False, message="ok")) as mock_merge, \
                 patch.object(wm.WorktreeManager, "remove", return_value=True) as mock_remove:
                result = workflow.run(
                    "abc123", wt_path, base_dir,
                    plan_file="2026-02-27_my-feature.md"
                )

        assert result.merged is True
        assert result.tests_passed is True
        # merge_to_main에 올바른 plan_file 전달
        _, merge_kw = mock_merge.call_args
        assert merge_kw.get("plan_file") == "2026-02-27_my-feature.md"
        # remove에도 올바른 plan_file 전달
        _, remove_kw = mock_remove.call_args
        assert remove_kw.get("plan_file") == "2026-02-27_my-feature.md"
        # Redis merge_status = "merged"
        assert fake_redis.get("plan-runner:runners:abc123:merge_status") == "merged"

    def test_e2e_merge_workflow_conflict_then_retry(self, workflow, fake_redis, tmp_path):
        """TC-E2E: 충돌 → merge_status=conflict → retry 시 plan_file 재전달"""
        wt_path = tmp_path / "2026-02-27_conflict-test"
        wt_path.mkdir()
        base_dir = tmp_path / ".worktrees"
        base_dir.mkdir()

        # 1차: 충돌
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            import worktree_manager as wm
            with patch.object(wm.WorktreeManager, "merge_to_main",
                               return_value=MergeResult(success=False, conflict=True, message="CONFLICT")):
                result1 = workflow.run(
                    "ccc123", wt_path, base_dir,
                    plan_file="2026-02-27_conflict-test.md"
                )
        assert result1.conflict is True
        assert fake_redis.get("plan-runner:runners:ccc123:merge_status") == "conflict"

        # 2차: retry (plan_file 재전달)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            with patch.object(wm.WorktreeManager, "merge_to_main",
                               return_value=MergeResult(success=True, conflict=False, message="ok")) as mock_merge2, \
                 patch.object(wm.WorktreeManager, "remove", return_value=True):
                result2 = workflow.run(
                    "ccc123", wt_path, base_dir,
                    plan_file="2026-02-27_conflict-test.md"
                )
        assert result2.merged is True
        _, kw = mock_merge2.call_args
        assert kw.get("plan_file") == "2026-02-27_conflict-test.md"
