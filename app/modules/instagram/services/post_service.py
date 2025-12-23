"""Instagram Post Service - 게시물 CRUD 서비스."""

import hashlib
import logging
import uuid
from datetime import datetime, date
from typing import List, Optional, Tuple

from sqlalchemy import func, desc, asc, or_, and_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import InstagramPost, InstagramCrawlRun
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
        likes: Optional[int] = None,
        comments: Optional[int] = None,
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
            likes: 좋아요 수
            comments: 댓글 수
            account_id: 수집 계정 ID
            crawl_run_id: 크롤링 실행 ID

        Returns:
            (게시물, is_new) - is_new=True면 새로 생성됨, False면 이미 존재함
        """
        # unknown_* 형태의 post_id를 콘텐츠 기반 해시 ID로 변경
        if post_id.startswith("unknown_"):
            # 콘텐츠 기반 해시 생성 (account + caption 일부로 중복 체크)
            content_key = f"{account or ''}:{(caption or '')[:100]}:{is_ad}"
            hash_id = hashlib.md5(content_key.encode()).hexdigest()[:12]
            post_id = f"ad_{hash_id}"
            logger.debug(f"Generated content-based post_id: {post_id}")

        # post_id로 중복 체크 (unknown_* → ad_* 변환 후에도 체크)
        existing = self.get_post_by_instagram_id(post_id)
        if existing:
            logger.debug(f"Post already exists by post_id: {post_id}")
            return existing, False

        # URL로 중복 체크 (URL이 있을 때)
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
            likes=likes,
            comments=comments,
            account_id=account_id,
            crawl_run_id=crawl_run_id,
            collected_at=datetime.now(),
        )

        try:
            self.db.add(post)
            self.db.commit()
            self.db.refresh(post)
            logger.info(f"Created post: {post_id} from @{account}")
            return post, True
        except IntegrityError as e:
            self.db.rollback()
            logger.warning(f"Duplicate post skipped (IntegrityError): {post_id}")
            return None, False

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
        likes: Optional[int] = None,
        comments: Optional[int] = None,
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
            likes=likes,
            comments=comments,
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
        tags: Optional[List[str]] = None,
        llm_tag: Optional[str] = None,
        llm_status: Optional[str] = None,
        event_status: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = "asc",
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[InstagramPost], int]:
        """게시물 목록 조회.

        Args:
            account: 계정명 필터
            date_from: 시작 날짜
            date_to: 종료 날짜
            is_ad: 광고 필터
            tags: 태그 필터 (태그 이름 목록)
            llm_tag: LLM 분류 태그 필터 (이벤트/팝업/홍보대사/기타)
            llm_status: LLM 분석 상태 필터 (pending/processing/completed/failed)
            event_status: 이벤트 진행상태 필터 (ongoing/upcoming/ended)
            sort_by: 정렬 기준 (event_end/event_start/collected_at)
            sort_order: 정렬 순서 (asc/desc)
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

        # 태그 필터
        if tags:
            query = (
                query.join(InstagramPostTagRelation)
                .join(InstagramPostTag)
                .filter(InstagramPostTag.name.in_(tags))
                .distinct()
            )

        # LLM 분류 태그 필터
        if llm_tag:
            query = query.filter(InstagramPost.llm_tag == llm_tag)

        # LLM 분석 상태 필터
        if llm_status:
            query = query.filter(InstagramPost.llm_status == llm_status)

        # 이벤트 진행상태 필터
        if event_status:
            today = date.today()
            if event_status == "ongoing":
                # 진행 중: 시작일 <= 오늘 AND (종료일 >= 오늘 OR 종료일 없음)
                query = query.filter(
                    and_(
                        or_(
                            InstagramPost.llm_event_start <= today,
                            InstagramPost.llm_event_start.is_(None)
                        ),
                        or_(
                            InstagramPost.llm_event_end >= today,
                            InstagramPost.llm_event_end.is_(None)
                        )
                    )
                )
            elif event_status == "upcoming":
                # 예정: 시작일 > 오늘
                query = query.filter(InstagramPost.llm_event_start > today)
            elif event_status == "ended":
                # 종료: 종료일 < 오늘
                query = query.filter(InstagramPost.llm_event_end < today)
            elif event_status == "ongoing_or_upcoming":
                # 진행 중 + 예정: 종료일이 오늘 이후이거나 없음
                query = query.filter(
                    or_(
                        InstagramPost.llm_event_end >= today,
                        InstagramPost.llm_event_end.is_(None)
                    )
                )

        total = query.count()

        # 정렬 적용
        order_func = asc if sort_order == "asc" else desc
        if sort_by == "event_end":
            # NULL을 마지막으로
            if sort_order == "asc":
                query = query.order_by(
                    InstagramPost.llm_event_end.is_(None),
                    asc(InstagramPost.llm_event_end),
                    asc(InstagramPost.llm_event_start)
                )
            else:
                query = query.order_by(
                    InstagramPost.llm_event_end.is_(None),
                    desc(InstagramPost.llm_event_end),
                    desc(InstagramPost.llm_event_start)
                )
        elif sort_by == "event_start":
            if sort_order == "asc":
                query = query.order_by(
                    InstagramPost.llm_event_start.is_(None),
                    asc(InstagramPost.llm_event_start)
                )
            else:
                query = query.order_by(
                    InstagramPost.llm_event_start.is_(None),
                    desc(InstagramPost.llm_event_start)
                )
        else:
            # 기본: 수집일 내림차순
            query = query.order_by(desc(InstagramPost.collected_at))

        posts = query.offset(offset).limit(limit).all()

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
