"""Facebook Post Service - 게시물 CRUD 서비스."""

import logging
from datetime import datetime
from typing import List, Optional, Tuple, Dict, Any

from sqlalchemy import func, desc
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.facebook_post import FacebookPost
from .crawler import FacebookPostData

logger = logging.getLogger("facebook.post_service")


class PostService:
    """Facebook 게시물 CRUD 서비스."""

    def __init__(self, db: Session):
        """
        Args:
            db: SQLAlchemy 세션
        """
        self.db = db

    def save_post(
        self,
        post: FacebookPostData,
        service_account_id: Optional[int] = None,
        crawl_run_id: Optional[int] = None,
    ) -> Optional[FacebookPost]:
        """Facebook 게시물을 저장하거나 업데이트합니다.

        Args:
            post: 크롤링된 게시물 데이터
            service_account_id: 수집 계정 ID
            crawl_run_id: 크롤링 실행 ID

        Returns:
            저장된 FacebookPost 또는 None (실패 시)
        """
        if not post.post_id:
            logger.warning("post_id 없음 - 저장 스킵")
            return None

        existing = self.get_post_by_id(post.post_id)
        now = datetime.now()

        if existing:
            return self._update_post(existing, post, now)
        else:
            return self._create_post(post, service_account_id, crawl_run_id, now)

    def _create_post(
        self,
        post: FacebookPostData,
        service_account_id: Optional[int],
        crawl_run_id: Optional[int],
        now: datetime,
    ) -> Optional[FacebookPost]:
        """새 게시물 생성."""
        try:
            posted_at = None
            if post.datetime_str:
                try:
                    posted_at = datetime.fromisoformat(post.datetime_str)
                except Exception:
                    pass

            db_post = FacebookPost(
                post_id=post.post_id,
                account=post.account or "",
                url=post.url,
                caption=post.caption,
                images=post.images or [],
                posted_at=posted_at,
                display_time=post.display_time,
                reactions=post.reactions or {},
                total_reactions=post.total_reactions or 0,
                shares=post.shares or 0,
                comments=post.comments or 0,
                post_type=post.post_type or "NORMAL",
                original_post_url=post.original_post_url,
                link_preview=post.link_preview,
                source_type=post.source_type or "feed",
                group_id=post.group_id,
                group_name=post.group_name,
                page_id=post.page_id,
                page_name=post.page_name,
                service_account_id=service_account_id,
                crawl_run_id=crawl_run_id,
                collected_at=now,
                created_at=now,
                last_seen_at=now,
                last_seen_run_id=crawl_run_id,
                is_active=True,
            )
            self.db.add(db_post)
            self.db.commit()
            self.db.refresh(db_post)
            logger.debug(f"게시물 생성: post_id={post.post_id}")
            return db_post

        except IntegrityError:
            self.db.rollback()
            logger.warning(f"게시물 중복 (IntegrityError): post_id={post.post_id}")
            return self.get_post_by_id(post.post_id)
        except Exception as e:
            self.db.rollback()
            logger.error(f"게시물 생성 실패: {e}")
            return None

    def _update_post(
        self,
        existing: FacebookPost,
        post: FacebookPostData,
        now: datetime,
    ) -> FacebookPost:
        """기존 게시물 업데이트."""
        changed = False

        if post.reactions and post.reactions != existing.reactions:
            existing.reactions = post.reactions
            changed = True
        if post.total_reactions and post.total_reactions != existing.total_reactions:
            existing.total_reactions = post.total_reactions
            changed = True
        if post.shares and post.shares != existing.shares:
            existing.shares = post.shares
            changed = True
        if post.comments and post.comments != existing.comments:
            existing.comments = post.comments
            changed = True
        if post.caption and existing.caption != post.caption:
            existing.caption = post.caption
            changed = True

        existing.last_seen_at = now

        if changed:
            existing.updated_at = now

        try:
            self.db.commit()
        except Exception as e:
            self.db.rollback()
            logger.error(f"게시물 업데이트 실패: {e}")

        return existing

    def get_post_by_id(self, post_id: str) -> Optional[FacebookPost]:
        """post_id로 게시물 조회."""
        return (
            self.db.query(FacebookPost)
            .filter(FacebookPost.post_id == post_id)
            .first()
        )

    def get_posts(
        self,
        account: Optional[str] = None,
        post_type: Optional[str] = None,
        is_active: Optional[bool] = True,
        limit: int = 20,
        offset: int = 0,
    ) -> List[FacebookPost]:
        """게시물 목록 조회."""
        q = self.db.query(FacebookPost)
        if account:
            q = q.filter(FacebookPost.account == account)
        if post_type:
            q = q.filter(FacebookPost.post_type == post_type)
        if is_active is not None:
            q = q.filter(FacebookPost.is_active == is_active)
        return q.order_by(desc(FacebookPost.posted_at)).offset(offset).limit(limit).all()

    def count_posts(
        self,
        account: Optional[str] = None,
        is_active: Optional[bool] = True,
    ) -> int:
        """게시물 수 집계."""
        q = self.db.query(func.count(FacebookPost.id))
        if account:
            q = q.filter(FacebookPost.account == account)
        if is_active is not None:
            q = q.filter(FacebookPost.is_active == is_active)
        return q.scalar() or 0
