"""수집 관리 서비스."""

from datetime import datetime, timedelta
from typing import Optional, List, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import or_, desc, func

from app.models.instagram_post import InstagramPost
from app.models.universal_crawl import CrawledPage
from app.models import CrawlRequest, TaskScheduleRun, TaskSchedule
from app.modules.claude_worker.models.llm_request import LLMRequest
from app.schemas.collect import CollectedPostBase, CrawlHistoryItem, CrawlHistoryStats


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

        # 통합 조회 시: 각 소스에서 충분한 데이터를 가져와 통합 후 페이징
        # 단일 소스 조회 시: 해당 소스에서 직접 페이징
        is_combined = source_type is None
        fetch_page = 1 if is_combined else page
        fetch_limit = page * limit if is_combined else limit

        # Instagram 게시물 조회
        if source_type is None or source_type == 'instagram':
            ig_posts, ig_total = self._get_instagram_posts(
                page=fetch_page,
                limit=fetch_limit,
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
                page=fetch_page,
                limit=fetch_limit,
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

        # 통합 조회 시에만 재페이징 (단일 소스는 이미 페이징됨)
        if is_combined:
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

        # LLM 상태 조회 (배치)
        post_ids = [p.id for p in posts]
        llm_status_map = self._get_llm_status_batch(post_ids)

        return [self._instagram_to_collected(p, llm_status_map.get(p.id)) for p in posts], total

    def _get_llm_status_batch(self, post_ids: List[int]) -> dict:
        """Instagram 게시물들의 LLM 상태를 배치로 조회."""
        if not post_ids:
            return {}

        # 각 게시물의 최신 LLM 요청 상태 조회 (서브쿼리)
        latest_requests = (
            self.db.query(
                LLMRequest.caller_id,
                LLMRequest.status,
            )
            .filter(
                LLMRequest.caller_type == 'instagram',
                LLMRequest.caller_id.in_([str(pid) for pid in post_ids]),
                LLMRequest.deleted_at.is_(None),
            )
            .order_by(LLMRequest.caller_id, desc(LLMRequest.requested_at))
            .all()
        )

        # caller_id별 첫 번째(최신) 상태만 사용
        status_map = {}
        for caller_id, status in latest_requests:
            pid = int(caller_id)
            if pid not in status_map:
                status_map[pid] = status

        return status_map

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

    def _instagram_to_collected(
        self, post: InstagramPost, llm_status: Optional[str] = None
    ) -> CollectedPostBase:
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
            llm_status=llm_status,
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

    def get_crawl_history(
        self,
        page: int = 1,
        limit: int = 20,
        source_type: Optional[str] = None,
        status: Optional[str] = None,
        period: Optional[str] = None,  # 'today', 'week', 'month', None(전체)
    ) -> Tuple[List[CrawlHistoryItem], int, CrawlHistoryStats]:
        """통합 크롤링 이력 조회.

        crawl_requests와 crawl_schedule_runs를 통합하여 조회합니다.
        """
        results = []
        total = 0

        # 기간 필터 계산
        date_from = None
        if period == 'today':
            date_from = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == 'week':
            date_from = datetime.now() - timedelta(days=7)
        elif period == 'month':
            date_from = datetime.now() - timedelta(days=30)

        # CrawlRequest 조회
        if source_type is None or source_type in ('instagram', 'web'):
            requests, req_total = self._get_crawl_requests(
                page=page,
                limit=limit,
                source_type=source_type,
                status=status,
                date_from=date_from,
            )
            results.extend(requests)
            total += req_total

        # TaskScheduleRun 조회
        if source_type is None or source_type in ('instagram', 'web'):
            runs, run_total = self._get_schedule_runs(
                page=page,
                limit=limit,
                source_type=source_type,
                status=status,
                date_from=date_from,
            )
            results.extend(runs)
            total += run_total

        # 시간순 정렬
        results.sort(key=lambda x: x.started_at, reverse=True)

        # 페이징 처리
        start = (page - 1) * limit
        end = start + limit
        results = results[start:end]

        # 통계 계산
        stats = self._get_history_stats(source_type=source_type, date_from=date_from)

        return results, total, stats

    def _get_crawl_requests(
        self,
        page: int,
        limit: int,
        source_type: Optional[str],
        status: Optional[str],
        date_from: Optional[datetime],
    ) -> Tuple[List[CrawlHistoryItem], int]:
        """CrawlRequest 조회."""
        query = self.db.query(CrawlRequest)

        # source_type 필터
        if source_type == 'instagram':
            query = query.filter(CrawlRequest.url_type.like('instagram%'))
        elif source_type == 'web':
            query = query.filter(~CrawlRequest.url_type.like('instagram%'))

        # status 필터
        if status:
            query = query.filter(CrawlRequest.status == status)

        # 기간 필터
        if date_from:
            query = query.filter(CrawlRequest.requested_at >= date_from)

        total = query.count()

        # 페이징 (통합 정렬을 위해 많이 가져옴)
        requests = (
            query.order_by(desc(CrawlRequest.requested_at))
            .limit(limit * 2)  # 통합 정렬 후 페이징을 위해 여유있게
            .all()
        )

        return [self._request_to_history(r) for r in requests], total

    def _get_schedule_runs(
        self,
        page: int,
        limit: int,
        source_type: Optional[str],
        status: Optional[str],
        date_from: Optional[datetime],
    ) -> Tuple[List[CrawlHistoryItem], int]:
        """TaskScheduleRun 조회."""
        query = self.db.query(TaskScheduleRun).join(TaskSchedule)

        # source_type 필터
        if source_type == 'instagram':
            query = query.filter(TaskSchedule.target_type == 'instagram_feed')
        elif source_type == 'web':
            query = query.filter(TaskSchedule.target_type != 'instagram_feed')

        # status 필터
        if status:
            query = query.filter(TaskScheduleRun.status == status)

        # 기간 필터
        if date_from:
            query = query.filter(TaskScheduleRun.started_at >= date_from)

        total = query.count()

        # 페이징
        runs = (
            query.order_by(desc(TaskScheduleRun.started_at))
            .limit(limit * 2)
            .all()
        )

        return [self._run_to_history(r) for r in runs], total

    def _request_to_history(self, request: CrawlRequest) -> CrawlHistoryItem:
        """CrawlRequest를 CrawlHistoryItem으로 변환."""
        is_instagram = request.url_type.startswith('instagram') if request.url_type else False

        return CrawlHistoryItem(
            id=request.id,
            history_type='request',
            source_type='instagram' if is_instagram else 'web',
            status=request.status,
            started_at=request.requested_at,
            finished_at=request.processed_at,
            duration_seconds=None,  # CrawlRequest는 duration 없음
            error_message=request.error_message,
            url=request.url,
            url_type=request.url_type,
            request_type=self._get_request_type(request),
            requested_by=request.requested_by,
        )

    def _run_to_history(self, run: TaskScheduleRun) -> CrawlHistoryItem:
        """TaskScheduleRun을 CrawlHistoryItem으로 변환."""
        schedule = run.schedule
        is_instagram = schedule.target_type == 'instagram_feed' if schedule else False

        return CrawlHistoryItem(
            id=run.id,
            history_type='schedule_run',
            source_type='instagram' if is_instagram else 'web',
            status=run.status,
            started_at=run.started_at,
            finished_at=run.finished_at,
            duration_seconds=run.duration_seconds,
            error_message=run.error_message,
            schedule_id=run.schedule_id,
            schedule_name=schedule.display_name or schedule.name if schedule else None,
            collected_count=run.collected_count or 0,
            saved_count=run.saved_count or 0,
        )

    def _get_request_type(self, request: CrawlRequest) -> str:
        """CrawlRequest의 타입 판별."""
        if request.url_type and request.url_type.startswith('instagram'):
            if 'feed' in request.url_type:
                return 'feed'
            return 'single_post'
        return 'url'

    def _get_history_stats(
        self,
        source_type: Optional[str],
        date_from: Optional[datetime],
    ) -> CrawlHistoryStats:
        """크롤링 이력 통계 계산."""
        # CrawlRequest 통계
        req_query = self.db.query(CrawlRequest)
        if source_type == 'instagram':
            req_query = req_query.filter(CrawlRequest.url_type.like('instagram%'))
        elif source_type == 'web':
            req_query = req_query.filter(~CrawlRequest.url_type.like('instagram%'))
        if date_from:
            req_query = req_query.filter(CrawlRequest.requested_at >= date_from)

        total = req_query.count()
        completed = req_query.filter(CrawlRequest.status == 'completed').count()
        failed = req_query.filter(CrawlRequest.status == 'failed').count()
        processing = req_query.filter(
            CrawlRequest.status.in_(['pending', 'processing'])
        ).count()

        return CrawlHistoryStats(
            total_requests=total,
            completed_requests=completed,
            failed_requests=failed,
            processing_requests=processing,
        )
