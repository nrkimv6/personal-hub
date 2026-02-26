"""MergeWorkflow 유닛 테스트 — RIGHT-BICEP + CORRECT"""
import subprocess
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, call
import fakeredis

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from merge_workflow import MergeWorkflow, WorkflowResult, TestResult
from worktree_manager import MergeResult


@pytest.fixture
def fake_redis():
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def workflow(fake_redis, tmp_path):
    return MergeWorkflow(project_root=tmp_path, redis_client=fake_redis, python_path="python")


# ── run() ────────────────────────────────────────────────────────────────────

class TestMergeWorkflowRun:
    def test_right_success_calls_merge_and_tests(self, workflow, tmp_path):
        """TC-Right: runner 성공 → 머지 성공 → 테스트 실행 → WorkflowResult(merged=True, tests_passed=True)"""
        wt_path = tmp_path / "wt001"
        wt_path.mkdir()
        base_dir = tmp_path / ".worktrees"
        base_dir.mkdir()

        with patch("subprocess.run") as mock_run, \
             patch.object(workflow, "run_post_merge_tests") as mock_tests:
            mock_tests.return_value = TestResult(passed=True, output="", exit_code=0)
            mock_run.return_value = MagicMock(returncode=0)
            import worktree_manager as wm
            with patch.object(wm.WorktreeManager, "merge_to_main",
                               return_value=MergeResult(success=True, conflict=False, message="ok")):
                result = workflow.run("wt001", wt_path, base_dir)

        assert result.merged is True
        assert result.tests_passed is True
        mock_tests.assert_called_once()

    def test_right_success_calls_remove(self, workflow, tmp_path):
        """TC-Right: 머지 성공 + 테스트 통과 → WorktreeManager.remove() 호출"""
        wt_path = tmp_path / "wt002"
        wt_path.mkdir()
        base_dir = tmp_path / ".worktrees"
        base_dir.mkdir()

        with patch("subprocess.run") as mock_run, \
             patch.object(workflow, "run_post_merge_tests") as mock_tests:
            mock_tests.return_value = TestResult(passed=True, output="", exit_code=0)
            mock_run.return_value = MagicMock(returncode=0)

            # WorktreeManager는 scripts/ sys.path로 import됨
            import worktree_manager as wm
            with patch.object(wm.WorktreeManager, "merge_to_main",
                               return_value=MergeResult(success=True, conflict=False, message="ok")):
                with patch.object(wm.WorktreeManager, "remove", return_value=True) as mock_remove:
                    workflow.run("wt002", wt_path, base_dir)

        mock_remove.assert_called_once_with("wt002", base_dir)

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

    def test_error_tests_fail_returns_correct_result(self, workflow, tmp_path):
        """TC-Error: HTTP 테스트 실패 → WorkflowResult(merged=True, tests_passed=False)"""
        wt_path = tmp_path / "wt004"
        wt_path.mkdir()
        base_dir = tmp_path / ".worktrees"
        base_dir.mkdir()

        with patch("subprocess.run") as mock_run, \
             patch.object(workflow, "run_post_merge_tests") as mock_tests:
            mock_tests.return_value = TestResult(passed=False, output="FAILED", exit_code=1)
            mock_run.return_value = MagicMock(returncode=0)
            import worktree_manager as wm
            with patch.object(wm.WorktreeManager, "merge_to_main",
                               return_value=MergeResult(success=True, conflict=False, message="ok")):
                result = workflow.run("wt004", wt_path, base_dir)

        assert result.merged is True
        assert result.tests_passed is False


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
