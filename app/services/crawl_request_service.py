"""단건 크롤링 요청 서비스."""

import logging
from datetime import datetime, timedelta
from typing import Optional, List
from sqlalchemy.orm import Session

from app.models import CrawlRequest
from app.shared.redis import RedisClient, RedisQueue
from app.shared.redis.queue import CRAWL_REQUEST_QUEUE

logger = logging.getLogger(__name__)


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
        """새 크롤링 요청 생성 (동기 버전 - SQLite 폴링 모드).

        Redis가 활성화된 경우 create_request_async를 사용해야 합니다.
        """
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

    async def create_request_async(
        self,
        url: str,
        url_type: str,
        requested_by: str = "api"
    ) -> CrawlRequest:
        """새 크롤링 요청 생성 (비동기 버전 - Redis 큐 지원).

        Redis가 활성화되어 있으면 Redis 큐에 추가하고,
        그렇지 않으면 SQLite pending 상태로 저장합니다.

        Args:
            url: 크롤링할 URL
            url_type: URL 타입 (instagram, naver_blog 등)
            requested_by: 요청 출처 (api, manual, retry)

        Returns:
            CrawlRequest: 생성된 요청 객체
        """
        # 1. DB에 로그 저장
        request = CrawlRequest(
            url=url,
            url_type=url_type,
            requested_by=requested_by,
            status=CrawlRequest.STATUS_QUEUED,  # 일단 queued로 설정
            requested_at=datetime.now()
        )
        self.db.add(request)
        self.db.commit()
        self.db.refresh(request)

        # 2. Redis 큐에 추가 시도
        redis_client = await RedisClient.get_client()
        if redis_client:
            queue = RedisQueue(redis_client, CRAWL_REQUEST_QUEUE)
            success = await queue.push({
                "id": request.id,
                "url": url,
                "url_type": url_type,
                "requested_by": requested_by,
                "created_at": request.requested_at,
            })

            if success:
                logger.debug(f"Redis 큐에 요청 추가: id={request.id}, url={url}")
            else:
                # Redis push 실패 → SQLite fallback
                logger.warning(f"Redis push 실패, SQLite fallback: id={request.id}")
                request.status = CrawlRequest.STATUS_PENDING
                self.db.commit()
        else:
            # Redis 미연결 → SQLite fallback
            logger.debug(f"Redis 미연결, SQLite 폴링 모드: id={request.id}")
            request.status = CrawlRequest.STATUS_PENDING
            self.db.commit()

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
        """실패한 요청 재시도 (동기 버전)."""
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

    async def retry_failed_request_async(self, request_id: int) -> Optional[CrawlRequest]:
        """실패한 요청 재시도 (비동기 버전 - Redis 큐 지원)."""
        original = self.db.query(CrawlRequest).filter(
            CrawlRequest.id == request_id,
            CrawlRequest.status == CrawlRequest.STATUS_FAILED
        ).first()

        if not original:
            return None

        # create_request_async를 사용하여 Redis 큐에도 추가
        return await self.create_request_async(
            url=original.url,
            url_type=original.url_type,
            requested_by="retry"
        )

    def cleanup_stale_processing(self, timeout_minutes: int = 30) -> int:
        """오래된 processing/picked 상태 요청을 failed로 정리.

        워커가 비정상 종료되면 요청이 processing 상태로 남을 수 있음.

        Args:
            timeout_minutes: 상태 유지 시간 제한

        Returns:
            정리된 요청 수
        """
        cutoff = datetime.now() - timedelta(minutes=timeout_minutes)

        stale_requests = self.db.query(CrawlRequest).filter(
            CrawlRequest.status.in_([
                CrawlRequest.STATUS_PROCESSING,
                CrawlRequest.STATUS_PICKED
            ]),
            CrawlRequest.picked_at < cutoff
        ).all()

        count = 0
        for request in stale_requests:
            request.mark_failed(f"Timeout: {request.status} 상태가 {timeout_minutes}분 초과")
            count += 1

        if count > 0:
            self.db.commit()

        return count

    def has_pending_for_url(self, url: str) -> bool:
        """동일 URL에 대한 pending 요청이 있는지 확인."""
        return self.db.query(CrawlRequest).filter(
            CrawlRequest.url == url,
            CrawlRequest.status == CrawlRequest.STATUS_PENDING
        ).first() is not None

    def get_active_requests(self, url_type: Optional[str] = None) -> List[CrawlRequest]:
        """활성 상태(pending, picked, processing) 요청 조회."""
        query = self.db.query(CrawlRequest).filter(
            CrawlRequest.status.in_([
                CrawlRequest.STATUS_PENDING,
                CrawlRequest.STATUS_PICKED,
                CrawlRequest.STATUS_PROCESSING
            ])
        )
        if url_type:
            query = query.filter(CrawlRequest.url_type == url_type)
        return query.order_by(CrawlRequest.requested_at.asc()).all()
