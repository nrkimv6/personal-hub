"""
WorktreeManager — git worktree 생명주기 관리 유틸리티

각 plan-runner 인스턴스를 격리된 git worktree에서 실행하기 위한 헬퍼 클래스.
"""
import subprocess
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


class WorktreeError(Exception):
    pass


@dataclass
class MergeResult:
    success: bool
    conflict: bool
    message: str


class WorktreeManager:
    @staticmethod
    def create(runner_id: str, base_dir: Path) -> Path:
        """git worktree add {base_dir}/{runner_id} -b runner/{runner_id}"""
        if not runner_id:
            raise WorktreeError("runner_id cannot be empty")
        worktree_path = base_dir / runner_id
        branch = f"runner/{runner_id}"
        try:
            base_dir.mkdir(parents=True, exist_ok=True)
            result = subprocess.run(
                ["git", "worktree", "add", str(worktree_path), "-b", branch],
                capture_output=True, text=True, cwd=str(base_dir.parent)
            )
            if result.returncode != 0:
                raise WorktreeError(f"git worktree add 실패: {result.stderr}")
            logger.info(f"[WorktreeManager] 생성: {worktree_path} (브랜치: {branch})")
            return worktree_path
        except WorktreeError:
            raise
        except Exception as e:
            raise WorktreeError(f"worktree 생성 중 오류: {e}")

    @staticmethod
    def remove(runner_id: str, base_dir: Path) -> bool:
        """git worktree remove + git branch -D"""
        worktree_path = base_dir / runner_id
        branch = f"runner/{runner_id}"
        try:
            result = subprocess.run(
                ["git", "worktree", "remove", str(worktree_path), "--force"],
                capture_output=True, text=True, cwd=str(base_dir.parent)
            )
            if result.returncode != 0 and "is not a working tree" not in result.stderr:
                logger.warning(f"[WorktreeManager] worktree 삭제 경고: {result.stderr}")
            subprocess.run(
                ["git", "branch", "-D", branch],
                capture_output=True, text=True, cwd=str(base_dir.parent)
            )
            logger.info(f"[WorktreeManager] 제거: {runner_id}")
            return True
        except Exception as e:
            logger.error(f"[WorktreeManager] 제거 실패: {e}")
            return True  # 멱등 처리

    @staticmethod
    def merge_to_main(runner_id: str, base_dir: Path, project_root: Path) -> MergeResult:
        """worktree 변경사항을 main 브랜치에 머지"""
        branch = f"runner/{runner_id}"
        try:
            # main 체크아웃
            subprocess.run(["git", "checkout", "main"], capture_output=True, cwd=str(project_root))
            result = subprocess.run(
                ["git", "merge", branch, "--no-ff", "-m", f"merge: {branch}"],
                capture_output=True, text=True, cwd=str(project_root)
            )
            if result.returncode == 0:
                logger.info(f"[WorktreeManager] 머지 성공: {branch}")
                return MergeResult(success=True, conflict=False, message="머지 성공")
            else:
                # 충돌 abort
                subprocess.run(["git", "merge", "--abort"], capture_output=True, cwd=str(project_root))
                return MergeResult(success=False, conflict=True, message=result.stderr)
        except Exception as e:
            return MergeResult(success=False, conflict=False, message=str(e))

    @staticmethod
    def list_worktrees() -> list:
        """git worktree list --porcelain 파싱"""
        try:
            result = subprocess.run(
                ["git", "worktree", "list", "--porcelain"],
                capture_output=True, text=True
            )
            worktrees = []
            current: dict = {}
            for line in result.stdout.splitlines():
                if line.startswith("worktree "):
                    if current:
                        worktrees.append(current)
                    current = {"path": line[9:], "branch": None, "runner_id": None}
                elif line.startswith("branch "):
                    branch = line[7:].replace("refs/heads/", "")
                    current["branch"] = branch
                    if branch.startswith("runner/"):
                        current["runner_id"] = branch[7:]
            if current:
                worktrees.append(current)
            return worktrees
        except Exception as e:
            logger.error(f"[WorktreeManager] list 실패: {e}")
            return []
