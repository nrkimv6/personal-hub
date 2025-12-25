"""
Universal Crawl 서비스 - 범용 URL 크롤링 요청 관리
"""
import hashlib
import json
import logging
from typing import List, Optional, Tuple
from datetime import datetime

from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.models.universal_crawl import UniversalCrawlRequest, CrawledPage
from app.schemas.universal_crawl import (
    UniversalCrawlRequestCreate,
    UniversalCrawlRequestUpdate,
    UniversalCrawlRequestResponse,
    UniversalCrawlRequestList,
    CrawledPageCreate,
    CrawledPageResponse,
    CrawledPageList,
    CrawlUrlRequest,
    CrawlUrlResponse,
)
from app.services.event_service import detect_url_type

logger = logging.getLogger(__name__)


class UniversalCrawlService:
    """범용 URL 크롤링 서비스"""

    # Instagram URL 패턴
    INSTAGRAM_PATTERNS = [
        "instagram.com/p/",
        "instagram.com/reel/",
        "instagram.com/reels/",
        "instagram.com/stories/",
        "instagr.am/",
    ]

    def is_instagram_url(self, url: str) -> bool:
        """Instagram URL 여부 판단"""
        url_lower = url.lower()
        return any(pattern in url_lower for pattern in self.INSTAGRAM_PATTERNS)

    def create_request(
        self,
        db: Session,
        url: str,
        account_id: Optional[int] = None,
        auto_analyze: bool = True,
        priority: int = 0,
        requested_by: str = "manual",
        extra_metadata: Optional[dict] = None,
    ) -> Tuple[UniversalCrawlRequest, str]:
        """
        크롤링 요청 생성

        Returns:
            Tuple[UniversalCrawlRequest, str]: (요청 객체, 메시지)
        """
        # Instagram URL은 거부 (별도 크롤러 사용)
        if self.is_instagram_url(url):
            raise ValueError("Instagram URL은 Instagram 크롤러를 사용하세요.")

        # URL 타입 자동 감지
        url_type = detect_url_type(url)
        if url_type == "sns":
            url_type = "other"  # SNS 중 Instagram 제외한 것들

        # 요청 생성
        request = UniversalCrawlRequest(
            url=url,
            url_type=url_type,
            account_id=account_id,
            status="pending",
            requested_by=requested_by,
            auto_analyze=auto_analyze,
            priority=priority,
            extra_metadata=json.dumps(extra_metadata) if extra_metadata else None,
        )

        db.add(request)
        db.commit()
        db.refresh(request)

        logger.info(f"크롤링 요청 생성: id={request.id}, url={url}, type={url_type}")
        return request, f"크롤링 요청이 등록되었습니다. (ID: {request.id})"

    def get_pending_requests(
        self,
        db: Session,
        limit: int = 10,
    ) -> List[UniversalCrawlRequest]:
        """대기 중인 요청 조회 (우선순위 순)"""
        return (
            db.query(UniversalCrawlRequest)
            .filter(UniversalCrawlRequest.status == "pending")
            .order_by(
                desc(UniversalCrawlRequest.priority),
                UniversalCrawlRequest.requested_at,
            )
            .limit(limit)
            .all()
        )

    def get_request(
        self,
        db: Session,
        request_id: int,
    ) -> Optional[UniversalCrawlRequest]:
        """요청 상세 조회"""
        return db.query(UniversalCrawlRequest).filter(
            UniversalCrawlRequest.id == request_id
        ).first()

    def get_requests(
        self,
        db: Session,
        status: Optional[str] = None,
        url_type: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> UniversalCrawlRequestList:
        """요청 목록 조회"""
        query = db.query(UniversalCrawlRequest)

        if status:
            query = query.filter(UniversalCrawlRequest.status == status)
        if url_type:
            query = query.filter(UniversalCrawlRequest.url_type == url_type)

        total = query.count()
        total_pages = (total + page_size - 1) // page_size

        items = (
            query.order_by(desc(UniversalCrawlRequest.requested_at))
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

        return UniversalCrawlRequestList(
            items=[UniversalCrawlRequestResponse.model_validate(item) for item in items],
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )

    def update_request_status(
        self,
        db: Session,
        request_id: int,
        status: str,
        error_message: Optional[str] = None,
        crawled_page_id: Optional[int] = None,
    ) -> Optional[UniversalCrawlRequest]:
        """요청 상태 업데이트"""
        request = self.get_request(db, request_id)
        if not request:
            return None

        request.status = status

        if status == "processing":
            request.started_at = datetime.now()
        elif status in ("completed", "failed"):
            request.completed_at = datetime.now()

        if error_message:
            request.error_message = error_message
        if crawled_page_id:
            request.crawled_page_id = crawled_page_id

        db.commit()
        db.refresh(request)

        logger.info(f"요청 상태 업데이트: id={request_id}, status={status}")
        return request

    def mark_processing(
        self,
        db: Session,
        request_id: int,
    ) -> Optional[UniversalCrawlRequest]:
        """요청을 processing 상태로 전환"""
        return self.update_request_status(db, request_id, "processing")

    def mark_completed(
        self,
        db: Session,
        request_id: int,
        crawled_page_id: int,
    ) -> Optional[UniversalCrawlRequest]:
        """요청을 completed 상태로 전환"""
        return self.update_request_status(
            db, request_id, "completed", crawled_page_id=crawled_page_id
        )

    def mark_failed(
        self,
        db: Session,
        request_id: int,
        error_message: str,
    ) -> Optional[UniversalCrawlRequest]:
        """요청을 failed 상태로 전환"""
        request = self.get_request(db, request_id)
        if request:
            request.retry_count += 1
        return self.update_request_status(
            db, request_id, "failed", error_message=error_message
        )

    def retry_request(
        self,
        db: Session,
        request_id: int,
    ) -> Optional[UniversalCrawlRequest]:
        """실패한 요청 재시도"""
        request = self.get_request(db, request_id)
        if not request:
            return None
        if request.status != "failed":
            raise ValueError("실패한 요청만 재시도할 수 있습니다.")

        request.status = "pending"
        request.error_message = None
        request.started_at = None
        request.completed_at = None

        db.commit()
        db.refresh(request)

        logger.info(f"요청 재시도: id={request_id}")
        return request

    # CrawledPage 관련 메서드

    def create_crawled_page(
        self,
        db: Session,
        url: str,
        url_type: str,
        title: Optional[str] = None,
        description: Optional[str] = None,
        content: Optional[str] = None,
        extracted_data: Optional[dict] = None,
        og_title: Optional[str] = None,
        og_description: Optional[str] = None,
        og_image: Optional[str] = None,
        extractor_used: Optional[str] = None,
    ) -> CrawledPage:
        """크롤링 결과 저장"""
        url_hash = hashlib.md5(url.encode()).hexdigest()

        # 중복 체크
        existing = db.query(CrawledPage).filter(CrawledPage.url_hash == url_hash).first()
        if existing:
            # 기존 데이터 업데이트
            existing.title = title or existing.title
            existing.description = description or existing.description
            existing.content = content or existing.content
            existing.extracted_data = json.dumps(extracted_data) if extracted_data else existing.extracted_data
            existing.og_title = og_title or existing.og_title
            existing.og_description = og_description or existing.og_description
            existing.og_image = og_image or existing.og_image
            existing.extractor_used = extractor_used or existing.extractor_used
            existing.crawled_at = datetime.now()

            db.commit()
            db.refresh(existing)
            logger.info(f"크롤링 결과 업데이트: id={existing.id}, url={url}")
            return existing

        # 신규 생성
        page = CrawledPage(
            url=url,
            url_type=url_type,
            title=title,
            description=description,
            content=content,
            extracted_data=json.dumps(extracted_data) if extracted_data else None,
            og_title=og_title,
            og_description=og_description,
            og_image=og_image,
            extractor_used=extractor_used,
            url_hash=url_hash,
        )

        db.add(page)
        db.commit()
        db.refresh(page)

        logger.info(f"크롤링 결과 저장: id={page.id}, url={url}")
        return page

    def get_crawled_page(
        self,
        db: Session,
        page_id: int,
    ) -> Optional[CrawledPage]:
        """크롤링 페이지 상세 조회"""
        return db.query(CrawledPage).filter(CrawledPage.id == page_id).first()

    def get_crawled_pages(
        self,
        db: Session,
        url_type: Optional[str] = None,
        is_event: Optional[bool] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> CrawledPageList:
        """크롤링 페이지 목록 조회"""
        query = db.query(CrawledPage)

        if url_type:
            query = query.filter(CrawledPage.url_type == url_type)
        if is_event is not None:
            query = query.filter(CrawledPage.is_event == is_event)

        total = query.count()
        total_pages = (total + page_size - 1) // page_size

        items = (
            query.order_by(desc(CrawledPage.crawled_at))
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

        return CrawledPageList(
            items=[CrawledPageResponse.model_validate(item) for item in items],
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )

    def update_analysis_result(
        self,
        db: Session,
        page_id: int,
        is_event: bool,
        analysis_result: Optional[dict] = None,
        event_id: Optional[int] = None,
    ) -> Optional[CrawledPage]:
        """AI 분석 결과 업데이트"""
        page = self.get_crawled_page(db, page_id)
        if not page:
            return None

        page.is_event = is_event
        page.analysis_result = json.dumps(analysis_result) if analysis_result else None
        page.event_id = event_id

        db.commit()
        db.refresh(page)

        logger.info(f"분석 결과 업데이트: id={page_id}, is_event={is_event}")
        return page


# 싱글톤 인스턴스
universal_crawl_service = UniversalCrawlService()
