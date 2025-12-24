"""
UncategorizedPost 서비스 - 미분류 게시물 관리 및 재분류
"""
from typing import Optional
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.uncategorized_post import UncategorizedPost
from app.models.instagram_post import InstagramPost
from app.models.event import Event
from app.models.popup import Popup
from app.schemas.uncategorized import (
    UncategorizedResponse,
    UncategorizedList,
    ReclassifyRequest,
    ReclassifyResponse,
)


class UncategorizedService:
    """미분류 게시물 서비스"""

    def get_uncategorized_list(
        self,
        db: Session,
        original_tag: Optional[str] = None,
        include_reclassified: bool = False,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        page: int = 1,
        page_size: int = 50,
    ) -> UncategorizedList:
        """미분류 게시물 목록 조회"""
        query = db.query(UncategorizedPost)

        # 재분류된 항목 제외 (기본)
        if not include_reclassified:
            query = query.filter(UncategorizedPost.reclassified_as.is_(None))

        # 원본 태그 필터
        if original_tag:
            query = query.filter(UncategorizedPost.original_tag == original_tag)

        # 총 개수
        total = query.count()

        # 정렬
        sort_column = getattr(UncategorizedPost, sort_by, UncategorizedPost.created_at)
        if sort_order == "desc":
            query = query.order_by(sort_column.desc())
        else:
            query = query.order_by(sort_column.asc())

        # 페이지네이션
        offset = (page - 1) * page_size
        items = query.offset(offset).limit(page_size).all()

        responses = [self._to_response(item) for item in items]
        total_pages = (total + page_size - 1) // page_size

        return UncategorizedList(
            items=responses,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )

    def get_uncategorized(self, db: Session, uncategorized_id: int) -> Optional[UncategorizedResponse]:
        """단일 미분류 항목 조회"""
        item = db.query(UncategorizedPost).filter(UncategorizedPost.id == uncategorized_id).first()
        if not item:
            return None
        return self._to_response(item)

    def reclassify(
        self,
        db: Session,
        uncategorized_id: int,
        data: ReclassifyRequest,
    ) -> Optional[ReclassifyResponse]:
        """미분류 항목을 Event 또는 Popup으로 재분류"""
        item = db.query(UncategorizedPost).filter(UncategorizedPost.id == uncategorized_id).first()
        if not item:
            return None

        # 이미 재분류된 경우
        if item.reclassified_as:
            return ReclassifyResponse(
                success=False,
                target=item.reclassified_as,
                created_id=item.reclassified_id,
                message=f"Already reclassified as {item.reclassified_as}",
            )

        # Instagram 게시물 조회
        post = db.query(InstagramPost).filter(
            InstagramPost.id == item.source_instagram_post_id
        ).first()

        # 썸네일 추출
        thumbnail_url = item.thumbnail_url
        if not thumbnail_url and post and post.images:
            images = post.images or []
            thumbnail_url = images[0].get("src") if images else None

        if data.target == "event":
            # Event로 재분류
            event = Event(
                title=data.title or item.title or "제목 없음",
                thumbnail_url=thumbnail_url,
                event_type="event",
                event_start=item.start_date,
                event_end=item.end_date,
                organizer=item.organizer,
                summary=item.summary,
                additional_urls=item.urls or [],
                source_type="instagram",
                source_instagram_post_id=item.source_instagram_post_id,
                source_instagram_url=item.source_instagram_url,
                source_instagram_account=item.source_instagram_account,
            )
            db.add(event)
            db.commit()
            db.refresh(event)

            # Uncategorized 업데이트
            item.reclassified_as = "event"
            item.reclassified_id = event.id
            item.reclassified_at = datetime.now()

            # InstagramPost 업데이트
            if post:
                post.classified_type = "event"
                post.classified_id = event.id

            db.commit()

            return ReclassifyResponse(
                success=True,
                target="event",
                created_id=event.id,
                message="Successfully reclassified as event",
            )

        elif data.target == "popup":
            # Popup으로 재분류
            popup = Popup(
                title=data.title or item.title or "제목 없음",
                thumbnail_url=thumbnail_url,
                start_date=item.start_date,
                end_date=item.end_date,
                organizer=item.organizer,
                summary=item.summary,
                additional_urls=item.urls or [],
                source_type="instagram",
                source_instagram_post_id=item.source_instagram_post_id,
                source_instagram_url=item.source_instagram_url,
                source_instagram_account=item.source_instagram_account,
            )
            db.add(popup)
            db.commit()
            db.refresh(popup)

            # Uncategorized 업데이트
            item.reclassified_as = "popup"
            item.reclassified_id = popup.id
            item.reclassified_at = datetime.now()

            # InstagramPost 업데이트
            if post:
                post.classified_type = "popup"
                post.classified_id = popup.id

            db.commit()

            return ReclassifyResponse(
                success=True,
                target="popup",
                created_id=popup.id,
                message="Successfully reclassified as popup",
            )

        return None

    def delete_uncategorized(self, db: Session, uncategorized_id: int) -> bool:
        """미분류 항목 삭제"""
        item = db.query(UncategorizedPost).filter(UncategorizedPost.id == uncategorized_id).first()
        if not item:
            return False

        # 연결된 InstagramPost의 classified_type/id 초기화
        if item.source_instagram_post_id:
            post = db.query(InstagramPost).filter(
                InstagramPost.id == item.source_instagram_post_id
            ).first()
            if post and post.classified_type == 'uncategorized' and post.classified_id == item.id:
                post.classified_type = None
                post.classified_id = None

        db.delete(item)
        db.commit()
        return True

    def _to_response(self, item: UncategorizedPost) -> UncategorizedResponse:
        """UncategorizedPost 모델을 Response로 변환"""
        return UncategorizedResponse(
            id=item.id,
            original_tag=item.original_tag,
            title=item.title,
            thumbnail_url=item.thumbnail_url,
            summary=item.summary,
            organizer=item.organizer,
            start_date=item.start_date,
            end_date=item.end_date,
            urls=item.urls or [],
            source_instagram_post_id=item.source_instagram_post_id,
            source_instagram_url=item.source_instagram_url,
            source_instagram_account=item.source_instagram_account,
            reclassified_as=item.reclassified_as,
            reclassified_id=item.reclassified_id,
            reclassified_at=item.reclassified_at,
            created_at=item.created_at,
        )


uncategorized_service = UncategorizedService()
