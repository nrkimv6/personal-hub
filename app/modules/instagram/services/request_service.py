"""Instagram Crawl Request Service - 수동 실행 요청 관리."""

import logging
from datetime import datetime
from typing import List, Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.models import InstagramCrawlRequest

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
            requested_at=datetime.utcnow(),
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
        request.processed_at = datetime.utcnow()
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
