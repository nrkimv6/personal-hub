"""
Event 서비스 - 독립 이벤트 CRUD 및 관리
"""
import asyncio
import logging
from typing import List, Optional, Tuple, Dict, Any
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session
from sqlalchemy import or_, and_, func

from app.models.event import Event
from app.models.instagram_post import InstagramPost
from app.schemas.event import (
    EventCreate,
    EventUpdate,
    EventResponse,
    EventList,
    EventImportFromInstagram,
    EventImportFromUrl,
    EventImportFromUrlResponse,
)

logger = logging.getLogger(__name__)


def detect_url_type(url: str) -> str:
    """URL 타입 자동 분류"""
    if not url:
        return "other"

    url_lower = url.lower()

    patterns = {
        "google_form": ["forms.gle", "docs.google.com/forms"],
        "naver_form": ["naver.me", "form.naver.com", "survey.naver.com"],
        "survey": ["surveymonkey.com", "typeform.com", "sthp.kr/survey"],
        "sns": ["instagram.com", "twitter.com", "facebook.com", "x.com"],
    }

    for url_type, keywords in patterns.items():
        if any(kw in url_lower for kw in keywords):
            return url_type

    # shop 키워드 체크
    if any(kw in url_lower for kw in ["shop", "store", "mall", "buy", "order"]):
        return "shop"

    return "other"


