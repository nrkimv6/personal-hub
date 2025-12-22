"""Instagram Crawl Request Service - 수동 실행 요청 관리."""

import logging
from datetime import datetime
from typing import List, Optional

from sqlalchemy import desc, func
from sqlalchemy.orm import Session, joinedload
from datetime import timedelta

from app.models import InstagramCrawlRequest, InstagramCrawlRun

logger = logging.getLogger("instagram.request_service")


class CrawlRequestService:
    """Instagram 크롤링 요청 관리 서비스."""

    def __init__(self, db: Session):
        """
        Args:
            db: SQLAlchemy 세션
        """
        self.db = db

    def create_request(
        self,
        account_id: int,
        requested_by: str = "manual",
    ) -> InstagramCrawlRequest:
        """크롤링 요청 생성.

        Args:
            account_id: 수집 계정 ID
            requested_by: 요청 출처 ('manual', 'scheduler', 'retry')

        Returns:
            생성된 요청 객체
        """
        # 이미 대기 중인 요청이 있는지 확인
        existing = self.get_pending_request(account_id)
        if existing:
            logger.info(f"Pending request already exists for account {account_id}")
            return existing

        request = InstagramCrawlRequest(
            account_id=account_id,
            requested_by=requested_by,
            status="pending",
            requested_at=datetime.now(),
        )
        self.db.add(request)
        self.db.commit()
        self.db.refresh(request)

        logger.info(f"Created crawl request {request.id} for account {account_id}")
        return request

    def get_pending_request(self, account_id: Optional[int] = None) -> Optional[InstagramCrawlRequest]:
        """대기 중인 요청 조회.

        Args:
            account_id: 특정 계정 필터 (없으면 전체)

        Returns:
            대기 중인 요청, 없으면 None
        """
        query = self.db.query(InstagramCrawlRequest).filter(
            InstagramCrawlRequest.status == "pending"
        )

        if account_id:
            query = query.filter(InstagramCrawlRequest.account_id == account_id)

        return query.order_by(InstagramCrawlRequest.requested_at).first()

    def get_pending_requests(self, limit: int = 10) -> List[InstagramCrawlRequest]:
        """대기 중인 요청 목록 조회.

        Args:
            limit: 조회 개수

        Returns:
            대기 중인 요청 목록
        """
        return (
            self.db.query(InstagramCrawlRequest)
            .filter(InstagramCrawlRequest.status == "pending")
            .order_by(InstagramCrawlRequest.requested_at)
            .limit(limit)
            .all()
        )

    def mark_processing(self, request_id: int) -> Optional[InstagramCrawlRequest]:
        """요청을 처리 중으로 변경.

        Args:
            request_id: 요청 ID

        Returns:
            업데이트된 요청
        """
        request = self.db.query(InstagramCrawlRequest).get(request_id)
        if not request:
            return None

        request.status = "processing"
        request.processed_at = datetime.now()
        self.db.commit()
        self.db.refresh(request)

        return request

    def mark_completed(
        self,
        request_id: int,
        crawl_run_id: int,
    ) -> Optional[InstagramCrawlRequest]:
        """요청을 완료로 변경.

        Args:
            request_id: 요청 ID
            crawl_run_id: 크롤링 실행 ID

        Returns:
            업데이트된 요청
        """
        request = self.db.query(InstagramCrawlRequest).get(request_id)
        if not request:
            return None

        request.status = "completed"
        request.crawl_run_id = crawl_run_id
        self.db.commit()
        self.db.refresh(request)

        logger.info(f"Request {request_id} completed with run {crawl_run_id}")
        return request

    def mark_failed(
        self,
        request_id: int,
        error_message: str,
    ) -> Optional[InstagramCrawlRequest]:
        """요청을 실패로 변경.

        Args:
            request_id: 요청 ID
            error_message: 오류 메시지

        Returns:
            업데이트된 요청
        """
        request = self.db.query(InstagramCrawlRequest).get(request_id)
        if not request:
            return None

        request.status = "failed"
        request.error_message = error_message
        self.db.commit()
        self.db.refresh(request)

        logger.warning(f"Request {request_id} failed: {error_message}")
        return request

    def get_recent_requests(
        self,
        limit: int = 10,
        account_id: Optional[int] = None,
    ) -> List[InstagramCrawlRequest]:
        """최근 요청 목록 조회.

        Args:
            limit: 조회 개수
            account_id: 계정 필터

        Returns:
            최근 요청 목록
        """
        query = self.db.query(InstagramCrawlRequest)

        if account_id:
            query = query.filter(InstagramCrawlRequest.account_id == account_id)

        return (
            query.order_by(desc(InstagramCrawlRequest.requested_at))
            .limit(limit)
            .all()
        )

    def has_active_request(self, account_id: int) -> bool:
        """활성 요청이 있는지 확인.

        Args:
            account_id: 계정 ID

        Returns:
            대기 중 또는 처리 중인 요청이 있으면 True
        """
        return (
            self.db.query(InstagramCrawlRequest)
            .filter(
                InstagramCrawlRequest.account_id == account_id,
                InstagramCrawlRequest.status.in_(["pending", "processing"]),
            )
            .first()
            is not None
        )

    def create_single_post_request(
        self,
        post_id: int,
        account_id: int,
        requested_by: str = "manual",
    ) -> InstagramCrawlRequest:
        """개별 게시물 재크롤링 요청 생성.

        Args:
            post_id: 대상 게시물 ID (instagram_posts.id)
            account_id: 계정 ID
            requested_by: 요청 출처

        Returns:
            생성된 요청 객체
        """
        # 이미 대기 중인 동일 게시물 요청이 있는지 확인
        existing = (
            self.db.query(InstagramCrawlRequest)
            .filter(
                InstagramCrawlRequest.target_post_id == post_id,
                InstagramCrawlRequest.request_type == "single_post",
                InstagramCrawlRequest.status == "pending",
            )
            .first()
        )
        if existing:
            logger.info(f"Pending single_post request already exists for post {post_id}")
            return existing

        request = InstagramCrawlRequest(
            account_id=account_id,
            requested_by=requested_by,
            request_type="single_post",
            target_post_id=post_id,
            status="pending",
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
        account_id: int,
        requested_by: str = "manual",
    ) -> InstagramCrawlRequest:
        """URL로 단일 게시물 수집 요청 생성.

        Args:
            url: Instagram 게시물 URL
            account_id: 계정 ID
            requested_by: 요청 출처

        Returns:
            생성된 요청 객체
        """
        # 이미 대기 중인 동일 URL 요청이 있는지 확인
        existing = (
            self.db.query(InstagramCrawlRequest)
            .filter(
                InstagramCrawlRequest.target_url == url,
                InstagramCrawlRequest.request_type == "single_post_url",
                InstagramCrawlRequest.status == "pending",
            )
            .first()
        )
        if existing:
            logger.info(f"Pending url crawl request already exists for {url}")
            return existing

        request = InstagramCrawlRequest(
            account_id=account_id,
            requested_by=requested_by,
            request_type="single_post_url",
            target_url=url,
            status="pending",
            requested_at=datetime.now(),
        )
        self.db.add(request)
        self.db.commit()
        self.db.refresh(request)

        logger.info(f"Created url crawl request {request.id} for {url}")
        return request

    def get_request_by_id(self, request_id: int) -> Optional[InstagramCrawlRequest]:
        """요청 ID로 조회.

        Args:
            request_id: 요청 ID

        Returns:
            요청 객체 또는 None
        """
        return self.db.query(InstagramCrawlRequest).get(request_id)

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
            self.db.query(InstagramCrawlRequest)
            .filter(
                InstagramCrawlRequest.status == "processing",
                InstagramCrawlRequest.processed_at < cutoff_time,
            )
            .all()
        )

        count = 0
        for request in stale_requests:
            request.status = "failed"
            request.error_message = f"Timeout: processing 상태가 {timeout_minutes}분 초과"
            count += 1
            logger.warning(
                f"Stale request {request.id} marked as failed (processing since {request.processed_at})"
            )

        if count > 0:
            self.db.commit()
            logger.info(f"Cleaned up {count} stale processing request(s)")

        return count

    def get_requests_paginated(
        self,
        page: int = 1,
        limit: int = 20,
        request_type: Optional[str] = None,
        requested_by: Optional[str] = None,
        status: Optional[str] = None,
        period: Optional[str] = None,
        account_id: Optional[int] = None,
    ) -> tuple[List[InstagramCrawlRequest], int]:
        """크롤링 요청 이력 페이징 조회.

        Args:
            page: 페이지 번호 (1부터 시작)
            limit: 페이지당 개수
            request_type: 요청 타입 필터 ('feed', 'single_post', 'single_post_url')
            requested_by: 요청 출처 필터 ('manual', 'scheduler', 'retry')
            status: 상태 필터 ('pending', 'processing', 'completed', 'failed')
            period: 기간 필터 ('today', 'week', 'month')
            account_id: 계정 필터

        Returns:
            (요청 목록, 전체 개수) 튜플
        """
        query = self.db.query(InstagramCrawlRequest)

        # 필터 적용
        if request_type:
            query = query.filter(InstagramCrawlRequest.request_type == request_type)

        if requested_by:
            query = query.filter(InstagramCrawlRequest.requested_by == requested_by)

        if status:
            query = query.filter(InstagramCrawlRequest.status == status)

        if account_id:
            query = query.filter(InstagramCrawlRequest.account_id == account_id)

        if period:
            now = datetime.now()
            if period == "today":
                start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
                query = query.filter(InstagramCrawlRequest.requested_at >= start_of_day)
            elif period == "week":
                week_ago = now - timedelta(days=7)
                query = query.filter(InstagramCrawlRequest.requested_at >= week_ago)
            elif period == "month":
                month_ago = now - timedelta(days=30)
                query = query.filter(InstagramCrawlRequest.requested_at >= month_ago)

        # 전체 개수
        total = query.count()

        # 페이징 적용
        offset = (page - 1) * limit
        requests = (
            query.order_by(desc(InstagramCrawlRequest.requested_at))
            .offset(offset)
            .limit(limit)
            .all()
        )

        return requests, total

    def get_request_with_run(self, request_id: int) -> Optional[dict]:
        """요청과 연결된 CrawlRun 정보를 함께 조회.

        Args:
            request_id: 요청 ID

        Returns:
            요청 정보와 CrawlRun 요약을 포함한 딕셔너리
        """
        request = self.db.query(InstagramCrawlRequest).get(request_id)
        if not request:
            return None

        result = {
            "request": request,
            "crawl_run": None,
        }

        if request.crawl_run_id:
            run = self.db.query(InstagramCrawlRun).get(request.crawl_run_id)
            if run:
                duration = None
                if run.started_at and run.finished_at:
                    duration = int((run.finished_at - run.started_at).total_seconds())

                result["crawl_run"] = {
                    "id": run.id,
                    "total_collected": run.total_collected,
                    "new_saved": run.new_saved,
                    "duration_seconds": duration,
                    "stop_reason": run.stop_reason,
                }

        return result
