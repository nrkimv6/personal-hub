"""Facebook API Routes."""

import logging
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.facebook_post import FacebookPost
from ..services.post_service import PostService
from ..services.url_parser import parse_facebook_url, FacebookUrlType

logger = logging.getLogger("facebook.api")

router = APIRouter(prefix="/api/v1/facebook", tags=["facebook"])


# ============== Posts ==============

@router.get("/posts")
async def get_posts(
    account: Optional[str] = Query(None, description="계정명 필터"),
    post_type: Optional[str] = Query(None, description="게시물 유형 필터"),
    is_active: Optional[bool] = Query(True, description="활성 게시물만"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Facebook 게시물 목록 조회."""
    service = PostService(db)
    posts = service.get_posts(
        account=account,
        post_type=post_type,
        is_active=is_active,
        limit=limit,
        offset=offset,
    )
    total = service.count_posts(account=account, is_active=is_active)

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "posts": [_serialize_post(p) for p in posts],
    }


@router.get("/posts/{post_db_id}")
async def get_post(
    post_db_id: int,
    db: Session = Depends(get_db),
):
    """Facebook 게시물 단건 조회."""
    post = db.query(FacebookPost).filter(FacebookPost.id == post_db_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="게시물을 찾을 수 없습니다.")
    return _serialize_post(post)


@router.delete("/posts/{post_db_id}")
async def delete_post(
    post_db_id: int,
    db: Session = Depends(get_db),
):
    """Facebook 게시물 비활성화."""
    post = db.query(FacebookPost).filter(FacebookPost.id == post_db_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="게시물을 찾을 수 없습니다.")
    post.is_active = False
    db.commit()
    return {"success": True, "message": "게시물이 비활성화되었습니다."}


# ============== URL Parser ==============

@router.post("/url/parse")
async def parse_url(body: dict):
    """Facebook URL 파싱."""
    url = body.get("url", "")
    if not url:
        raise HTTPException(status_code=400, detail="url이 필요합니다.")
    parsed = parse_facebook_url(url)
    return {
        "url_type": parsed.url_type.value,
        "username": parsed.username,
        "page_name": parsed.page_name,
        "group_id": parsed.group_id,
        "post_id": parsed.post_id,
        "reel_id": parsed.reel_id,
        "is_supported": parsed.is_supported,
        "original_url": parsed.original_url,
    }


# ============== Stats ==============

@router.get("/stats")
async def get_stats(
    db: Session = Depends(get_db),
):
    """Facebook 수집 통계."""
    from sqlalchemy import func

    total = db.query(func.count(FacebookPost.id)).scalar() or 0
    active = (
        db.query(func.count(FacebookPost.id))
        .filter(FacebookPost.is_active == True)
        .scalar()
        or 0
    )
    by_type = (
        db.query(FacebookPost.post_type, func.count(FacebookPost.id))
        .group_by(FacebookPost.post_type)
        .all()
    )
    by_account = (
        db.query(FacebookPost.account, func.count(FacebookPost.id))
        .group_by(FacebookPost.account)
        .order_by(func.count(FacebookPost.id).desc())
        .limit(10)
        .all()
    )

    return {
        "total_posts": total,
        "active_posts": active,
        "by_type": {t: c for t, c in by_type},
        "top_accounts": [{"account": a, "count": c} for a, c in by_account],
    }


# ============== Helper ==============

def _serialize_post(post: FacebookPost) -> dict:
    """FacebookPost를 딕셔너리로 직렬화합니다."""
    return {
        "id": post.id,
        "post_id": post.post_id,
        "account": post.account,
        "url": post.url,
        "caption": post.caption,
        "images": post.images or [],
        "posted_at": post.posted_at.isoformat() if post.posted_at else None,
        "display_time": post.display_time,
        "reactions": post.reactions or {},
        "total_reactions": post.total_reactions or 0,
        "shares": post.shares or 0,
        "comments": post.comments or 0,
        "post_type": post.post_type,
        "original_post_url": post.original_post_url,
        "link_preview": post.link_preview,
        "source_type": post.source_type,
        "group_id": post.group_id,
        "group_name": post.group_name,
        "page_id": post.page_id,
        "page_name": post.page_name,
        "service_account_id": post.service_account_id,
        "is_active": post.is_active,
        "classified_type": post.classified_type,
        "classified_id": post.classified_id,
        "classified_at": post.classified_at.isoformat() if post.classified_at else None,
        "collected_at": post.collected_at.isoformat() if post.collected_at else None,
        "created_at": post.created_at.isoformat() if post.created_at else None,
    }