class EventService:
    """이벤트 서비스"""

    def get_deadline_counts(
        self,
        db: Session,
        days: int = 6,
        event_type: Optional[str] = None,
    ) -> Dict[str, int]:
        """오늘부터 N일간 각 날짜별 마감 이벤트 개수 조회.

        Args:
            db: DB 세션
            days: 조회할 일수 (기본 6일)
            event_type: 이벤트 유형 필터 (optional)

        Returns:
            { "2025-12-25": 3, "2025-12-26": 5, ... }
        """
        today = date.today()
        result = {}

        for i in range(days):
            target_date = today + timedelta(days=i)
            date_str = target_date.strftime("%Y-%m-%d")

            query = db.query(func.count(Event.id)).filter(Event.event_end == target_date)

            if event_type:
                query = query.filter(Event.event_type == event_type)

            count = query.scalar() or 0
            result[date_str] = count

        return result

    def get_events(
        self,
        db: Session,
        event_type: Optional[str] = None,
        status: Optional[str] = None,
        event_status: Optional[str] = None,  # ongoing/upcoming/ended
        deadline_date: Optional[str] = None,  # YYYY-MM-DD 형식, 특정 마감일
        source_type: Optional[str] = None,
        url_type: Optional[str] = None,
        is_bookmarked: Optional[bool] = None,
        is_participated: Optional[bool] = None,
        is_offline: Optional[bool] = None,  # 오프라인 이벤트 필터
        unknown_period_filter: str = "include",  # exclude/include/only
        search: Optional[str] = None,
        sort_by: str = "event_end",
        sort_order: str = "asc",
        page: int = 1,
        page_size: int = 50,
    ) -> EventList:
        """이벤트 목록 조회 (필터/정렬/페이지네이션)"""
        query = db.query(Event)

        # 검색어 필터 (LIKE) - body_text 포함
        if search:
            search_pattern = f"%{search}%"
            query = query.filter(
                or_(
                    Event.title.ilike(search_pattern),
                    Event.summary.ilike(search_pattern),
                    Event.organizer.ilike(search_pattern),
                    Event.body_text.ilike(search_pattern),
                )
            )

        # 기본 필터
        if event_type:
            query = query.filter(Event.event_type == event_type)
        if status:
            query = query.filter(Event.status == status)
        if source_type:
            query = query.filter(Event.source_type == source_type)
        if url_type:
            query = query.filter(Event.url_type == url_type)
        if is_bookmarked is not None:
            query = query.filter(Event.is_bookmarked == is_bookmarked)
        if is_participated is not None:
            query = query.filter(Event.is_participated == is_participated)
        if is_offline is not None:
            query = query.filter(Event.is_offline == is_offline)

        # unknown_period_filter 처리 (exclude/include/only)
        today = date.today()
        include_unknown = unknown_period_filter in ("include", "only")

        # only: 기간미정만 보기 (시작일과 종료일 모두 NULL)
        if unknown_period_filter == "only":
            query = query.filter(
                and_(Event.event_start.is_(None), Event.event_end.is_(None))
            )
        elif unknown_period_filter == "exclude":
            # exclude: 기간미정 제외 (종료일이 있는 것만)
            query = query.filter(Event.event_end.isnot(None))

        # event_status 필터 (기간 기반) - only가 아닐 때만 적용
        if event_status and unknown_period_filter != "only":
            # cancelled 상태는 별도 처리 (ongoing/upcoming/ended와 배타적)
            if event_status != "cancelled":
                query = query.filter(Event.status != "cancelled")

            # 조기종료(status="ended") 일괄 처리: ended 필터가 아니면 제외
            if event_status not in ("ended", "cancelled"):
                query = query.filter(Event.status != "ended")

            if event_status == "ongoing":
                # 진행 중: 시작일 <= 오늘 AND (종료일 >= 오늘 OR 종료일 NULL)
                conditions = [
                    and_(
                        or_(Event.event_start <= today, Event.event_start.is_(None)),
                        or_(Event.event_end >= today, Event.event_end.is_(None) if include_unknown else False),
                    )
                ]
                if include_unknown:
                    conditions.append(
                        and_(Event.event_start.is_(None), Event.event_end.is_(None))
                    )
                query = query.filter(or_(*conditions))

            elif event_status == "upcoming":
                # 예정: 시작일 > 오늘
                query = query.filter(Event.event_start > today)

            elif event_status == "ended":
                # 종료: 종료일 < 오늘 OR 조기종료(status="ended")
                query = query.filter(
                    or_(Event.event_end < today, Event.status == "ended")
                )

            elif event_status == "ongoing_or_upcoming":
                # 진행 중 + 예정: 종료일 >= 오늘 OR 종료일 NULL
                conditions = [Event.event_end >= today]
                if include_unknown:
                    conditions.append(Event.event_end.is_(None))
                query = query.filter(or_(*conditions))

            elif event_status == "ending_today":
                # 오늘 마감: 종료일 == 오늘
                query = query.filter(Event.event_end == today)

            elif event_status == "ending_tomorrow":
                # 내일까지 마감: 오늘 <= 종료일 <= 내일
                tomorrow = today + timedelta(days=1)
                query = query.filter(
                    Event.event_end >= today,
                    Event.event_end <= tomorrow
                )

        # deadline_date 필터 (특정 날짜 마감)
        if deadline_date:
            from datetime import datetime
            try:
                target_date = datetime.strptime(deadline_date, "%Y-%m-%d").date()
                query = query.filter(Event.event_end == target_date)
            except ValueError:
                logger.warning(f"Invalid deadline_date format: {deadline_date}")

        # 총 개수
        total = query.count()

        # 정렬 (1순위: sort_by, 2순위: event_end일 경우 winner_count desc)
        sort_column = getattr(Event, sort_by, Event.event_end)
        if sort_order == "desc":
            primary_order = sort_column.desc().nullslast()
        else:
            primary_order = sort_column.asc().nullslast()

        # 2차 정렬: 마감일 기준일 때 당첨자수 내림차순 추가
        if sort_by == "event_end":
            query = query.order_by(primary_order, Event.winner_count.desc().nullslast())
        else:
            query = query.order_by(primary_order)

        # 페이지네이션
        offset = (page - 1) * page_size
        events = query.offset(offset).limit(page_size).all()

        # Response 변환 (Instagram 출처 정보 포함)
        items = []
        for event in events:
            response = self._to_response(db, event)
            items.append(response)

        total_pages = (total + page_size - 1) // page_size

        return EventList(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )

    def get_event(self, db: Session, event_id: int) -> Optional[EventResponse]:
        """단일 이벤트 조회"""
        event = db.query(Event).filter(Event.id == event_id).first()
        if not event:
            return None
        return self._to_response(db, event)

    def create_event(self, db: Session, data: EventCreate) -> EventResponse:
        """이벤트 생성"""
        # URL 타입 자동 분류
        url_type = data.url_type or detect_url_type(data.event_url)

        event = Event(
            title=data.title,
            event_type=data.event_type,
            event_url=data.event_url,
            url_type=url_type,
            additional_urls=data.additional_urls,
            event_start=data.event_start,
            event_end=data.event_end,
            announcement_date=data.announcement_date,
            organizer=data.organizer,
            summary=data.summary,
            body_text=data.body_text,
            prizes=data.prizes,
            winner_count=data.winner_count,
            purchase_required=data.purchase_required,
            location_venue=data.location_venue,
            location_address=data.location_address,
            source_type=data.source_type,
            source_instagram_post_id=data.source_instagram_post_id,
            source_url=data.source_url,
            source_note=data.source_note,
            user_note=data.user_note,
            input_source=data.input_source,
            is_offline=data.is_offline,
        )

        db.add(event)
        db.commit()
        db.refresh(event)

        return self._to_response(db, event)

    def update_event(
        self, db: Session, event_id: int, data: EventUpdate
    ) -> Optional[EventResponse]:
        """이벤트 수정"""
        event = db.query(Event).filter(Event.id == event_id).first()
        if not event:
            return None

        update_data = data.model_dump(exclude_unset=True)

        # URL이 변경되면 url_type 재분류
        if "event_url" in update_data and "url_type" not in update_data:
            update_data["url_type"] = detect_url_type(update_data["event_url"])

        # AI가 생성한 이벤트를 수정하면 'ai_edited'로 변경
        if event.input_source == "ai" and "input_source" not in update_data:
            update_data["input_source"] = "ai_edited"

        for field, value in update_data.items():
            setattr(event, field, value)

        db.commit()
        db.refresh(event)

        return self._to_response(db, event)

    def delete_event(self, db: Session, event_id: int) -> bool:
        """이벤트 삭제"""
        event = db.query(Event).filter(Event.id == event_id).first()
        if not event:
            return False

        db.delete(event)
        db.commit()
        return True

    def toggle_bookmark(self, db: Session, event_id: int) -> Optional[EventResponse]:
        """북마크 토글"""
        event = db.query(Event).filter(Event.id == event_id).first()
        if not event:
            return None

        event.is_bookmarked = not event.is_bookmarked
        db.commit()
        db.refresh(event)

        return self._to_response(db, event)

    def toggle_participated(self, db: Session, event_id: int) -> Optional[EventResponse]:
        """참여 완료 토글"""
        event = db.query(Event).filter(Event.id == event_id).first()
        if not event:
            return None

        event.is_participated = not event.is_participated
        db.commit()
        db.refresh(event)

        return self._to_response(db, event)

    def toggle_offline(self, db: Session, event_id: int) -> Optional[dict]:
        """오프라인 상태 토글"""
        event = db.query(Event).filter(Event.id == event_id).first()
        if not event:
            return None

        event.is_offline = not event.is_offline
        db.commit()
        db.refresh(event)

        return {
            "id": event.id,
            "is_offline": event.is_offline,
            "message": f"{'오프라인' if event.is_offline else '온라인'} 이벤트로 변경되었습니다"
        }

    def import_from_instagram(
        self, db: Session, data: EventImportFromInstagram
    ) -> Optional[EventResponse]:
        """Instagram 게시물에서 이벤트 생성.

        Note: llm_* 필드가 제거되었으므로 기본 정보만으로 이벤트를 생성합니다.
        LLM 분석 결과는 claude_worker가 직접 Event 테이블에 저장합니다.
        """
        post = db.query(InstagramPost).filter(InstagramPost.id == data.instagram_post_id).first()
        if not post:
            return None

        # 이미 연결된 이벤트가 있는지 확인
        existing = db.query(Event).filter(
            Event.source_instagram_post_id == data.instagram_post_id
        ).first()
        if existing:
            return self._to_response(db, existing)

        # 기본 이벤트 생성 (LLM 분석 데이터는 별도로 업데이트됨)
        event = Event(
            title=data.title or f"{post.account}의 이벤트",
            event_type="event",
            url_type="other",
            additional_urls=[],
            prizes=[],
            body_text=post.caption,  # Instagram caption을 body_text로 저장
            source_type="instagram",
            source_instagram_post_id=post.id,
            source_url=post.url,
        )

        db.add(event)
        db.commit()
        db.refresh(event)

        return self._to_response(db, event)

    def check_duplicate_url(self, db: Session, event_url: str, exclude_id: Optional[int] = None) -> Optional[Event]:
        """동일 URL로 등록된 이벤트 확인"""
        query = db.query(Event).filter(Event.event_url == event_url)
        if exclude_id:
            query = query.filter(Event.id != exclude_id)
        return query.first()

    def get_instagram_source(self, db: Session, event_id: int) -> dict:
        """이벤트의 Instagram 출처 정보 조회 (lazy loading용)"""
        event = db.query(Event).filter(Event.id == event_id).first()
        if not event:
            return {"url": None, "account": None}

        # 이미 저장된 값이 있으면 반환
        if event.source_instagram_url:
            return {
                "url": event.source_instagram_url,
                "account": event.source_instagram_account,
            }

        # InstagramPost에서 조회
        if event.source_instagram_post_id:
            post = db.query(InstagramPost).filter(
                InstagramPost.id == event.source_instagram_post_id
            ).first()
            if post:
                return {"url": post.url, "account": post.account}

        return {"url": None, "account": None}

    def import_from_url(
        self, db: Session, data: EventImportFromUrl
    ) -> EventImportFromUrlResponse:
        """URL에서 이벤트 정보를 추출.

        1. Playwright로 페이지 로드
        2. ExtractorFactory로 적절한 추출기 선택
        3. 페이지 내용 추출
        4. LLM으로 이벤트 정보 분석
        5. auto_save=True면 Event 생성

        Args:
            db: DB 세션
            data: EventImportFromUrl 스키마

        Returns:
            EventImportFromUrlResponse
        """
        from app.services.page_extractor import get_extractor_factory
        from app.modules.claude_worker.prompts.event_extract import (
            build_event_extract_prompt,
            parse_event_from_llm_response,
        )
        from app.modules.claude_worker.services.llm_service import LLMService

        url = data.url

        # 중복 URL 확인
        existing = self.check_duplicate_url(db, url)
        if existing:
            return EventImportFromUrlResponse(
                success=False,
                is_event=True,
                page_type="unknown",
                extraction_method="skipped",
                error=f"동일 URL로 등록된 이벤트가 있습니다 (ID: {existing.id})",
            )

        try:
            # 비동기 추출 작업 실행
            extracted = asyncio.get_event_loop().run_until_complete(
                self._extract_page_content(url)
            )
        except RuntimeError:
            # 이벤트 루프가 없는 경우 (동기 컨텍스트)
            extracted = asyncio.run(self._extract_page_content(url))

        if not extracted.success:
            return EventImportFromUrlResponse(
                success=False,
                is_event=True,
                page_type=extracted.page_type,
                extraction_method=extracted.extraction_method,
                error=extracted.error or "페이지 추출 실패",
            )

        # LLM 프롬프트 생성
        prompt = build_event_extract_prompt(extracted)

        # LLM 요청 생성 (비동기 큐 패턴)
        from app.modules.claude_worker.models.llm_request import LLMRequest

        llm_request = LLMRequest(
            caller_type="event_import",
            caller_id=url,
            prompt=prompt,
            status="pending",
            requested_by="api",
            request_source="event_import",
        )
        db.add(llm_request)
        db.commit()
        db.refresh(llm_request)

        logger.info(f"Event import 요청 생성: request_id={llm_request.id}, url={url}")

        # 즉시 응답 반환 (Worker가 처리)
        return EventImportFromUrlResponse(
            success=True,
            is_event=True,
            page_type=extracted.page_type,
            extraction_method=extracted.extraction_method,
            raw_content=extracted.content[:1000] if extracted.content else None,
            message=f"이벤트 등록 요청을 받았습니다 (요청 ID: {llm_request.id})",
        )

    async def _extract_page_content(self, url: str):
        """Playwright로 페이지 내용 추출 (비동기).

        Args:
            url: 추출할 페이지 URL

        Returns:
            ExtractedContent 객체
        """
        from playwright.async_api import async_playwright
        from app.services.page_extractor import get_extractor_factory
        from app.services.page_extractor.base import ExtractedContent

        factory = get_extractor_factory()
        extractor = factory.get_extractor(url)

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    viewport={"width": 1280, "height": 800},
                )
                page = await context.new_page()

                try:
                    await page.goto(url, wait_until="networkidle", timeout=30000)
                    extracted = await extractor.extract(page, url)
                    return extracted
                finally:
                    await page.close()
                    await context.close()
                    await browser.close()

        except Exception as e:
            logger.error(f"페이지 추출 실패 ({url}): {e}")
            return ExtractedContent(
                url=url,
                page_type=extractor.page_type,
                extraction_method="failed",
                success=False,
                error=str(e),
            )

    def _parse_event_dates(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        """이벤트 날짜 문자열을 date 객체로 변환.

        Args:
            event_data: 이벤트 데이터 딕셔너리

        Returns:
            날짜가 변환된 이벤트 데이터
        """
        from datetime import datetime

        date_fields = ["event_start", "event_end", "announcement_date"]

        for field in date_fields:
            value = event_data.get(field)
            if value and isinstance(value, str):
                try:
                    # YYYY-MM-DD 형식 파싱
                    parsed = datetime.strptime(value, "%Y-%m-%d").date()
                    event_data[field] = parsed
                except ValueError:
                    # 파싱 실패 시 None으로 설정
                    event_data[field] = None
            elif not value:
                event_data[field] = None

        return event_data

    def _to_response(self, db: Session, event: Event) -> EventResponse:
        """Event 모델을 EventResponse로 변환"""
        response_data = {
            "id": event.id,
            "title": event.title,
            "thumbnail_url": event.thumbnail_url,
            "event_type": event.event_type,
            "status": event.status,
            "event_url": event.event_url,
            "url_type": event.url_type,
            "additional_urls": event.additional_urls or [],
            "event_start": event.event_start,
            "event_end": event.event_end,
            "announcement_date": event.announcement_date,
            "organizer": event.organizer,
            "summary": event.summary,
            "body_text": event.body_text,
            "prizes": event.prizes or [],
            "winner_count": event.winner_count,
            "purchase_required": event.purchase_required,
            "location_venue": event.location_venue,
            "location_address": event.location_address,
            "source_type": event.source_type,
            "source_instagram_post_id": event.source_instagram_post_id,
            "source_url": event.source_url,
            "source_note": event.source_note,
            "user_note": event.user_note,
            "is_bookmarked": event.is_bookmarked,
            "is_participated": event.is_participated,
            "is_offline": event.is_offline,
            "input_source": event.input_source or "human",
            "created_at": event.created_at,
            "updated_at": event.updated_at,
            "source_instagram_url": event.source_instagram_url,
            "source_instagram_account": event.source_instagram_account,
        }

        return EventResponse(**response_data)


event_service = EventService()
