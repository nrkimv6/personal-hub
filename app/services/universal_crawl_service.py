"""
Universal Crawl 서비스 - 범용 URL 크롤링 요청 관리
"""
import hashlib
import json
import logging
from typing import List, Optional, Tuple
from datetime import datetime, date

from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc, asc, or_

from app.models import CrawlRequest
from app.models.universal_crawl import CrawledPage
from app.schemas.universal_crawl import (
    UniversalCrawlRequestResponse,
    UniversalCrawlRequestList,
    CrawledPageResponse,
    CrawledPageList,
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
        service_account_id: Optional[int] = None,
        auto_analyze: bool = True,
        priority: int = 0,
        requested_by: str = "manual",
        extra_metadata: Optional[dict] = None,
    ) -> Tuple[CrawlRequest, str]:
        """
        크롤링 요청 생성

        Returns:
            Tuple[CrawlRequest, str]: (요청 객체, 메시지)
        """
        # Instagram URL은 instagram 타입으로 설정 (ondemand_worker가 처리)
        if self.is_instagram_url(url):
            url_type = "instagram"
        else:
            # URL 타입 자동 감지
            url_type = detect_url_type(url)
            if url_type == "sns":
                url_type = "other"  # SNS 중 Instagram 제외한 것들

        # 요청 생성
        request = CrawlRequest(
            url=url,
            url_type=url_type,
            status=CrawlRequest.STATUS_PENDING,
            requested_by=requested_by,
            requested_at=datetime.now(),
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
    ) -> List[CrawlRequest]:
        """대기 중인 요청 조회"""
        return (
            db.query(CrawlRequest)
            .filter(CrawlRequest.status == CrawlRequest.STATUS_PENDING)
            .order_by(CrawlRequest.requested_at)
            .limit(limit)
            .all()
        )

    def get_request(
        self,
        db: Session,
        request_id: int,
    ) -> Optional[CrawlRequest]:
        """요청 상세 조회"""
        return db.query(CrawlRequest).filter(
            CrawlRequest.id == request_id
        ).first()

    def get_requests(
        self,
        db: Session,
        status: Optional[str] = None,
        url_type: Optional[str] = None,
        analysis_status: Optional[str] = None,
        url_search: Optional[str] = None,
        content_search: Optional[str] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        sort_by: Optional[str] = "requested_at",
        sort_order: Optional[str] = "desc",
        page: int = 1,
        page_size: int = 50,
    ) -> UniversalCrawlRequestList:
        """요청 목록 조회 (필터/정렬 지원)

        Args:
            status: 상태 필터 (pending/processing/completed/failed)
            url_type: URL 타입 필터
            analysis_status: 분석 상태 (event/uncategorized/unanalyzed)
            url_search: URL 검색 (부분 일치)
            content_search: 본문 검색 (부분 일치)
            date_from: 요청일 시작
            date_to: 요청일 종료
            sort_by: 정렬 컬럼
            sort_order: 정렬 순서 (asc/desc)
        """
        query = db.query(CrawlRequest)

        # 기본 필터
        if status:
            query = query.filter(CrawlRequest.status == status)
        if url_type:
            query = query.filter(CrawlRequest.url_type == url_type)

        # URL 검색
        if url_search:
            query = query.filter(CrawlRequest.url.ilike(f"%{url_search}%"))

        # 날짜 범위 필터
        if date_from:
            query = query.filter(CrawlRequest.requested_at >= datetime.combine(date_from, datetime.min.time()))
        if date_to:
            query = query.filter(CrawlRequest.requested_at <= datetime.combine(date_to, datetime.max.time()))

        # 본문 검색 (crawled_page 조인 필요)
        if content_search:
            query = query.join(CrawledPage, CrawlRequest.result_id == CrawledPage.id, isouter=True)
            query = query.filter(CrawlRequest.result_type == "crawled_page")
            query = query.filter(
                or_(
                    CrawledPage.content.ilike(f"%{content_search}%"),
                    CrawledPage.title.ilike(f"%{content_search}%"),
                    CrawledPage.description.ilike(f"%{content_search}%"),
                )
            )

        # 분석 상태 필터
        if analysis_status:
            if not content_search:
                query = query.join(CrawledPage, CrawlRequest.result_id == CrawledPage.id, isouter=True)
                query = query.filter(CrawlRequest.result_type == "crawled_page")

            if analysis_status == "event":
                query = query.filter(CrawledPage.is_event == True)
            elif analysis_status == "uncategorized":
                query = query.filter(CrawledPage.is_event == False)
            elif analysis_status == "unanalyzed":
                query = query.filter(
                    or_(
                        CrawledPage.is_event.is_(None),
                        CrawlRequest.result_id.is_(None),
                    )
                )

        total = query.count()
        total_pages = (total + page_size - 1) // page_size

        # 정렬
        sort_column = getattr(CrawlRequest, sort_by, CrawlRequest.requested_at)
        if sort_order == "asc":
            query = query.order_by(asc(sort_column))
        else:
            query = query.order_by(desc(sort_column))

        items = (
            query.offset((page - 1) * page_size)
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
    ) -> Optional[CrawlRequest]:
        """요청 상태 업데이트"""
        request = self.get_request(db, request_id)
        if not request:
            return None

        request.status = status

        if status == CrawlRequest.STATUS_PROCESSING:
            request.mark_processing()
        elif status == CrawlRequest.STATUS_COMPLETED and crawled_page_id:
            request.mark_completed(result_type="crawled_page", result_id=crawled_page_id)
        elif status == CrawlRequest.STATUS_FAILED:
            request.mark_failed(error_message or "Unknown error")

        db.commit()
        db.refresh(request)

        logger.info(f"요청 상태 업데이트: id={request_id}, status={status}")
        return request

    def mark_processing(
        self,
        db: Session,
        request_id: int,
    ) -> Optional[CrawlRequest]:
        """요청을 processing 상태로 전환"""
        request = self.get_request(db, request_id)
        if not request:
            return None
        request.mark_processing()
        db.commit()
        db.refresh(request)
        return request

    def mark_completed(
        self,
        db: Session,
        request_id: int,
        crawled_page_id: int,
    ) -> Optional[CrawlRequest]:
        """요청을 completed 상태로 전환"""
        request = self.get_request(db, request_id)
        if not request:
            return None
        request.mark_completed(result_type="crawled_page", result_id=crawled_page_id)
        db.commit()
        db.refresh(request)
        return request

    def mark_failed(
        self,
        db: Session,
        request_id: int,
        error_message: str,
    ) -> Optional[CrawlRequest]:
        """요청을 failed 상태로 전환"""
        request = self.get_request(db, request_id)
        if not request:
            return None
        request.retry_count = (request.retry_count or 0) + 1
        request.mark_failed(error_message)
        db.commit()
        db.refresh(request)
        return request

    def retry_request(
        self,
        db: Session,
        request_id: int,
    ) -> Optional[CrawlRequest]:
        """요청 재시도 (실패/완료 상태 모두 가능)"""
        request = self.get_request(db, request_id)
        if not request:
            return None
        if request.status not in (CrawlRequest.STATUS_FAILED, CrawlRequest.STATUS_COMPLETED):
            raise ValueError("실패 또는 완료된 요청만 재시도할 수 있습니다.")

        request.status = CrawlRequest.STATUS_PENDING
        request.error_message = None
        request.picked_at = None
        request.processed_at = None
        request.requested_at = datetime.now()  # 재시도 시간으로 갱신

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
