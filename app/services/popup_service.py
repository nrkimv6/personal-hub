"""
Popup 서비스 - 팝업스토어 CRUD 및 관리
"""
from typing import List, Optional
from datetime import date

from sqlalchemy.orm import Session
from sqlalchemy import or_, and_

from app.models.popup import Popup
from app.models.instagram_post import InstagramPost
from app.schemas.popup import (
    PopupCreate,
    PopupUpdate,
    PopupResponse,
    PopupList,
    PopupImportFromInstagram,
)


class PopupService:
    """팝업스토어 서비스"""

    def get_popups(
        self,
        db: Session,
        status: Optional[str] = None,
        popup_status: Optional[str] = None,  # ongoing/upcoming/ended
        source_type: Optional[str] = None,
        is_bookmarked: Optional[bool] = None,
        is_visited: Optional[bool] = None,
        unknown_period_filter: str = "include",  # exclude/include/only
        search: Optional[str] = None,
        sort_by: str = "end_date",
        sort_order: str = "asc",
        page: int = 1,
        page_size: int = 50,
    ) -> PopupList:
        """팝업 목록 조회 (필터/정렬/페이지네이션)"""
        query = db.query(Popup)

        # 검색어 필터 (LIKE)
        if search:
            search_pattern = f"%{search}%"
            query = query.filter(
                or_(
                    Popup.title.ilike(search_pattern),
                    Popup.venue_name.ilike(search_pattern),
                    Popup.address.ilike(search_pattern),
                )
            )

        # 기본 필터
        if status:
            query = query.filter(Popup.status == status)
        if source_type:
            query = query.filter(Popup.source_type == source_type)
        if is_bookmarked is not None:
            query = query.filter(Popup.is_bookmarked == is_bookmarked)
        if is_visited is not None:
            query = query.filter(Popup.is_visited == is_visited)

        # unknown_period_filter 처리 (exclude/include/only)
        today = date.today()
        include_unknown = unknown_period_filter in ("include", "only")

        # only: 기간미정만 보기 (시작일과 종료일 모두 NULL)
        if unknown_period_filter == "only":
            query = query.filter(
                and_(Popup.start_date.is_(None), Popup.end_date.is_(None))
            )
        elif unknown_period_filter == "exclude":
            # exclude: 기간미정 제외 (종료일이 있는 것만)
            query = query.filter(Popup.end_date.isnot(None))

        # popup_status 필터 (기간 기반) - only가 아닐 때만 적용
        if popup_status and unknown_period_filter != "only":
            if popup_status == "ongoing":
                conditions = [
                    and_(
                        or_(Popup.start_date <= today, Popup.start_date.is_(None)),
                        or_(Popup.end_date >= today, Popup.end_date.is_(None) if include_unknown else False),
                    )
                ]
                if include_unknown:
                    conditions.append(
                        and_(Popup.start_date.is_(None), Popup.end_date.is_(None))
                    )
                query = query.filter(or_(*conditions))

            elif popup_status == "upcoming":
                query = query.filter(Popup.start_date > today)

            elif popup_status == "ended":
                query = query.filter(Popup.end_date < today)

            elif popup_status == "ongoing_or_upcoming":
                conditions = [Popup.end_date >= today]
                if include_unknown:
                    conditions.append(Popup.end_date.is_(None))
                query = query.filter(or_(*conditions))

        # 총 개수
        total = query.count()

        # 정렬
        sort_column = getattr(Popup, sort_by, Popup.end_date)
        if sort_order == "desc":
            query = query.order_by(sort_column.desc().nullslast())
        else:
            query = query.order_by(sort_column.asc().nullslast())

        # 페이지네이션
        offset = (page - 1) * page_size
        popups = query.offset(offset).limit(page_size).all()

        items = [self._to_response(popup) for popup in popups]
        total_pages = (total + page_size - 1) // page_size

        return PopupList(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )

    def get_popup(self, db: Session, popup_id: int) -> Optional[PopupResponse]:
        """단일 팝업 조회"""
        popup = db.query(Popup).filter(Popup.id == popup_id).first()
        if not popup:
            return None
        return self._to_response(popup)

    def create_popup(self, db: Session, data: PopupCreate) -> PopupResponse:
        """팝업 생성"""
        popup = Popup(
            title=data.title,
            thumbnail_url=data.thumbnail_url,
            start_date=data.start_date,
            end_date=data.end_date,
            venue_name=data.venue_name,
            address=data.address,
            floor_info=data.floor_info,
            operating_hours=data.operating_hours,
            admission_fee=data.admission_fee,
            reservation_required=data.reservation_required,
            reservation_url=data.reservation_url,
            brand=data.brand,
            organizer=data.organizer,
            collaboration=data.collaboration,
            summary=data.summary,
            highlights=data.highlights,
            official_url=data.official_url,
            additional_urls=data.additional_urls,
            source_type=data.source_type,
            source_instagram_post_id=data.source_instagram_post_id,
            source_instagram_url=data.source_instagram_url,
            source_instagram_account=data.source_instagram_account,
            user_note=data.user_note,
            input_source=data.input_source,
        )

        db.add(popup)
        db.commit()
        db.refresh(popup)

        return self._to_response(popup)

    def update_popup(
        self, db: Session, popup_id: int, data: PopupUpdate
    ) -> Optional[PopupResponse]:
        """팝업 수정"""
        popup = db.query(Popup).filter(Popup.id == popup_id).first()
        if not popup:
            return None

        update_data = data.model_dump(exclude_unset=True)

        # AI가 생성한 팝업을 수정하면 'ai_edited'로 변경
        if popup.input_source == "ai" and "input_source" not in update_data:
            update_data["input_source"] = "ai_edited"

        for field, value in update_data.items():
            setattr(popup, field, value)

        db.commit()
        db.refresh(popup)

        return self._to_response(popup)

    def delete_popup(self, db: Session, popup_id: int) -> bool:
        """팝업 삭제"""
        popup = db.query(Popup).filter(Popup.id == popup_id).first()
        if not popup:
            return False

        # 연결된 InstagramPost의 classified_type/id 초기화
        if popup.source_instagram_post_id:
            post = db.query(InstagramPost).filter(
                InstagramPost.id == popup.source_instagram_post_id
            ).first()
            if post and post.classified_type == 'popup' and post.classified_id == popup.id:
                post.classified_type = None
                post.classified_id = None

        db.delete(popup)
        db.commit()
        return True

    def toggle_bookmark(self, db: Session, popup_id: int) -> Optional[PopupResponse]:
        """북마크 토글"""
        popup = db.query(Popup).filter(Popup.id == popup_id).first()
        if not popup:
            return None

        popup.is_bookmarked = not popup.is_bookmarked
        db.commit()
        db.refresh(popup)

        return self._to_response(popup)

    def toggle_visited(self, db: Session, popup_id: int) -> Optional[PopupResponse]:
        """방문 완료 토글"""
        popup = db.query(Popup).filter(Popup.id == popup_id).first()
        if not popup:
            return None

        popup.is_visited = not popup.is_visited
        db.commit()
        db.refresh(popup)

        return self._to_response(popup)

    def import_from_instagram(
        self, db: Session, data: PopupImportFromInstagram
    ) -> Optional[PopupResponse]:
        """Instagram 게시물에서 팝업 생성.

        Note: llm_* 필드가 제거되었으므로 기본 정보만으로 팝업을 생성합니다.
        LLM 분석 결과는 claude_worker가 직접 Popup 테이블에 저장합니다.
        """
        post = db.query(InstagramPost).filter(InstagramPost.id == data.instagram_post_id).first()
        if not post:
            return None

        # 이미 연결된 팝업이 있는지 확인
        existing = db.query(Popup).filter(
            Popup.source_instagram_post_id == data.instagram_post_id
        ).first()
        if existing:
            return self._to_response(existing)

        # 썸네일 추출
        images = post.images or []
        thumbnail_url = images[0].get("src") if images else None

        # 기본 팝업 생성 (LLM 분석 데이터는 별도로 업데이트됨)
        popup = Popup(
            title=data.title or f"{post.account}의 팝업",
            thumbnail_url=thumbnail_url,
            additional_urls=[],
            source_type="instagram",
            source_instagram_post_id=post.id,
            source_instagram_url=post.url,
            source_instagram_account=post.account,
        )

        db.add(popup)
        db.commit()
        db.refresh(popup)

        return self._to_response(popup)

    def get_instagram_source(self, db: Session, popup_id: int) -> dict:
        """팝업의 Instagram 출처 정보 조회 (lazy loading용)"""
        popup = db.query(Popup).filter(Popup.id == popup_id).first()
        if not popup:
            return {"url": None, "account": None}

        if popup.source_instagram_url:
            return {
                "url": popup.source_instagram_url,
                "account": popup.source_instagram_account,
            }

        if popup.source_instagram_post_id:
            post = db.query(InstagramPost).filter(
                InstagramPost.id == popup.source_instagram_post_id
            ).first()
            if post:
                return {"url": post.url, "account": post.account}

        return {"url": None, "account": None}

    def _to_response(self, popup: Popup) -> PopupResponse:
        """Popup 모델을 PopupResponse로 변환"""
        return PopupResponse(
            id=popup.id,
            title=popup.title,
            thumbnail_url=popup.thumbnail_url,
            start_date=popup.start_date,
            end_date=popup.end_date,
            venue_name=popup.venue_name,
            address=popup.address,
            floor_info=popup.floor_info,
            operating_hours=popup.operating_hours,
            admission_fee=popup.admission_fee,
            reservation_required=popup.reservation_required or False,
            reservation_url=popup.reservation_url,
            brand=popup.brand,
            organizer=popup.organizer,
            collaboration=popup.collaboration,
            summary=popup.summary,
            highlights=popup.highlights or [],
            official_url=popup.official_url,
            additional_urls=popup.additional_urls or [],
            source_type=popup.source_type,
            source_instagram_post_id=popup.source_instagram_post_id,
            source_instagram_url=popup.source_instagram_url,
            source_instagram_account=popup.source_instagram_account,
            user_note=popup.user_note,
            input_source=popup.input_source or "human",
            status=popup.status,
            is_bookmarked=popup.is_bookmarked or False,
            is_visited=popup.is_visited or False,
            created_at=popup.created_at,
            updated_at=popup.updated_at,
        )


popup_service = PopupService()
