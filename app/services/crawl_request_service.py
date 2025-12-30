"""단건 크롤링 요청 서비스."""

from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session

from app.models import CrawlRequest


class CrawlRequestService:
    """단건 크롤링 요청 관리 서비스."""

    def __init__(self, db: Session):
        self.db = db

    def create_request(
        self,
        url: str,
        url_type: str,
        requested_by: str = "manual"
    ) -> CrawlRequest:
        """새 크롤링 요청 생성."""
        request = CrawlRequest(
            url=url,
            url_type=url_type,
            requested_by=requested_by,
            status=CrawlRequest.STATUS_PENDING,
            requested_at=datetime.now()
        )
        self.db.add(request)
        self.db.commit()
        self.db.refresh(request)
        return request

    def get_pending_requests(self, url_type: Optional[str] = None, limit: int = 10) -> list[CrawlRequest]:
        """대기 중인 요청 조회."""
        query = self.db.query(CrawlRequest).filter(
            CrawlRequest.status == CrawlRequest.STATUS_PENDING
        )
        if url_type:
            query = query.filter(CrawlRequest.url_type == url_type)
        return query.order_by(CrawlRequest.requested_at.asc()).limit(limit).all()

    def pick_request(self, request_id: int, worker_id: str) -> Optional[CrawlRequest]:
        """요청을 워커가 가져감으로 표시."""
        request = self.db.query(CrawlRequest).filter(
            CrawlRequest.id == request_id,
            CrawlRequest.status == CrawlRequest.STATUS_PENDING
        ).first()

        if request:
            request.mark_picked(worker_id)
            self.db.commit()
            self.db.refresh(request)
        return request

    def start_processing(self, request_id: int) -> Optional[CrawlRequest]:
        """처리 시작으로 표시."""
        request = self.db.query(CrawlRequest).filter(
            CrawlRequest.id == request_id
        ).first()

        if request:
            request.mark_processing()
            self.db.commit()
            self.db.refresh(request)
        return request

    def complete_request(
        self,
        request_id: int,
        result_type: str,
        result_id: int
    ) -> Optional[CrawlRequest]:
        """요청 완료 처리."""
        request = self.db.query(CrawlRequest).filter(
            CrawlRequest.id == request_id
        ).first()

        if request:
            request.mark_completed(result_type, result_id)
            self.db.commit()
            self.db.refresh(request)
        return request

    def fail_request(
        self,
        request_id: int,
        error_message: str
    ) -> Optional[CrawlRequest]:
        """요청 실패 처리."""
        request = self.db.query(CrawlRequest).filter(
            CrawlRequest.id == request_id
        ).first()

        if request:
            request.mark_failed(error_message)
            self.db.commit()
            self.db.refresh(request)
        return request

    def get_requests_paginated(
        self,
        page: int = 1,
        limit: int = 20,
        url_type: Optional[str] = None,
        status: Optional[str] = None,
        requested_by: Optional[str] = None
    ) -> dict:
        """요청 이력 페이징 조회."""
        query = self.db.query(CrawlRequest)

        if url_type:
            query = query.filter(CrawlRequest.url_type == url_type)
        if status:
            query = query.filter(CrawlRequest.status == status)
        if requested_by:
            query = query.filter(CrawlRequest.requested_by == requested_by)

        total = query.count()
        items = query.order_by(
            CrawlRequest.requested_at.desc()
        ).offset((page - 1) * limit).limit(limit).all()

        return {
            "items": items,
            "total": total,
            "page": page,
            "limit": limit,
            "pages": (total + limit - 1) // limit
        }

    def get_request_by_id(self, request_id: int) -> Optional[CrawlRequest]:
        """ID로 요청 조회."""
        return self.db.query(CrawlRequest).filter(
            CrawlRequest.id == request_id
        ).first()

    def retry_failed_request(self, request_id: int) -> Optional[CrawlRequest]:
        """실패한 요청 재시도."""
        original = self.db.query(CrawlRequest).filter(
            CrawlRequest.id == request_id,
            CrawlRequest.status == CrawlRequest.STATUS_FAILED
        ).first()

        if not original:
            return None

        # 새 요청 생성 (재시도)
        retry_request = CrawlRequest(
            url=original.url,
            url_type=original.url_type,
            requested_by="retry",
            status=CrawlRequest.STATUS_PENDING,
            requested_at=datetime.now(),
            retry_count=original.retry_count + 1
        )
        self.db.add(retry_request)
        self.db.commit()
        self.db.refresh(retry_request)
        return retry_request
