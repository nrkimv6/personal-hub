"""Instagram Crawl Request Service - 수동 실행 요청 관리."""

import logging
from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.models import CrawlRequest, TaskScheduleRun

logger = logging.getLogger("instagram.request_service")

# Instagram URL 타입 상수
URL_TYPE_INSTAGRAM_FEED = "instagram_feed"
URL_TYPE_INSTAGRAM_POST = "instagram_post"
URL_TYPE_INSTAGRAM_ACCOUNT = "instagram_account"
URL_TYPE_INSTAGRAM_HASHTAG = "instagram_hashtag"
URL_TYPE_INSTAGRAM_REELS = "instagram_reels"


class CrawlRequestService:
    """Instagram 크롤링 요청 관리 서비스.

    Note:
        이 서비스는 Instagram 특화 요청을 관리하며,
        내부적으로 공통 CrawlRequest 모델을 사용합니다.
        service_account_id는 URL에 인코딩되어 저장됩니다.
    """

    def __init__(self, db: Session):
        """
        Args:
            db: SQLAlchemy 세션
        """
        self.db = db

    def _make_feed_url(self, service_account_id: int) -> str:
        """피드 크롤링용 가상 URL 생성."""
        return f"instagram://feed?account_id={service_account_id}"

    def _extract_account_id(self, url: str) -> Optional[int]:
        """URL에서 account_id 추출."""
        if url.startswith("instagram://feed?account_id="):
            try:
                return int(url.split("=")[1])
            except (ValueError, IndexError):
                return None
        return None

    def create_request(
        self,
        service_account_id: int,
        requested_by: str = "manual",
        force_create: bool = False,
    ) -> CrawlRequest:
        """크롤링 요청 생성.

        Args:
            service_account_id: 수집 계정 ID
            requested_by: 요청 출처 ('manual', 'scheduler', 'retry')
            force_create: True면 중복 체크 없이 강제 생성 (다중 큐잉 허용)

        Returns:
            생성된 요청 객체
        """
        # 이미 대기 중인 요청이 있는지 확인 (force_create=True면 스킵)
        if not force_create:
            existing = self.get_pending_request(service_account_id)
            if existing:
                logger.info(f"Pending request already exists for account {service_account_id}")
                return existing

        url = self._make_feed_url(service_account_id)
        request = CrawlRequest(
            url=url,
            url_type=URL_TYPE_INSTAGRAM_FEED,
            requested_by=requested_by,
            status=CrawlRequest.STATUS_PENDING,
            requested_at=datetime.now(),
        )
        self.db.add(request)
        self.db.commit()
        self.db.refresh(request)

        logger.info(f"Created crawl request {request.id} for account {service_account_id} (force={force_create})")
        return request

    def get_pending_request(self, service_account_id: Optional[int] = None) -> Optional[CrawlRequest]:
        """대기 중인 요청 조회.

        Args:
            service_account_id: 특정 계정 필터 (없으면 전체 Instagram 요청)

        Returns:
            대기 중인 요청, 없으면 None
        """
        query = self.db.query(CrawlRequest).filter(
            CrawlRequest.status == CrawlRequest.STATUS_PENDING,
            CrawlRequest.url_type.like("instagram%")
        )

        if service_account_id:
            url = self._make_feed_url(service_account_id)
            query = query.filter(CrawlRequest.url == url)

        return query.order_by(CrawlRequest.requested_at).first()

    def get_pending_requests(self, limit: int = 10) -> List[CrawlRequest]:
        """대기 중인 요청 목록 조회.

        Args:
            limit: 조회 개수

        Returns:
            대기 중인 요청 목록
        """
        return (
            self.db.query(CrawlRequest)
            .filter(
                CrawlRequest.status == CrawlRequest.STATUS_PENDING,
                CrawlRequest.url_type.like("instagram%")
            )
            .order_by(CrawlRequest.requested_at)
            .limit(limit)
            .all()
        )

    def mark_processing(self, request_id: int) -> Optional[CrawlRequest]:
        """요청을 처리 중으로 변경.

        Args:
            request_id: 요청 ID

        Returns:
            업데이트된 요청
        """
        request = self.db.query(CrawlRequest).filter(CrawlRequest.id == request_id).first()
        if not request:
            return None

        request.mark_processing()
        self.db.commit()
        self.db.refresh(request)

        return request

    def mark_completed(
        self,
        request_id: int,
        crawl_run_id: int,
    ) -> Optional[CrawlRequest]:
        """요청을 완료로 변경.

        Args:
            request_id: 요청 ID
            crawl_run_id: 크롤링 실행 ID (TaskScheduleRun.id)

        Returns:
            업데이트된 요청
        """
        request = self.db.query(CrawlRequest).filter(CrawlRequest.id == request_id).first()
        if not request:
            return None

        request.mark_completed(result_type="crawl_schedule_run", result_id=crawl_run_id)
        self.db.commit()
        self.db.refresh(request)

        logger.info(f"Request {request_id} completed with run {crawl_run_id}")
        return request

    def mark_failed(
        self,
        request_id: int,
        error_message: str,
    ) -> Optional[CrawlRequest]:
        """요청을 실패로 변경.

        Args:
            request_id: 요청 ID
            error_message: 오류 메시지

        Returns:
            업데이트된 요청
        """
        request = self.db.query(CrawlRequest).filter(CrawlRequest.id == request_id).first()
        if not request:
            return None

        request.mark_failed(error_message)
        self.db.commit()
        self.db.refresh(request)

        logger.warning(f"Request {request_id} failed: {error_message}")
        return request

    def get_recent_requests(
        self,
        limit: int = 10,
        service_account_id: Optional[int] = None,
    ) -> List[CrawlRequest]:
        """최근 요청 목록 조회.

        Args:
            limit: 조회 개수
            service_account_id: 계정 필터

        Returns:
            최근 요청 목록
        """
        query = self.db.query(CrawlRequest).filter(
            CrawlRequest.url_type.like("instagram%")
        )

        if service_account_id:
            url = self._make_feed_url(service_account_id)
            query = query.filter(CrawlRequest.url == url)

        return (
            query.order_by(desc(CrawlRequest.requested_at))
            .limit(limit)
            .all()
        )

    def has_active_request(self, service_account_id: int) -> bool:
        """활성 요청이 있는지 확인.

        Args:
            service_account_id: 계정 ID

        Returns:
            대기 중 또는 처리 중인 요청이 있으면 True
        """
        url = self._make_feed_url(service_account_id)
        return (
            self.db.query(CrawlRequest)
            .filter(
                CrawlRequest.url == url,
                CrawlRequest.status.in_([
                    CrawlRequest.STATUS_PENDING,
                    CrawlRequest.STATUS_PICKED,
                    CrawlRequest.STATUS_PROCESSING
                ]),
            )
            .first()
            is not None
        )

    def get_pending_by_url(self, url: str) -> Optional[CrawlRequest]:
        """URL로 대기 중인 요청 조회.

        배치 URL 크롤링 시 중복 체크용으로 사용합니다.

        Args:
            url: Instagram URL

        Returns:
            대기 중인 요청, 없으면 None
        """
        return (
            self.db.query(CrawlRequest)
            .filter(
                CrawlRequest.url == url,
                CrawlRequest.status == CrawlRequest.STATUS_PENDING,
            )
            .first()
        )

    def create_single_post_request(
        self,
        post_id: int,
        service_account_id: int,
        requested_by: str = "manual",
    ) -> CrawlRequest:
        """개별 게시물 재크롤링 요청 생성.

        Args:
            post_id: 대상 게시물 ID (instagram_posts.id)
            service_account_id: 계정 ID
            requested_by: 요청 출처

        Returns:
            생성된 요청 객체
        """
        url = f"instagram://post/{post_id}?account_id={service_account_id}"

        # 이미 대기 중인 동일 게시물 요청이 있는지 확인
        existing = (
            self.db.query(CrawlRequest)
            .filter(
                CrawlRequest.url == url,
                CrawlRequest.status == CrawlRequest.STATUS_PENDING,
            )
            .first()
        )
        if existing:
            logger.info(f"Pending single_post request already exists for post {post_id}")
            return existing

        request = CrawlRequest(
            url=url,
            url_type=URL_TYPE_INSTAGRAM_POST,
            requested_by=requested_by,
            status=CrawlRequest.STATUS_PENDING,
            requested_at=datetime.now(),
        )
        self.db.add(request)
        self.db.commit()
        self.db.refresh(request)

        logger.info(f"Created single_post request {request.id} for post {post_id}")
        return request

    def create_url_crawl_request(
        self,
        url: str,
        service_account_id: int,
        requested_by: str = "manual",
    ) -> CrawlRequest:
        """URL로 단일 게시물 수집 요청 생성.

        Args:
            url: Instagram 게시물 URL
            service_account_id: 계정 ID
            requested_by: 요청 출처

        Returns:
            생성된 요청 객체
        """
        # 이미 대기 중인 동일 URL 요청이 있는지 확인
        existing = (
            self.db.query(CrawlRequest)
            .filter(
                CrawlRequest.url == url,
                CrawlRequest.status == CrawlRequest.STATUS_PENDING,
            )
            .first()
        )
        if existing:
            logger.info(f"Pending url crawl request already exists for {url}")
            return existing

        request = CrawlRequest(
            url=url,
            url_type=URL_TYPE_INSTAGRAM_POST,
            requested_by=requested_by,
            status=CrawlRequest.STATUS_PENDING,
            requested_at=datetime.now(),
        )
        self.db.add(request)
        self.db.commit()
        self.db.refresh(request)

        logger.info(f"Created url crawl request {request.id} for {url}")
        return request

    def create_generic_url_crawl_request(
        self,
        url: str,
        url_type: str,
        service_account_id: int,
        max_posts: int = 20,
        scroll_count: int = 3,
        requested_by: str = "manual",
    ) -> CrawlRequest:
        """범용 URL 크롤링 요청 생성.

        계정 피드, 해시태그, 릴스 탐색 등 다양한 URL 타입을 지원합니다.

        Args:
            url: Instagram URL
            url_type: URL 타입 (account_profile, account_reels, hashtag 등)
            service_account_id: 계정 ID
            max_posts: 최대 수집 게시물 수
            scroll_count: 스크롤 횟수
            requested_by: 요청 출처

        Returns:
            생성된 요청 객체
        """
        # 이미 대기 중인 동일 URL 요청이 있는지 확인
        existing = (
            self.db.query(CrawlRequest)
            .filter(
                CrawlRequest.url == url,
                CrawlRequest.status == CrawlRequest.STATUS_PENDING,
            )
            .first()
        )
        if existing:
            logger.info(f"Pending url crawl request already exists for {url}")
            return existing

        # url_type에 따라 CrawlRequest.url_type 결정
        url_type_map = {
            "single_post": URL_TYPE_INSTAGRAM_POST,
            "single_reel": URL_TYPE_INSTAGRAM_POST,
            "account_profile": URL_TYPE_INSTAGRAM_ACCOUNT,
            "account_reels": URL_TYPE_INSTAGRAM_REELS,
            "hashtag": URL_TYPE_INSTAGRAM_HASHTAG,
            "reels_explore": URL_TYPE_INSTAGRAM_REELS,
        }
        crawl_url_type = url_type_map.get(url_type, URL_TYPE_INSTAGRAM_POST)

        request = CrawlRequest(
            url=url,
            url_type=crawl_url_type,
            requested_by=requested_by,
            status=CrawlRequest.STATUS_PENDING,
            requested_at=datetime.now(),
        )
        self.db.add(request)
        self.db.commit()
        self.db.refresh(request)

        logger.info(f"Created generic url crawl request {request.id} for {url} (type={url_type})")
        return request

    def get_request_by_id(self, request_id: int) -> Optional[CrawlRequest]:
        """요청 ID로 조회.

        Args:
            request_id: 요청 ID

        Returns:
            요청 객체 또는 None
        """
        return self.db.query(CrawlRequest).filter(CrawlRequest.id == request_id).first()

    def cleanup_stale_processing_requests(self, timeout_minutes: int = 30) -> int:
        """오래된 processing 상태 요청을 timeout 처리.

        워커가 크롤링 중 비정상 종료되면 요청이 processing 상태로 남을 수 있음.
        워커 시작 시 이러한 좀비 요청을 정리합니다.

        Args:
            timeout_minutes: processing 상태 유지 시간 제한 (기본 30분)

        Returns:
            정리된 요청 수
        """
        cutoff_time = datetime.now() - timedelta(minutes=timeout_minutes)

        stale_requests = (
            self.db.query(CrawlRequest)
            .filter(
                CrawlRequest.url_type.like("instagram%"),
                CrawlRequest.status.in_([
                    CrawlRequest.STATUS_PROCESSING,
                    CrawlRequest.STATUS_PICKED
                ]),
                CrawlRequest.picked_at < cutoff_time,
            )
            .all()
        )

        count = 0
        for request in stale_requests:
            request.mark_failed(f"Timeout: {request.status} 상태가 {timeout_minutes}분 초과")
            count += 1
            logger.warning(
                f"Stale request {request.id} marked as failed (status={request.status} since {request.picked_at})"
            )

        if count > 0:
            self.db.commit()
            logger.info(f"Cleaned up {count} stale processing request(s)")

        return count

    def cleanup_stale_pending_requests(self, timeout_minutes: int = 60) -> int:
        """오래된 pending 상태 요청을 timeout 처리.

        워커가 요청을 처리하지 못하고 오래 대기 중인 경우 타임아웃 처리합니다.

        Args:
            timeout_minutes: pending 상태 유지 시간 제한 (기본 60분)

        Returns:
            정리된 요청 수
        """
        cutoff_time = datetime.now() - timedelta(minutes=timeout_minutes)

        stale_requests = (
            self.db.query(CrawlRequest)
            .filter(
                CrawlRequest.url_type.like("instagram%"),
                CrawlRequest.status == CrawlRequest.STATUS_PENDING,
                CrawlRequest.requested_at < cutoff_time,
            )
            .all()
        )

        count = 0
        for request in stale_requests:
            request.mark_failed(f"Timeout: pending 상태가 {timeout_minutes}분 초과 (워커 미처리)")
            count += 1
            logger.warning(
                f"Stale pending request {request.id} marked as failed (pending since {request.requested_at})"
            )

        if count > 0:
            self.db.commit()
            logger.info(f"Cleaned up {count} stale pending request(s)")

        return count

    def get_requests_paginated(
        self,
        page: int = 1,
        limit: int = 20,
        request_type: Optional[str] = None,
        requested_by: Optional[str] = None,
        status: Optional[str] = None,
        period: Optional[str] = None,
        service_account_id: Optional[int] = None,
    ) -> tuple[List[CrawlRequest], int]:
        """크롤링 요청 이력 페이징 조회.

        Args:
            page: 페이지 번호 (1부터 시작)
            limit: 페이지당 개수
            request_type: 요청 타입 필터 (url_type으로 매핑됨)
            requested_by: 요청 출처 필터 ('manual', 'scheduler', 'retry')
            status: 상태 필터 ('pending', 'processing', 'completed', 'failed')
            period: 기간 필터 ('today', 'week', 'month')
            service_account_id: 계정 필터 (현재는 URL 기반 필터링)

        Returns:
            (요청 목록, 전체 개수) 튜플
        """
        query = self.db.query(CrawlRequest).filter(
            CrawlRequest.url_type.like("instagram%")
        )

        # request_type을 url_type으로 변환
        if request_type:
            type_map = {
                "feed": URL_TYPE_INSTAGRAM_FEED,
                "single_post": URL_TYPE_INSTAGRAM_POST,
                "single_post_url": URL_TYPE_INSTAGRAM_POST,
                "account_feed": URL_TYPE_INSTAGRAM_ACCOUNT,
                "hashtag": URL_TYPE_INSTAGRAM_HASHTAG,
            }
            url_type = type_map.get(request_type, request_type)
            query = query.filter(CrawlRequest.url_type == url_type)

        if requested_by:
            query = query.filter(CrawlRequest.requested_by == requested_by)

        if status:
            query = query.filter(CrawlRequest.status == status)

        if service_account_id:
            # URL에 account_id가 포함된 요청 필터
            query = query.filter(
                CrawlRequest.url.like(f"%account_id={service_account_id}%")
            )

        if period:
            now = datetime.now()
            if period == "today":
                start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
                query = query.filter(CrawlRequest.requested_at >= start_of_day)
            elif period == "week":
                week_ago = now - timedelta(days=7)
                query = query.filter(CrawlRequest.requested_at >= week_ago)
            elif period == "month":
                month_ago = now - timedelta(days=30)
                query = query.filter(CrawlRequest.requested_at >= month_ago)

        # 전체 개수
        total = query.count()

        # 페이징 적용
        offset = (page - 1) * limit
        requests = (
            query.order_by(desc(CrawlRequest.requested_at))
            .offset(offset)
            .limit(limit)
            .all()
        )

        return requests, total

    def get_request_with_run(self, request_id: int) -> Optional[dict]:
        """요청과 연결된 TaskScheduleRun 정보를 함께 조회.

        Args:
            request_id: 요청 ID

        Returns:
            요청 정보와 TaskScheduleRun 요약을 포함한 딕셔너리
        """
        request = self.db.query(CrawlRequest).filter(CrawlRequest.id == request_id).first()
        if not request:
            return None

        result = {
            "request": request,
            "crawl_run": None,
        }

        if request.result_id and request.result_type == "crawl_schedule_run":
            run = self.db.query(TaskScheduleRun).filter(
                TaskScheduleRun.id == request.result_id
            ).first()
            if run:
                duration = run.duration_seconds

                result["crawl_run"] = {
                    "id": run.id,
                    "total_collected": run.collected_count,
                    "new_saved": run.saved_count,
                    "duration_seconds": duration,
                    "stop_reason": run.stop_reason,
                }

        return result
