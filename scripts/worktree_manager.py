"""
WorktreeManager — git worktree 생명주기 관리 유틸리티

각 plan-runner 인스턴스를 격리된 git worktree에서 실행하기 위한 헬퍼 클래스.
"""
import shutil
import subprocess
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


class WorktreeError(Exception):
    pass


def ensure_main_branch(project_root: Path) -> None:
    """메인 레포가 main 브랜치인지 확인하고, 아니면 main으로 복귀.

    main이면 즉시 return (no-op).
    uncommitted changes가 있어 checkout 불가능하면 WorktreeError 발생.
    """
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True, encoding="utf-8", cwd=str(project_root)
    )
    branch = result.stdout.strip()
    if branch == "main":
        return
    logger.warning(f"[WorktreeManager] 메인 레포가 {branch}에 있음, main으로 복귀")
    checkout = subprocess.run(
        ["git", "checkout", "main"],
        capture_output=True, text=True, encoding="utf-8", cwd=str(project_root)
    )
    if checkout.returncode != 0:
        raise WorktreeError(f"메인 레포를 main으로 복귀 실패 (현재: {branch}): {checkout.stderr}")


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
    already_merged: bool = False
    stash_pop_conflict: bool = False
    overwritten: bool = False
    exception: str = ""


class WorktreeManager:
    @staticmethod
    def validate(worktree_path: Path) -> bool:
        """worktree가 실제로 유효한지 검증.

        유효 조건:
        1. 디렉토리 존재
        2. .git 파일(worktree 링크) 존재
        3. git rev-parse --git-dir 성공

        깨진 worktree(디렉토리만 있고 .git 없음)는 False 반환.
        """
        if not worktree_path.is_dir():
            return False
        if not (worktree_path / ".git").exists():
            return False
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            capture_output=True, cwd=str(worktree_path)
        )
        return result.returncode == 0

    @staticmethod
    def _apply_sparse_checkout(worktree_path: Path) -> None:
        """worktree에 sparse-checkout 적용: docs/plan/, docs/archive/ 제외"""
        # sparse-checkout 활성화 (이미 활성이어도 멱등)
        subprocess.run(
            ["git", "sparse-checkout", "init", "--no-cone"],
            cwd=str(worktree_path), capture_output=True
        )
        # 패턴 설정: 전체 포함, docs/plan/ + docs/archive/ 제외
        subprocess.run(
            ["git", "sparse-checkout", "set", "--no-cone",
             "/*", "!/docs/plan/", "!/docs/archive/"],
            cwd=str(worktree_path), capture_output=True
        )
        logger.info(f"[WorktreeManager] sparse-checkout 적용: {worktree_path} (docs/plan, docs/archive 제외)")

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
            ensure_main_branch(base_dir.parent)
            result = subprocess.run(
                ["git", "worktree", "add", str(worktree_path), "-b", branch],
                capture_output=True, text=True, encoding="utf-8", cwd=str(base_dir.parent)
            )
            if result.returncode != 0:
                if "already exists" in result.stderr:
                    # 워크트리 디렉토리가 실제로 존재하면 재사용 (커밋 보존)
                    if worktree_path.is_dir():
                        if WorktreeManager.validate(worktree_path):
                            logger.info(f"[WorktreeManager] 기존 worktree 재사용: {branch}")
                            WorktreeManager._apply_sparse_checkout(worktree_path)
                            return worktree_path, branch
                        # .git 없는 깨진 worktree → 정리 후 재생성
                        logger.warning(f"[WorktreeManager] 깨진 worktree 정리 후 재생성: {branch} ({worktree_path})")
                        shutil.rmtree(str(worktree_path))
                        subprocess.run(
                            ["git", "worktree", "prune"],
                            capture_output=True, cwd=str(base_dir.parent),
                        )
                    # 디렉토리 없음 + 브랜치만 남은 경우: 미머지 커밋 확인 후 분기
                    subprocess.run(
                        ["git", "worktree", "prune"],
                        capture_output=True, cwd=str(base_dir.parent),
                    )
                    unmerged = subprocess.run(
                        ["git", "log", f"main..{branch}", "--oneline"],
                        capture_output=True, text=True, encoding="utf-8", cwd=str(base_dir.parent),
                    )
                    has_unmerged = unmerged.returncode == 0 and unmerged.stdout.strip()
                    if has_unmerged:
                        # 미머지 커밋 있음: branch -D 스킵, 기존 브랜치로 워크트리 연결
                        result = subprocess.run(
                            ["git", "worktree", "add", str(worktree_path), branch],
                            capture_output=True, text=True, encoding="utf-8", cwd=str(base_dir.parent),
                        )
                        if result.returncode != 0:
                            raise WorktreeError(f"git worktree add 실패 (기존 브랜치 재사용 시도): {result.stderr}")
                        logger.warning(f"[WorktreeManager] 미머지 커밋 보존 — 기존 브랜치 재사용: {branch}")
                    else:
                        # 미머지 커밋 없음(이미 머지됨 or 빈 브랜치): 기존 동작 유지
                        subprocess.run(
                            ["git", "branch", "-D", branch],
                            capture_output=True, cwd=str(base_dir.parent),
                        )
                        result = subprocess.run(
                            ["git", "worktree", "add", str(worktree_path), "-b", branch],
                            capture_output=True, text=True, encoding="utf-8", cwd=str(base_dir.parent),
                        )
                        if result.returncode != 0:
                            raise WorktreeError(f"git worktree add 실패 (재시도 후): {result.stderr}")
                        logger.warning(f"[WorktreeManager] dangling 브랜치 정리 후 재생성: {branch}")
                else:
                    raise WorktreeError(f"git worktree add 실패: {result.stderr}")
            WorktreeManager._apply_sparse_checkout(worktree_path)
            if not WorktreeManager.validate(worktree_path):
                raise WorktreeError(f"worktree 생성 후 검증 실패 (.git 누락): {worktree_path}")
            logger.info(f"[WorktreeManager] 생성: {worktree_path} (브랜치: {branch})")
            return worktree_path, branch
        except WorktreeError:
            raise
        except Exception as e:
            raise WorktreeError(f"worktree 생성 중 오류: {e}")

    @staticmethod
    def remove(runner_id: str, base_dir: Path, plan_file: Optional[str] = None, branch: Optional[str] = None, delete_branch: bool = True) -> bool:
        """git worktree remove + (선택적) git branch -D

        우선순위: branch 파라미터 > plan_file > runner_id 기반
        delete_branch=False: worktree 디렉토리만 제거, branch는 보존 (merge 전 사전 제거 시 사용)
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
                capture_output=True, text=True, encoding="utf-8", cwd=str(base_dir.parent)
            )
            if result.returncode != 0 and "is not a working tree" not in result.stderr:
                logger.warning(f"[WorktreeManager] worktree 삭제 경고: {result.stderr}")
            if delete_branch:
                subprocess.run(
                    ["git", "branch", "-D", branch],
                    capture_output=True, text=True, encoding="utf-8", cwd=str(base_dir.parent)
                )
            logger.info(f"[WorktreeManager] 제거: {runner_id} (delete_branch={delete_branch})")
            return True
        except Exception as e:
            logger.error(f"[WorktreeManager] 제거 실패: {e}")
            return True  # 멱등 처리

    @staticmethod
    def merge_to_main(runner_id: str, base_dir: Path, project_root: Path, plan_file: Optional[str] = None, branch: Optional[str] = None) -> MergeResult:
        """worktree 변경사항을 main 브랜치에 머지

        우선순위: branch 파라미터 > plan_file > runner_id 기반
        dirty working tree는 merge 전 stash, 결과에 따라 pop.
        예외 발생 시에도 finally에서 main 브랜치 복귀 보장.
        """
        if branch:
            pass  # 그대로 사용
        elif plan_file:
            stem = Path(plan_file).stem
            branch = f"plan/{stem}"
        else:
            branch = f"runner/{runner_id}"
        stashed = False
        try:
            # main 체크아웃
            ensure_main_branch(project_root)
            # is-ancestor 사전 체크 — 이미 머지된 브랜치면 skip
            ancestor_check = subprocess.run(
                ["git", "merge-base", "--is-ancestor", branch, "HEAD"],
                capture_output=True, cwd=str(project_root)
            )
            if ancestor_check.returncode == 0:
                logger.info(f"[WorktreeManager] 이미 머지됨 — skip: {branch}")
                return MergeResult(success=True, conflict=False, already_merged=True, message="이미 머지됨 — skip")
            # pre-merge stash: dirty working tree 감지
            status_r = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, encoding="utf-8", cwd=str(project_root))
            if status_r.stdout.strip():
                stash_r = subprocess.run(
                    ["git", "stash", "push", "--include-untracked"],
                    capture_output=True, text=True, encoding="utf-8", cwd=str(project_root)
                )
                stashed = stash_r.returncode == 0 and "No local changes to save" not in stash_r.stdout
                logger.info(f"[WorktreeManager] pre-merge stash: rc={stash_r.returncode}, stashed={stashed}")
            result = subprocess.run(
                ["git", "merge", branch, "--no-ff", "-m", f"merge: {branch}"],
                capture_output=True, text=True, encoding="utf-8", cwd=str(project_root)
            )
            if result.returncode == 0:
                # 머지 성공 → stash pop (있으면)
                stash_pop_conflict = False
                if stashed:
                    pop_r = subprocess.run(["git", "stash", "pop"], capture_output=True, text=True, encoding="utf-8", cwd=str(project_root))
                    if pop_r.returncode != 0:
                        stash_pop_conflict = True
                        logger.warning(f"[WorktreeManager] stash pop 충돌 — drop 실행: {pop_r.stderr[:200]}")
                        subprocess.run(["git", "stash", "drop"], capture_output=True, cwd=str(project_root))
                    stashed = False
                logger.info(f"[WorktreeManager] 머지 성공: {branch}")
                return MergeResult(success=True, conflict=False, stash_pop_conflict=stash_pop_conflict, message="머지 성공")
            else:
                conflict = "CONFLICT" in result.stdout or "CONFLICT" in result.stderr
                overwritten = "would be overwritten" in result.stderr or "would be overwritten" in result.stdout
                # CONFLICT 줄만 추출하여 message에 포함 (resolve에서 컨텍스트로 활용)
                conflict_lines = [l.strip() for l in result.stdout.splitlines() if l.strip().startswith("CONFLICT")]
                detail = "\n".join(conflict_lines) if conflict_lines else (result.stderr.strip() + "\n" + result.stdout.strip()).strip()[:500]
                # 항상 abort 후 stash pop
                subprocess.run(["git", "merge", "--abort"], capture_output=True, cwd=str(project_root))
                if stashed:
                    pop_r = subprocess.run(["git", "stash", "pop"], capture_output=True, text=True, encoding="utf-8", cwd=str(project_root))
                    if pop_r.returncode != 0:
                        logger.warning(f"[WorktreeManager] abort 후 stash pop 실패 — drop: {pop_r.stderr[:200]}")
                        subprocess.run(["git", "stash", "drop"], capture_output=True, cwd=str(project_root))
                    stashed = False
                return MergeResult(success=False, conflict=conflict, overwritten=overwritten, message=detail)
        except Exception as e:
            return MergeResult(success=False, conflict=False, exception=str(e), message=str(e))
        finally:
            # 예외 발생 시에도 main 복귀 보장 (stash pop은 위에서 이미 처리)
            # 예외는 억제 — 이미 except에서 MergeResult를 반환했거나 상위로 전파 중
            try:
                subprocess.run(["git", "checkout", "main"], capture_output=True, cwd=str(project_root))
            except Exception:
                pass

    @staticmethod
    def list_worktrees() -> list:
        """git worktree list --porcelain 파싱"""
        try:
            result = subprocess.run(
                ["git", "worktree", "list", "--porcelain"],
                capture_output=True, text=True, encoding="utf-8"
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
