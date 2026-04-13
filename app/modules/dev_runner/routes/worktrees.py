"""워크트리 목록 조회 API"""

import logging
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.dev_runner.schemas import WorktreeInfo, WorktreeListResponse
from app.modules.dev_runner.services.worktree_service import get_all_worktrees
from app.modules.git_repos.services.repo_service import GitRepoService

logger = logging.getLogger(__name__)
router = APIRouter()


def _resolve_repo_root(
    repo_id: Optional[int],
    db: Session,
) -> Optional[Path]:
    """repo_id가 있으면 저장된 레포 경로를 Path로 반환."""
    if repo_id is None:
        return None

    repo = GitRepoService().get_repo(db, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="레포지토리를 찾을 수 없습니다.")
    return Path(repo.path)


@router.get("", response_model=List[WorktreeInfo])
async def list_worktrees(
    repo_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """현재 레포의 워크트리 목록 + 브랜치별 커밋/diff stat/연결 계획서 반환."""
    try:
        repo_root = _resolve_repo_root(repo_id, db)
        response = (
            await get_all_worktrees(repo_root=repo_root)
            if repo_root is not None
            else await get_all_worktrees()
        )
        if isinstance(response, list):
            return response
        return response.worktrees
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("워크트리 목록 조회 실패")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/v2", response_model=WorktreeListResponse)
async def list_worktrees_v2(
    repo_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """멀티 레포 조회 API. repo_id가 없으면 현재 레포 기준."""
    try:
        repo_root = _resolve_repo_root(repo_id, db)
        if repo_root is None:
            response = await get_all_worktrees()
            if isinstance(response, list):
                return WorktreeListResponse(worktrees=response)
            return response
        return await get_all_worktrees(repo_root=repo_root)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("워크트리 v2 목록 조회 실패")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/repos")
async def list_worktree_repos(db: Session = Depends(get_db)):
    """등록 레포지토리 목록(멀티 레포 선택용)."""
    svc = GitRepoService()
    repos = svc.list_repos(db)
    return [{"id": repo.id, "alias": repo.alias, "path": repo.path} for repo in repos]
