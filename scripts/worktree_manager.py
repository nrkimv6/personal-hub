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


def parse_plan_filename(plan_file: str) -> tuple:
    """plan 파일명에서 날짜와 slug 분리

    '2026-02-27_activity-hub-fix.md' → ('2026-02-27', 'activity-hub-fix')
    날짜 접두사가 없으면 ('', stem) 반환
    """
    stem = Path(plan_file).stem
    # YYYY-MM-DD_ 패턴 감지
    import re
    m = re.match(r'^(\d{4}-\d{2}-\d{2})_(.+)$', stem)
    if m:
        return m.group(1), m.group(2)
    return '', stem


def branch_from_plan(plan_file: str) -> str:
    """plan 파일명에서 브랜치명 생성

    '2026-02-27_activity-hub-fix.md' → 'plan/2026-02-27_activity-hub-fix'
    """
    stem = Path(plan_file).stem
    return f"plan/{stem}"


@dataclass
class MergeResult:
    success: bool
    conflict: bool
    message: str


class WorktreeManager:
    @staticmethod
    def create(runner_id: str, base_dir: Path, plan_file: Optional[str] = None) -> tuple:
        """git worktree add 실행 후 (worktree_path, branch) 반환

        plan_file 지정 시: branch='plan/{stem}', path=base_dir/{stem}
        미지정 시: branch='runner/{runner_id}', path=base_dir/{runner_id}
        """
        if not runner_id:
            raise WorktreeError("runner_id cannot be empty")
        if plan_file:
            stem = Path(plan_file).stem
            worktree_path = base_dir / stem
            branch = f"plan/{stem}"
        else:
            worktree_path = base_dir / runner_id
            branch = f"runner/{runner_id}"
        try:
            base_dir.mkdir(parents=True, exist_ok=True)
            result = subprocess.run(
                ["git", "worktree", "add", str(worktree_path), "-b", branch],
                capture_output=True, text=True, cwd=str(base_dir.parent)
            )
            if result.returncode != 0:
                if "already exists" in result.stderr:
                    # 워크트리 디렉토리가 실제로 존재하면 재사용 (커밋 보존)
                    if worktree_path.is_dir():
                        logger.info(f"[WorktreeManager] 기존 worktree 재사용: {branch}")
                        return worktree_path, branch
                    # 디렉토리 없음 + 브랜치만 남은 경우: prune 후 재생성
                    subprocess.run(
                        ["git", "worktree", "prune"],
                        capture_output=True, cwd=str(base_dir.parent),
                    )
                    subprocess.run(
                        ["git", "branch", "-D", branch],
                        capture_output=True, cwd=str(base_dir.parent),
                    )
                    result = subprocess.run(
                        ["git", "worktree", "add", str(worktree_path), "-b", branch],
                        capture_output=True, text=True, cwd=str(base_dir.parent),
                    )
                    if result.returncode != 0:
                        raise WorktreeError(f"git worktree add 실패 (재시도 후): {result.stderr}")
                    logger.warning(f"[WorktreeManager] dangling 브랜치 정리 후 재생성: {branch}")
                else:
                    raise WorktreeError(f"git worktree add 실패: {result.stderr}")
            logger.info(f"[WorktreeManager] 생성: {worktree_path} (브랜치: {branch})")
            return worktree_path, branch
        except WorktreeError:
            raise
        except Exception as e:
            raise WorktreeError(f"worktree 생성 중 오류: {e}")

    @staticmethod
    def remove(runner_id: str, base_dir: Path, plan_file: Optional[str] = None, branch: Optional[str] = None) -> bool:
        """git worktree remove + git branch -D

        우선순위: branch 파라미터 > plan_file > runner_id 기반
        """
        if branch:
            # branch 파라미터가 있으면 그대로 사용, worktree_path는 base_dir/{branch_slug}로 추론
            branch_slug = branch.replace("/", "_")
            worktree_path = base_dir / branch_slug
        elif plan_file:
            stem = Path(plan_file).stem
            worktree_path = base_dir / stem
            branch = f"plan/{stem}"
        else:
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
    def merge_to_main(runner_id: str, base_dir: Path, project_root: Path, plan_file: Optional[str] = None, branch: Optional[str] = None) -> MergeResult:
        """worktree 변경사항을 main 브랜치에 머지

        우선순위: branch 파라미터 > plan_file > runner_id 기반
        conflict 시 항상 abort 후 MergeResult(conflict=True) 반환. 자동 해결은 호출자 책임.
        """
        if branch:
            pass  # 그대로 사용
        elif plan_file:
            stem = Path(plan_file).stem
            branch = f"plan/{stem}"
        else:
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
                # 충돌 abort — 자동 해결은 호출자(_do_inline_merge)가 처리
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
                    current = {"path": line[9:], "branch": None, "runner_id": None, "plan_slug": None}
                elif line.startswith("branch "):
                    branch = line[7:].replace("refs/heads/", "")
                    current["branch"] = branch
                    if branch.startswith("runner/"):
                        current["runner_id"] = branch[7:]
                    elif branch.startswith("plan/"):
                        current["plan_slug"] = branch[5:]
            if current:
                worktrees.append(current)
            return worktrees
        except Exception as e:
            logger.error(f"[WorktreeManager] list 실패: {e}")
            return []
