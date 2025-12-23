"""
Event 서비스 - 독립 이벤트 CRUD 및 관리
"""
from typing import List, Optional, Tuple
from datetime import date

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
)


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

    def get_events(
        self,
        db: Session,
        event_type: Optional[str] = None,
        status: Optional[str] = None,
        event_status: Optional[str] = None,  # ongoing/upcoming/ended
        source_type: Optional[str] = None,
        url_type: Optional[str] = None,
        is_bookmarked: Optional[bool] = None,
        is_participated: Optional[bool] = None,
        include_unknown_period: bool = True,
        sort_by: str = "event_end",
        sort_order: str = "asc",
        page: int = 1,
        page_size: int = 50,
    ) -> EventList:
        """이벤트 목록 조회 (필터/정렬/페이지네이션)"""
        query = db.query(Event)

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

        # event_status 필터 (기간 기반)
        today = date.today()
        if event_status:
            if event_status == "ongoing":
                # 진행 중: 시작일 <= 오늘 AND (종료일 >= 오늘 OR 종료일 NULL)
                conditions = [
                    and_(
                        or_(Event.event_start <= today, Event.event_start.is_(None)),
                        or_(Event.event_end >= today, Event.event_end.is_(None) if include_unknown_period else False),
                    )
                ]
                if include_unknown_period:
                    conditions.append(
                        and_(Event.event_start.is_(None), Event.event_end.is_(None))
                    )
                query = query.filter(or_(*conditions))

            elif event_status == "upcoming":
                # 예정: 시작일 > 오늘
                query = query.filter(Event.event_start > today)

            elif event_status == "ended":
                # 종료: 종료일 < 오늘
                query = query.filter(Event.event_end < today)

            elif event_status == "ongoing_or_upcoming":
                # 진행 중 + 예정: 종료일 >= 오늘 OR 종료일 NULL
                conditions = [Event.event_end >= today]
                if include_unknown_period:
                    conditions.append(Event.event_end.is_(None))
                query = query.filter(or_(*conditions))

        # 총 개수
        total = query.count()

        # 정렬
        sort_column = getattr(Event, sort_by, Event.event_end)
        if sort_order == "desc":
            query = query.order_by(sort_column.desc().nullslast())
        else:
            query = query.order_by(sort_column.asc().nullslast())

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

    def import_from_instagram(
        self, db: Session, data: EventImportFromInstagram
    ) -> Optional[EventResponse]:
        """Instagram 게시물에서 이벤트 생성"""
        post = db.query(InstagramPost).filter(InstagramPost.id == data.instagram_post_id).first()
        if not post:
            return None

        # 이미 연결된 이벤트가 있는지 확인
        existing = db.query(Event).filter(
            Event.source_instagram_post_id == data.instagram_post_id
        ).first()
        if existing:
            return self._to_response(db, existing)

        # LLM 분류 결과에서 이벤트 정보 추출
        event_type_map = {
            "이벤트": "event",
            "팝업": "popup",
            "홍보대사": "ambassador",
        }
        event_type = event_type_map.get(post.llm_tag, "other")

        # llm_urls에서 첫 번째 URL을 메인으로
        llm_urls = post.llm_urls or []
        event_url = llm_urls[0] if llm_urls else None
        additional_urls = llm_urls[1:] if len(llm_urls) > 1 else []

        # llm_location에서 위치 정보 추출
        location = post.llm_location or {}
        location_venue = location.get("venue_name")
        location_address = location.get("address")

        # 이벤트 생성
        event = Event(
            title=data.title or post.llm_summary or f"{post.account}의 이벤트",
            event_type=event_type,
            event_url=event_url,
            url_type=detect_url_type(event_url) if event_url else "other",
            additional_urls=additional_urls,
            event_start=post.llm_event_start,
            event_end=post.llm_event_end,
            announcement_date=post.llm_announcement_date,
            organizer=post.llm_organizer,
            summary=post.llm_summary,
            prizes=post.llm_prizes or [],
            winner_count=post.llm_winner_count,
            purchase_required=post.llm_purchase_required,
            location_venue=location_venue,
            location_address=location_address,
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

    def _to_response(self, db: Session, event: Event) -> EventResponse:
        """Event 모델을 EventResponse로 변환"""
        response_data = {
            "id": event.id,
            "title": event.title,
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
            "created_at": event.created_at,
            "updated_at": event.updated_at,
            "source_instagram_url": None,
            "source_instagram_account": None,
        }

        # Instagram 출처 정보 추가
        if event.source_instagram_post_id:
            post = db.query(InstagramPost).filter(
                InstagramPost.id == event.source_instagram_post_id
            ).first()
            if post:
                response_data["source_instagram_url"] = post.url
                response_data["source_instagram_account"] = post.account

        return EventResponse(**response_data)


event_service = EventService()
