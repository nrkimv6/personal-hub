"""Instagram Post Service - 게시물 CRUD 서비스."""

import hashlib
import logging
import uuid
from datetime import datetime, date
from typing import List, Optional, Tuple

from sqlalchemy import func, desc, asc
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.models import InstagramPost
from app.models.instagram_post_tag import InstagramPostTag, InstagramPostTagRelation

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
        post_type: str = "NORMAL",
        likes: Optional[int] = None,
        comments: Optional[int] = None,
        service_account_id: Optional[int] = None,
        crawl_run_id: Optional[int] = None,
    ) -> Tuple[Optional[InstagramPost], str]:
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
            post_type: 게시물 유형 (NORMAL/SPONSORED/SUGGESTED)
            likes: 좋아요 수
            comments: 댓글 수
            service_account_id: 수집 계정 ID
            crawl_run_id: 크롤링 실행 ID

        Returns:
            (게시물, status) - status: 'created' | 'updated' | 'unchanged'
        """
        # unknown_* 형태의 post_id를 콘텐츠 기반 해시 ID로 변경
        if post_id.startswith("unknown_"):
            # 콘텐츠 기반 해시 생성 (account + caption 일부로 중복 체크)
            content_key = f"{account or ''}:{(caption or '')[:100]}:{is_ad}"
            hash_id = hashlib.md5(content_key.encode()).hexdigest()[:12]
            post_id = f"ad_{hash_id}"
            logger.debug(f"Generated content-based post_id: {post_id}")

        # post_id로 기존 포스트 조회
        existing = self.get_post_by_instagram_id(post_id)

        now = datetime.now()

        if existing:
            # 기존 포스트가 있으면 업데이트 여부 확인
            has_changes = False

            # 변경된 필드 확인
            if caption and existing.caption != caption:
                existing.caption = caption
                has_changes = True
            if images and existing.images != images:
                existing.images = images
                has_changes = True
            if likes is not None and existing.likes != likes:
                existing.likes = likes
                has_changes = True
            if comments is not None and existing.comments != comments:
                existing.comments = comments
                has_changes = True
            if display_time and existing.display_time != display_time:
                existing.display_time = display_time
                has_changes = True

            # last_seen 정보는 항상 업데이트
            existing.last_seen_at = now
            existing.last_seen_run_id = crawl_run_id

            if has_changes:
                # 실제 내용이 변경되었으면 updated_at 갱신
                existing.updated_at = now
                self.db.commit()
                self.db.refresh(existing)
                logger.info(f"Updated post: {post_id} from @{account}")
                return existing, 'updated'
            else:
                # 변경 없으면 그냥 커밋 (last_seen만 업데이트)
                self.db.commit()
                self.db.refresh(existing)
                logger.debug(f"Post unchanged: {post_id}")
                return existing, 'unchanged'

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
            post_type=post_type,
            likes=likes,
            comments=comments,
            service_account_id=service_account_id,
            crawl_run_id=crawl_run_id,
            collected_at=now,
            created_at=now,
            last_seen_at=now,
            last_seen_run_id=crawl_run_id,
        )

        try:
            self.db.add(post)
            self.db.commit()
            self.db.refresh(post)
            logger.info(f"Created post: {post_id} from @{account}")
            return post, 'created'
        except IntegrityError as e:
            self.db.rollback()
            logger.warning(f"Duplicate post skipped (IntegrityError): {post_id}")
            return None, 'error'

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
        post_type: str = "NORMAL",
        likes: Optional[int] = None,
        comments: Optional[int] = None,
        service_account_id: Optional[int] = None,
        crawl_run_id: Optional[int] = None,
    ) -> Optional[InstagramPost]:
        """게시물 생성 (레거시 - create_or_update_post 사용 권장).

        Returns:
            생성된 게시물, 중복이면 None
        """
        post, status = self.create_or_update_post(
            post_id=post_id,
            account=account,
            url=url,
            caption=caption,
            images=images,
            posted_at=posted_at,
            display_time=display_time,
            is_ad=is_ad,
            post_type=post_type,
            likes=likes,
            comments=comments,
            service_account_id=service_account_id,
            crawl_run_id=crawl_run_id,
        )
        return post if status == 'created' else None

    def get_posts(
        self,
        account: Optional[str] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        is_ad: Optional[bool] = None,
        post_type: Optional[str] = None,
        tags: Optional[List[str]] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = "asc",
        is_active: Optional[bool] = None,
        search: Optional[str] = None,
        include_post_ids: Optional[List[int]] = None,
        exclude_post_ids: Optional[List[int]] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[InstagramPost], int]:
        """게시물 목록 조회.

        Args:
            account: 계정명 필터
            date_from: 시작 날짜
            date_to: 종료 날짜
            is_ad: 광고 필터 (레거시, post_type 권장)
            post_type: 게시물 유형 필터 (NORMAL/SPONSORED/SUGGESTED)
            tags: 태그 필터 (태그 이름 목록)
            sort_by: 정렬 기준 (collected_at)
            sort_order: 정렬 순서 (asc/desc)
            is_active: 활성화 상태 필터 (True/False/None)
            search: 캡션 검색어 (LIKE 검색)
            include_post_ids: 포함할 게시물 ID 목록 (있으면 해당 ID만 조회)
            exclude_post_ids: 제외할 게시물 ID 목록
            limit: 조회 개수
            offset: 시작 위치

        Returns:
            (게시물 목록, 전체 개수)
        """
        query = self.db.query(InstagramPost)

        # 캡션 검색어 필터 (LIKE)
        if search:
            query = query.filter(InstagramPost.caption.ilike(f"%{search}%"))

        # 활성화 상태 필터
        if is_active is not None:
            query = query.filter(InstagramPost.is_active == is_active)

        if account:
            query = query.filter(InstagramPost.account.ilike(f"%{account}%"))

        if date_from:
            query = query.filter(InstagramPost.collected_at >= datetime.combine(date_from, datetime.min.time()))

        if date_to:
            query = query.filter(InstagramPost.collected_at <= datetime.combine(date_to, datetime.max.time()))

        if is_ad is not None:
            query = query.filter(InstagramPost.is_ad == is_ad)

        # 게시물 유형 필터
        if post_type:
            query = query.filter(InstagramPost.post_type == post_type)

        # 태그 필터
        if tags:
            query = (
                query.join(InstagramPostTagRelation)
                .join(InstagramPostTag)
                .filter(InstagramPostTag.name.in_(tags))
                .distinct()
            )

        # 게시물 ID 필터 (include/exclude)
        if include_post_ids is not None:
            if len(include_post_ids) == 0:
                # 빈 목록이면 결과 없음
                return [], 0
            query = query.filter(InstagramPost.id.in_(include_post_ids))

        if exclude_post_ids:
            query = query.filter(~InstagramPost.id.in_(exclude_post_ids))

        total = query.count()

        # 정렬 적용
        # 기본: 수집일 내림차순 + AI분류시간 내림차순 (NULLS LAST)
        order_func = asc if sort_order == "asc" else desc

        # sort_by 필드에 따른 정렬
        if sort_by == "posted_at":
            query = query.order_by(order_func(InstagramPost.posted_at))
        else:
            # 기본값: collected_at DESC, classified_at DESC (NULLS LAST)
            query = query.order_by(
                order_func(InstagramPost.collected_at),
                desc(InstagramPost.classified_at).nulls_last(),
            )

        posts = query.offset(offset).limit(limit).all()

        return posts, total

    def get_post_by_id(self, post_id: int) -> Optional[InstagramPost]:
        """ID로 게시물 조회.

        Args:
            post_id: 게시물 DB ID

        Returns:
            게시물 또는 None
        """
        return (
            self.db.query(InstagramPost)
            .filter(InstagramPost.id == post_id)
            .first()
        )

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

    def update_post_tags(self, post_id: int, tag_ids: List[int]) -> Optional[InstagramPost]:
        """게시물 태그 업데이트 (전체 교체).

        Args:
            post_id: 게시물 DB ID
            tag_ids: 새 태그 ID 목록

        Returns:
            업데이트된 게시물 또는 None
        """
        post = self.get_post_by_id(post_id)
        if not post:
            return None

        # 기존 태그 관계 삭제
        self.db.query(InstagramPostTagRelation).filter(
            InstagramPostTagRelation.post_id == post_id
        ).delete()

        # 새 태그 관계 추가
        for tag_id in tag_ids:
            # 태그 존재 확인
            tag = self.db.query(InstagramPostTag).filter(
                InstagramPostTag.id == tag_id
            ).first()
            if tag:
                relation = InstagramPostTagRelation(
                    post_id=post_id,
                    tag_id=tag_id
                )
                self.db.add(relation)

        self.db.commit()
        self.db.refresh(post)

        logger.info(f"Updated tags for post {post_id}: {tag_ids}")
        return post

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

    def get_posts_by_run_id(
        self,
        run_id: int,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[InstagramPost], int]:
        """특정 실행에서 수집된 게시물 조회.

        Args:
            run_id: 크롤링 실행 ID
            limit: 조회 개수
            offset: 시작 위치

        Returns:
            (게시물 목록, 전체 개수)
        """
        query = self.db.query(InstagramPost).filter(
            InstagramPost.crawl_run_id == run_id
        )

        total = query.count()
        posts = query.order_by(desc(InstagramPost.collected_at)).offset(offset).limit(limit).all()

        return posts, total

    def update_post_active_status(self, post_id: int, is_active: bool) -> Optional[InstagramPost]:
        """게시물 활성화 상태 업데이트.

        Args:
            post_id: 게시물 DB ID
            is_active: 활성화 상태

        Returns:
            업데이트된 게시물 또는 None
        """
        post = self.get_post_by_id(post_id)
        if not post:
            return None

        post.is_active = is_active
        self.db.commit()
        self.db.refresh(post)

        logger.info(f"Updated post {post_id} is_active={is_active}")
        return post

    def batch_delete(self, post_ids: List[int]) -> int:
        """게시물 일괄 삭제.

        Args:
            post_ids: 삭제할 게시물 ID 목록

        Returns:
            삭제된 게시물 수
        """
        if not post_ids:
            return 0

        deleted = self.db.query(InstagramPost).filter(
            InstagramPost.id.in_(post_ids)
        ).delete(synchronize_session=False)

        self.db.commit()
        logger.info(f"Batch deleted {deleted} posts")
        return deleted

    def batch_update_active(self, post_ids: List[int], is_active: bool) -> int:
        """게시물 일괄 활성화/비활성화.

        Args:
            post_ids: 업데이트할 게시물 ID 목록
            is_active: 활성화 상태

        Returns:
            업데이트된 게시물 수
        """
        if not post_ids:
            return 0

        updated = self.db.query(InstagramPost).filter(
            InstagramPost.id.in_(post_ids)
        ).update({"is_active": is_active}, synchronize_session=False)

        self.db.commit()
        logger.info(f"Batch updated {updated} posts is_active={is_active}")
        return updated

