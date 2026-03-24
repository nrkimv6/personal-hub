"""
수집 이력 API.
"""
from __future__ import annotations

import os
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.kakao_monitor import KakaoCollectedPost
from app.modules.kakao_monitor.services.collect_service import KakaoCollectService

router = APIRouter(prefix="/api/v1/kakao-monitor", tags=["kakao-monitor"])


# ========== Schemas ==========

class PostOut(BaseModel):
    id: int
    config_id: int
    keyword_id: Optional[int]
    matched_keyword: Optional[str]
    trigger_message: Optional[str]
    collected_content: Optional[str]
    collected_at: Optional[str]
    screenshot_path: Optional[str]
    status: str

    class Config:
        from_attributes = True


class PostListResponse(BaseModel):
    items: List[PostOut]
    total: int
    skip: int
    limit: int


# ========== Routes ==========

@router.get("/posts", response_model=PostListResponse)
def get_posts(
    config_id: Optional[int] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    svc = KakaoCollectService(db)
    items, total = svc.get_collected_posts(config_id=config_id, skip=skip, limit=limit)
    return PostListResponse(
        items=[_post_to_out(p) for p in items],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/posts/{post_id}", response_model=PostOut)
def get_post(post_id: int, db: Session = Depends(get_db)):
    post = db.query(KakaoCollectedPost).filter(KakaoCollectedPost.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    return _post_to_out(post)


@router.delete("/posts/{post_id}", status_code=204)
def delete_post(post_id: int, db: Session = Depends(get_db)):
    post = db.query(KakaoCollectedPost).filter(KakaoCollectedPost.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    # 스크린샷 파일 삭제
    if post.screenshot_path and os.path.exists(post.screenshot_path):
        try:
            os.remove(post.screenshot_path)
        except OSError:
            pass

    db.delete(post)
    db.commit()


# ========== Helpers ==========

def _post_to_out(p: KakaoCollectedPost) -> PostOut:
    return PostOut(
        id=p.id,
        config_id=p.config_id,
        keyword_id=p.keyword_id,
        matched_keyword=p.matched_keyword,
        trigger_message=p.trigger_message,
        collected_content=p.collected_content,
        collected_at=str(p.collected_at) if p.collected_at else None,
        screenshot_path=p.screenshot_path,
        status=p.status,
    )
