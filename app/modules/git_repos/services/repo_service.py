"""GitRepo CRUD + 상태 관리 서비스."""
import asyncio
import os
from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from app.modules.git_repos.models import GitRepo, GitOperationLog
from app.modules.git_repos.schemas import RepoStatus, OperationResult
from app.modules.git_repos.services.git_command import GitCommandService


class GitRepoService:
    """레포지토리 CRUD 및 상태 관리."""

    def __init__(self):
        self._git = GitCommandService()

    # ─────────────────────────────────────────────
    # CRUD
    # ─────────────────────────────────────────────

    def list_repos(self, db: Session) -> List[GitRepo]:
        return (
            db.query(GitRepo)
            .order_by(GitRepo.sort_order, GitRepo.alias, GitRepo.path)
            .all()
        )

    def get_repo(self, db: Session, repo_id: int) -> Optional[GitRepo]:
        return db.query(GitRepo).filter(GitRepo.id == repo_id).first()

    async def create_repo(self, db: Session, path: str, alias: Optional[str] = None) -> GitRepo:
        """경로 유효성(.git 존재) 확인 후 등록."""
        # 정규화
        path = os.path.normpath(path)

        # .git 디렉토리 확인
        git_dir = os.path.join(path, ".git")
        if not os.path.exists(git_dir):
            raise ValueError(f"유효한 git 레포지토리가 아닙니다: {path}")

        # 중복 확인
        existing = db.query(GitRepo).filter(GitRepo.path == path).first()
        if existing:
            raise ValueError(f"이미 등록된 레포지토리입니다: {path}")

        repo = GitRepo(path=path, alias=alias or os.path.basename(path))
        db.add(repo)
        db.commit()
        db.refresh(repo)

        # 초기 상태 조회
        try:
            await self.refresh_status(db, repo)
        except Exception:
            pass

        return repo

    def update_repo(
        self,
        db: Session,
        repo_id: int,
        alias: Optional[str] = None,
        is_active: Optional[bool] = None,
        sort_order: Optional[int] = None,
    ) -> Optional[GitRepo]:
        repo = self.get_repo(db, repo_id)
        if not repo:
            return None
        if alias is not None:
            repo.alias = alias
        if is_active is not None:
            repo.is_active = is_active
        if sort_order is not None:
            repo.sort_order = sort_order
        repo.updated_at = datetime.now()
        db.commit()
        db.refresh(repo)
        return repo

    def delete_repo(self, db: Session, repo_id: int) -> bool:
        repo = self.get_repo(db, repo_id)
        if not repo:
            return False
        db.delete(repo)
        db.commit()
        return True

    async def discover_repos(self, base_path: str) -> List[str]:
        """base_path 하위 1단계에서 .git 포함 폴더 목록 반환."""
        base_path = os.path.normpath(base_path)
        if not os.path.isdir(base_path):
            raise ValueError(f"디렉토리가 존재하지 않습니다: {base_path}")

        found = []
        try:
            for name in os.listdir(base_path):
                candidate = os.path.join(base_path, name)
                if os.path.isdir(candidate) and os.path.isdir(os.path.join(candidate, ".git")):
                    found.append(candidate)
        except PermissionError as e:
            raise ValueError(f"디렉토리 접근 권한이 없습니다: {e}")

        return sorted(found)

    # ─────────────────────────────────────────────
    # 상태 갱신
    # ─────────────────────────────────────────────

    async def get_detailed_status(self, path: str) -> RepoStatus:
        return await self._git.get_status(path)

    async def refresh_status(self, db: Session, repo: GitRepo) -> GitRepo:
        """git status 실행 후 DB 갱신."""
        try:
            status = await self._git.get_status(repo.path)
            repo.last_status = status.status
            repo.last_branch = status.branch
            repo.last_ahead = status.ahead
            repo.last_behind = status.behind
        except Exception:
            repo.last_status = "unknown"

        repo.last_checked_at = datetime.now()
        repo.updated_at = datetime.now()
        db.commit()
        db.refresh(repo)
        return repo

    async def refresh_all(self, db: Session) -> List[GitRepo]:
        """전체 활성 레포지토리 상태 병렬 갱신."""
        repos = db.query(GitRepo).filter(GitRepo.is_active == True).all()
        if not repos:
            return []

        async def _safe_refresh(repo: GitRepo):
            try:
                await self.refresh_status(db, repo)
            except Exception:
                pass

        await asyncio.gather(*[_safe_refresh(r) for r in repos])
        return repos

    # ─────────────────────────────────────────────
    # 작업 실행 (래핑)
    # ─────────────────────────────────────────────

    async def commit_repo(
        self, db: Session, repo: GitRepo, message: str, stage_all: bool = False
    ) -> OperationResult:
        if stage_all:
            ok, out, err = await self._git.stage_all(repo.path)
            if not ok:
                self.log_operation(db, repo.id, "commit", "failure", message, err)
                return OperationResult(success=False, stderr=err, message="스테이징 실패")

        ok, stdout, stderr = await self._git.commit(repo.path, message)
        self.log_operation(db, repo.id, "commit", "success" if ok else "failure", message, stderr or stdout)
        if ok:
            await self.refresh_status(db, repo)
        return OperationResult(success=ok, stdout=stdout, stderr=stderr)

    async def push_repo(self, db: Session, repo: GitRepo) -> OperationResult:
        ok, stdout, stderr = await self._git.push(repo.path)
        self.log_operation(db, repo.id, "push", "success" if ok else "failure", None, stderr or stdout)
        if ok:
            await self.refresh_status(db, repo)
        return OperationResult(success=ok, stdout=stdout, stderr=stderr)

    async def pull_repo(self, db: Session, repo: GitRepo) -> OperationResult:
        ok, stdout, stderr = await self._git.pull(repo.path)
        self.log_operation(db, repo.id, "pull", "success" if ok else "failure", None, stderr or stdout)
        if ok:
            await self.refresh_status(db, repo)
        return OperationResult(success=ok, stdout=stdout, stderr=stderr)

    async def fetch_repo(self, db: Session, repo: GitRepo) -> OperationResult:
        ok, stdout, stderr = await self._git.fetch(repo.path)
        self.log_operation(db, repo.id, "fetch", "success" if ok else "failure", None, stderr or stdout)
        if ok:
            await self.refresh_status(db, repo)
        return OperationResult(success=ok, stdout=stdout, stderr=stderr)

    # ─────────────────────────────────────────────
    # 로그
    # ─────────────────────────────────────────────

    def log_operation(
        self,
        db: Session,
        repo_id: int,
        operation: str,
        status: str,
        message: Optional[str],
        detail: Optional[str],
    ) -> None:
        log = GitOperationLog(
            repo_id=repo_id,
            operation=operation,
            status=status,
            message=message,
            detail=detail,
        )
        db.add(log)
        db.commit()
