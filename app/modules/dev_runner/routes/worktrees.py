"""워크트리 목록 조회 API"""

import logging
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.dev_runner.schemas import (
    WorktreeCleanupRequest,
    WorktreeCleanupResponse,
    WorktreeCommit,
    WorktreeInfo,
    WorktreeListResponse,
)
from app.modules.dev_runner.services.worktree_service import (
    cleanup_worktrees,
    get_all_worktrees,
    get_all_worktrees_full,
    get_worktree_commits,
    list_worktrees,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _resolve_repo_root(repo_id: Optional[int], db: Session) -> Optional[Path]:
    """repo_id가 있으면 DB에서 경로 조회, 없으면 None 반환"""
    if repo_id is None:
        return None
    try:
        from app.modules.git_repos.services.repo_service import GitRepoService
        repo = GitRepoService().get_repo(db, repo_id)
    except Exception:
        raise HTTPException(status_code=500, detail="레포지토리 조회 중 오류가 발생했습니다.")
    if repo is None:
        raise HTTPException(status_code=404, detail="레포지토리를 찾을 수 없습니다.")
    return Path(repo.path)


@router.get("/repos")
async def list_repos(db: Session = Depends(get_db)):
    """등록된 git 레포 목록 반환 — 프론트 레포 선택 드롭다운용"""
    try:
        from app.modules.git_repos.services.repo_service import GitRepoService
        repos = GitRepoService().list_repos(db)
        return [{"id": r.id, "alias": r.alias, "path": r.path} for r in repos]
    except Exception as e:
        logger.exception("레포 목록 조회 실패")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("", response_model=List[WorktreeInfo])
async def list_worktrees_v1(
    repo_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """현재 레포의 워크트리 목록 반환 (v1 호환: list 형태)"""
    try:
        repo_root = _resolve_repo_root(repo_id, db)
        kwargs = {"repo_root": repo_root} if repo_root else {}
        return await get_all_worktrees_full(**kwargs)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("워크트리 목록 조회 실패")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/v2", response_model=WorktreeListResponse)
async def list_worktrees_v2(
    request: Request,
    repo_id: Optional[int] = Query(None),
    force: bool = Query(False, description="캐시 무시"),
    db: Session = Depends(get_db),
):
    """전체 워크트리 상태 반환 (v2: plan_only·branch_unresolved·main_dirty 포함).

    참고: queued claim은 worktree가 생성되기 전의 상태이므로 이 API의 worktree source로 포함하지 않는다.
    claim은 plan_execution_claims 테이블을 직접 조회하거나 /plans API의 execution_claim_* 필드로 확인한다.
    """
    try:
        repo_root = _resolve_repo_root(repo_id, db)
        kwargs = {"repo_root": repo_root} if repo_root else {}
        cache_control = request.headers.get("Cache-Control", "")
        force_refresh = force or "no-cache" in cache_control.lower()
        return await get_all_worktrees(
            **kwargs,
            use_cache=True,
            cache_repo_id=repo_id,
            force=force_refresh,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("워크트리 목록 조회 실패 (v2)")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/v2/commits", response_model=List[WorktreeCommit])
async def list_worktree_commits_v2(
    branch: str = Query(..., min_length=1),
    repo_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """특정 워크트리 브랜치의 커밋 상세를 lazy-load 한다."""
    try:
        repo_root = _resolve_repo_root(repo_id, db)
        kwargs = {"repo_root": repo_root} if repo_root else {}
        existing_branches = {wt["branch"] for wt in await list_worktrees(**kwargs)}
        if branch not in existing_branches:
            raise HTTPException(status_code=404, detail="워크트리 브랜치를 찾을 수 없습니다.")
        return await get_worktree_commits(branch, **kwargs)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("워크트리 커밋 상세 조회 실패 (v2)")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cleanup", response_model=WorktreeCleanupResponse)
async def cleanup_worktrees_v1(
    req: WorktreeCleanupRequest = Body(...),
    repo_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """정리 가능한 워크트리 일괄 cleanup."""
    try:
        repo_root = _resolve_repo_root(repo_id, db)
        kwargs = {"repo_root": repo_root} if repo_root else {}
        return await cleanup_worktrees(req.branches, req.dry_run, **kwargs)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("워크트리 cleanup 실패")
        raise HTTPException(status_code=500, detail=str(e))
