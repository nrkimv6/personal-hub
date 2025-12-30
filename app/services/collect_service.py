"""수집 관리 서비스."""

from datetime import datetime
from typing import Optional, List, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import or_, desc

from app.models.instagram_post import InstagramPost
from app.models.universal_crawl import CrawledPage
from app.schemas.collect import CollectedPostBase


class CollectService:
    """수집된 게시물 통합 관리 서비스."""

    def __init__(self, db: Session):
        self.db = db

    def get_posts_paginated(
        self,
        page: int = 1,
        limit: int = 20,
        source_type: Optional[str] = None,
        url_type: Optional[str] = None,
        classification: Optional[str] = None,
        search: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        is_active: Optional[bool] = None,
    ) -> Tuple[List[CollectedPostBase], int]:
        """통합 게시물 목록 조회.

        instagram_posts와 crawled_pages를 통합하여 조회합니다.
        """
        results = []
        total = 0

        # Instagram 게시물 조회
        if source_type is None or source_type == 'instagram':
            ig_posts, ig_total = self._get_instagram_posts(
                page=page,
                limit=limit,
                url_type=url_type,
                classification=classification,
                search=search,
                date_from=date_from,
                date_to=date_to,
                is_active=is_active,
            )
            results.extend(ig_posts)
            total += ig_total

        # Web (CrawledPages) 조회
        if source_type is None or source_type == 'web':
            web_posts, web_total = self._get_web_posts(
                page=page,
                limit=limit,
                url_type=url_type,
                classification=classification,
                search=search,
                date_from=date_from,
                date_to=date_to,
            )
            results.extend(web_posts)
            total += web_total

        # 날짜순 정렬
        results.sort(key=lambda x: x.created_at, reverse=True)

        # 페이징 처리 (통합 후)
        if source_type is None:
            # 통합 조회 시 재정렬 후 페이징
            start = (page - 1) * limit
            end = start + limit
            results = results[start:end]

        return results, total

    def _get_instagram_posts(
        self,
        page: int,
        limit: int,
        url_type: Optional[str],
        classification: Optional[str],
        search: Optional[str],
        date_from: Optional[datetime],
        date_to: Optional[datetime],
        is_active: Optional[bool],
    ) -> Tuple[List[CollectedPostBase], int]:
        """Instagram 게시물 조회."""
        query = self.db.query(InstagramPost)

        # url_type 필터 (instagram 관련만)
        if url_type and not url_type.startswith('instagram'):
            return [], 0

        # 분류 상태 필터
        if classification:
            if classification == 'unclassified':
                query = query.filter(InstagramPost.classified_type.is_(None))
            else:
                query = query.filter(InstagramPost.classified_type == classification)

        # 검색
        if search:
            query = query.filter(
                or_(
                    InstagramPost.caption.ilike(f'%{search}%'),
                    InstagramPost.account.ilike(f'%{search}%'),
                )
            )

        # 날짜 범위
        if date_from:
            query = query.filter(InstagramPost.collected_at >= date_from)
        if date_to:
            query = query.filter(InstagramPost.collected_at <= date_to)

        # 활성 상태
        if is_active is not None:
            query = query.filter(InstagramPost.is_active == is_active)

        total = query.count()

        # 페이징
        posts = (
            query.order_by(desc(InstagramPost.collected_at))
            .offset((page - 1) * limit)
            .limit(limit)
            .all()
        )

        return [self._instagram_to_collected(p) for p in posts], total

    def _get_web_posts(
        self,
        page: int,
        limit: int,
        url_type: Optional[str],
        classification: Optional[str],
        search: Optional[str],
        date_from: Optional[datetime],
        date_to: Optional[datetime],
    ) -> Tuple[List[CollectedPostBase], int]:
        """CrawledPages 조회."""
        query = self.db.query(CrawledPage)

        # url_type 필터 (instagram 제외)
        if url_type:
            if url_type.startswith('instagram'):
                return [], 0
            query = query.filter(CrawledPage.url_type == url_type)
        else:
            # 기본: instagram 제외
            query = query.filter(~CrawledPage.url_type.like('instagram%'))

        # 분류 상태 필터
        if classification:
            if classification == 'unclassified':
                query = query.filter(CrawledPage.is_event.is_(None))
            elif classification == 'event':
                query = query.filter(CrawledPage.is_event == True)
            elif classification == 'popup':
                query = query.filter(CrawledPage.popup_id.isnot(None))
            elif classification == 'uncategorized':
                query = query.filter(CrawledPage.is_event == False)

        # 검색
        if search:
            query = query.filter(
                or_(
                    CrawledPage.title.ilike(f'%{search}%'),
                    CrawledPage.content.ilike(f'%{search}%'),
                    CrawledPage.url.ilike(f'%{search}%'),
                )
            )

        # 날짜 범위
        if date_from:
            query = query.filter(CrawledPage.crawled_at >= date_from)
        if date_to:
            query = query.filter(CrawledPage.crawled_at <= date_to)

        total = query.count()

        # 페이징
        pages = (
            query.order_by(desc(CrawledPage.crawled_at))
            .offset((page - 1) * limit)
            .limit(limit)
            .all()
        )

        return [self._web_to_collected(p) for p in pages], total

    def _instagram_to_collected(self, post: InstagramPost) -> CollectedPostBase:
        """InstagramPost를 CollectedPostBase로 변환."""
        # 캡션에서 제목 추출 (첫 50자)
        title = None
        if post.caption:
            title = post.caption[:50] + ('...' if len(post.caption) > 50 else '')

        # 썸네일 추출
        thumbnail = None
        if post.images and len(post.images) > 0:
            thumbnail = post.images[0].get('src') if isinstance(post.images[0], dict) else post.images[0]

        return CollectedPostBase(
            id=post.id,
            source_type='instagram',
            source_id=post.id,
            title=title,
            content=post.caption,
            thumbnail=thumbnail,
            url=post.url or f'https://instagram.com/p/{post.post_id}',
            url_type='instagram_post',
            created_at=post.collected_at or datetime.now(),
            classification=post.classified_type,
            shortcode=post.post_id,
            account_name=post.account,
            is_active=post.is_active,
            tags=[rel.tag.name for rel in post.tag_relations if rel.tag] if post.tag_relations else [],
        )

    def _web_to_collected(self, page: CrawledPage) -> CollectedPostBase:
        """CrawledPage를 CollectedPostBase로 변환."""
        # 분류 상태 결정
        classification = None
        if page.event_id:
            classification = 'event'
        elif page.popup_id:
            classification = 'popup'
        elif page.is_event is False:
            classification = 'uncategorized'

        return CollectedPostBase(
            id=page.id,
            source_type='web',
            source_id=page.id,
            title=page.title or page.og_title,
            content=page.content or page.description,
            thumbnail=page.og_image,
            url=page.url,
            url_type=page.url_type,
            created_at=page.crawled_at or datetime.now(),
            classification=classification,
            extractor_used=page.extractor_used,
            is_event=page.is_event,
        )

    def get_url_types(self) -> List[str]:
        """사용 가능한 URL 타입 목록 조회."""
        # Instagram 타입
        types = ['instagram_post']

        # Web 타입
        web_types = (
            self.db.query(CrawledPage.url_type)
            .filter(~CrawledPage.url_type.like('instagram%'))
            .distinct()
            .all()
        )
        types.extend([t[0] for t in web_types if t[0]])

        return types
