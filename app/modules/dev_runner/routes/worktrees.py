"""워크트리 목록 조회 API"""

import logging
from typing import List

from fastapi import APIRouter, HTTPException

from app.modules.dev_runner.schemas import WorktreeInfo
from app.modules.dev_runner.services.worktree_service import get_all_worktrees

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("", response_model=List[WorktreeInfo])
async def list_worktrees():
    """현재 레포의 워크트리 목록 + 브랜치별 커밋/diff stat/연결 계획서 반환"""
    try:
        return await get_all_worktrees()
    except Exception as e:
        logger.exception("워크트리 목록 조회 실패")
        raise HTTPException(status_code=500, detail=str(e))
