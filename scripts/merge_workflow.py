"""
MergeWorkflow — plan-runner worktree 완료 후 머지 워크플로우

실행 순서:
  1. worktree에서 변경사항 커밋
  2. main 브랜치에 머지
  3. HTTP 테스트 실행
  4. 성공 시 worktree 정리
"""
import subprocess
import logging
from pathlib import Path
from dataclasses import dataclass

logger = logging.getLogger(__name__)

RUNNER_KEY_PREFIX = "plan-runner:runners"


@dataclass
class TestResult:
    passed: bool
    output: str
    exit_code: int


@dataclass
class WorkflowResult:
    merged: bool
    tests_passed: bool
    conflict: bool
    message: str


class MergeWorkflow:
    def __init__(self, project_root: Path, redis_client, python_path: str = None):
        self.project_root = project_root
        self.redis_client = redis_client
        self.python_path = python_path or "python"

    def run(self, runner_id: str, worktree_path: Path, base_dir: Path) -> WorkflowResult:
        from worktree_manager import WorktreeManager

        # 1. 변경사항 커밋
        subprocess.run(["git", "add", "-A"], cwd=str(worktree_path), capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", f"feat: runner/{runner_id} 구현 완료"],
            cwd=str(worktree_path), capture_output=True
        )

        # 2. 머지
        merge_result = WorktreeManager.merge_to_main(runner_id, base_dir, self.project_root)
        if not merge_result.success:
            if self.redis_client:
                try:
                    self.redis_client.set(
                        f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "conflict"
                    )
                except Exception:
                    pass
            return WorkflowResult(
                merged=False,
                tests_passed=False,
                conflict=merge_result.conflict,
                message=merge_result.message
            )

        # 3. HTTP 테스트
        test_result = self.run_post_merge_tests()
        if not test_result.passed:
            if self.redis_client:
                try:
                    self.redis_client.set(
                        f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "test_failed"
                    )
                except Exception:
                    pass
            return WorkflowResult(
                merged=True,
                tests_passed=False,
                conflict=False,
                message=test_result.output[:500]
            )

        # 4. worktree 정리
        WorktreeManager.remove(runner_id, base_dir)
        if self.redis_client:
            try:
                self.redis_client.set(
                    f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "merged"
                )
            except Exception:
                pass

        return WorkflowResult(merged=True, tests_passed=True, conflict=False, message="성공")

    def run_post_merge_tests(self) -> TestResult:
        result = subprocess.run(
            [self.python_path, "-m", "pytest", str(self.project_root / "tests"), "-m", "http", "-v", "--timeout=120"],
            capture_output=True, text=True, cwd=str(self.project_root)
        )
        return TestResult(
            passed=result.returncode == 0,
            output=result.stdout + result.stderr,
            exit_code=result.returncode
        )
