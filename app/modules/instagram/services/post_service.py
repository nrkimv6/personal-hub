"""Instagram Post Service - 게시물 CRUD 서비스."""

import json
import logging
from datetime import datetime, date
from typing import List, Optional, Tuple

from sqlalchemy import func, desc
from sqlalchemy.orm import Session

from app.models import InstagramPost, InstagramCrawlRun

logger = logging.getLogger("instagram.post_service")


class PostService:
    """Instagram 게시물 CRUD 서비스."""

    def __init__(self, db: Session):
        """
        Args:
            db: SQLAlchemy 세션
        """
        self.db = db

    def create_or_update_post(
        self,
        post_id: str,
        account: Optional[str] = None,
        url: Optional[str] = None,
        caption: Optional[str] = None,
        images: Optional[List[dict]] = None,
        posted_at: Optional[datetime] = None,
        display_time: Optional[str] = None,
        is_ad: bool = False,
        account_id: Optional[int] = None,
        crawl_run_id: Optional[int] = None,
    ) -> Tuple[Optional[InstagramPost], bool]:
        """게시물 생성 또는 업데이트 (upsert).

        Args:
            post_id: Instagram 게시물 ID
            account: 작성자 계정명
            url: 게시물 URL
            caption: 본문
            images: 이미지 목록
            posted_at: 게시 시간
            display_time: 상대 시간
            is_ad: 광고 여부
            account_id: 수집 계정 ID
            crawl_run_id: 크롤링 실행 ID

        Returns:
            (게시물, is_new) - is_new=True면 새로 생성됨, False면 이미 존재함
        """
        # 1. post_id로 중복 체크 (unknown_* 형태는 제외)
        existing = None
        if not post_id.startswith("unknown_"):
            existing = self.get_post_by_instagram_id(post_id)
            if existing:
                logger.debug(f"Post already exists by post_id: {post_id}")
                return existing, False

        # 2. URL로 중복 체크 (URL이 있을 때)
        if url:
            existing = self.get_post_by_url(url)
            if existing:
                logger.debug(f"Post already exists by url: {url}")
                return existing, False

        # 새 게시물 생성
        post = InstagramPost(
            post_id=post_id,
            account=account or "",
            url=url,
            caption=caption,
            images=images or [],
            posted_at=posted_at,
            display_time=display_time,
            is_ad=is_ad,
            account_id=account_id,
            crawl_run_id=crawl_run_id,
            collected_at=datetime.utcnow(),
        )

        self.db.add(post)
        self.db.commit()
        self.db.refresh(post)

        logger.info(f"Created post: {post_id} from @{account}")
        return post, True

    def create_post(
        self,
        post_id: str,
        account: Optional[str] = None,
        url: Optional[str] = None,
        caption: Optional[str] = None,
        images: Optional[List[dict]] = None,
        posted_at: Optional[datetime] = None,
        display_time: Optional[str] = None,
        is_ad: bool = False,
        account_id: Optional[int] = None,
        crawl_run_id: Optional[int] = None,
    ) -> Optional[InstagramPost]:
        """게시물 생성 (레거시 - create_or_update_post 사용 권장).

        Returns:
            생성된 게시물, 중복이면 None
        """
        post, is_new = self.create_or_update_post(
            post_id=post_id,
            account=account,
            url=url,
            caption=caption,
            images=images,
            posted_at=posted_at,
            display_time=display_time,
            is_ad=is_ad,
            account_id=account_id,
            crawl_run_id=crawl_run_id,
        )
        return post if is_new else None

    def get_posts(
        self,
        account: Optional[str] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        is_ad: Optional[bool] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[InstagramPost], int]:
        """게시물 목록 조회.

        Args:
            account: 계정명 필터
            date_from: 시작 날짜
            date_to: 종료 날짜
            is_ad: 광고 필터
            limit: 조회 개수
            offset: 시작 위치

        Returns:
            (게시물 목록, 전체 개수)
        """
        query = self.db.query(InstagramPost)

        if account:
            query = query.filter(InstagramPost.account.ilike(f"%{account}%"))

        if date_from:
            query = query.filter(InstagramPost.collected_at >= datetime.combine(date_from, datetime.min.time()))

        if date_to:
            query = query.filter(InstagramPost.collected_at <= datetime.combine(date_to, datetime.max.time()))

        if is_ad is not None:
            query = query.filter(InstagramPost.is_ad == is_ad)

        total = query.count()

        posts = query.order_by(desc(InstagramPost.collected_at)).offset(offset).limit(limit).all()

        return posts, total

    def get_post_by_id(self, post_id: int) -> Optional[InstagramPost]:
        """ID로 게시물 조회.

        Args:
            post_id: 게시물 DB ID

        Returns:
            게시물 또는 None
        """
        return self.db.query(InstagramPost).filter(InstagramPost.id == post_id).first()

    def get_post_by_instagram_id(self, instagram_post_id: str) -> Optional[InstagramPost]:
        """Instagram 게시물 ID로 조회.

        Args:
            instagram_post_id: Instagram 게시물 ID

        Returns:
            게시물 또는 None
        """
        return self.db.query(InstagramPost).filter(InstagramPost.post_id == instagram_post_id).first()

    def get_post_by_url(self, url: str) -> Optional[InstagramPost]:
        """URL로 게시물 조회.

        Args:
            url: 게시물 URL

        Returns:
            게시물 또는 None
        """
        return self.db.query(InstagramPost).filter(InstagramPost.url == url).first()

    def delete_post(self, post_id: int) -> bool:
        """게시물 삭제.

        Args:
            post_id: 게시물 DB ID

        Returns:
            삭제 성공 여부
        """
        post = self.get_post_by_id(post_id)
        if not post:
            return False

        self.db.delete(post)
        self.db.commit()

        logger.info(f"Deleted post: {post.post_id}")
        return True

    def exists_by_post_id(self, instagram_post_id: str) -> bool:
        """게시물 존재 여부 확인.

        Args:
            instagram_post_id: Instagram 게시물 ID

        Returns:
            존재하면 True
        """
        return self.db.query(InstagramPost).filter(
            InstagramPost.post_id == instagram_post_id
        ).first() is not None

    def get_total_count(self) -> int:
        """전체 게시물 수."""
        return self.db.query(InstagramPost).count()

    def get_today_count(self) -> int:
        """오늘 수집된 게시물 수."""
        today_start = datetime.combine(date.today(), datetime.min.time())
        return self.db.query(InstagramPost).filter(
            InstagramPost.collected_at >= today_start
        ).count()

    def get_recent_posts(self, limit: int = 5) -> List[InstagramPost]:
        """최근 수집된 게시물."""
        return self.db.query(InstagramPost).order_by(
            desc(InstagramPost.collected_at)
        ).limit(limit).all()
