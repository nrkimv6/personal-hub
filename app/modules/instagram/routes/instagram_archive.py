"""Instagram Archive API Routes."""

import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.database import get_db
from app.models.instagram_post_archive import InstagramPostArchive
from ..models.schemas import PostListResponse

logger = logging.getLogger("instagram.archive.api")

router = APIRouter(prefix="/api/v1/instagram", tags=["instagram-archive"])


@router.get("/posts/archive", response_model=PostListResponse)
def get_archive_posts(
    account: Optional[str] = Query(None, description="계정명 필터"),
    date_from: Optional[date] = Query(None, description="시작 날짜 (posted_at 기준)"),
    date_to: Optional[date] = Query(None, description="종료 날짜 (posted_at 기준)"),
    post_type: Optional[str] = Query(None, description="게시물 유형 필터 (NORMAL/SPONSORED/SUGGESTED)"),
    search: Optional[str] = Query(None, description="캡션 검색어"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    limit: int = Query(20, ge=1, le=100, description="페이지당 개수"),
    db: Session = Depends(get_db),
):
    """아카이브된 Instagram 게시물 목록 조회.

    archive 파티션 테이블에서 과거 게시물을 검색합니다.
    tags, llm_status 등 ORM relationship 의존 필터는 지원하지 않습니다.
    """
    query = db.query(InstagramPostArchive)

    if account:
        query = query.filter(InstagramPostArchive.account == account)

    if date_from:
        from datetime import datetime
        query = query.filter(InstagramPostArchive.posted_at >= datetime.combine(date_from, datetime.min.time()))

    if date_to:
        from datetime import datetime, timedelta
        query = query.filter(
            InstagramPostArchive.posted_at < datetime.combine(date_to, datetime.min.time()) + timedelta(days=1)
        )

    if post_type:
        query = query.filter(InstagramPostArchive.post_type == post_type)

    if search:
        query = query.filter(InstagramPostArchive.caption.ilike(f"%{search}%"))

    total = query.count()
    offset = (page - 1) * limit
    posts = query.order_by(desc(InstagramPostArchive.posted_at)).offset(offset).limit(limit).all()

    post_dicts = []
    for p in posts:
        post_dicts.append({
            "id": p.id,
            "post_id": p.post_id,
            "account": p.account,
            "url": p.url,
            "caption": p.caption,
            "images": p.images or [],
            "posted_at": p.posted_at,
            "display_time": p.display_time,
            "is_ad": p.is_ad or False,
            "post_type": p.post_type or "NORMAL",
            "collected_at": p.collected_at or p.created_at,
            "crawl_run_id": p.crawl_run_id,
            "tags": [],
            "is_active": p.is_active if p.is_active is not None else True,
            "llm_status": None,
        })

    return PostListResponse(posts=post_dicts, total=total, page=page, limit=limit)
