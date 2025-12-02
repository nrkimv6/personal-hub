"""
BizItem 서비스 - 아이템 CRUD
설계 문서: 2025-12-01_monitoring_restructure_design.md
"""
import json
from typing import List, Optional
from sqlalchemy.orm import Session
from datetime import datetime

from app.models.biz_item import BizItem
from app.schemas.biz_item import BizItemCreate, BizItemUpdate


class BizItemService:
    """아이템 관리 서비스"""

    def get_by_business(self, db: Session, business_id: int) -> List[BizItem]:
        """업체별 아이템 목록 조회"""
        return db.query(BizItem).filter(
            BizItem.business_id == business_id
        ).order_by(BizItem.name).all()

    def get_by_id(self, db: Session, item_id: int) -> Optional[BizItem]:
        """ID로 아이템 조회"""
        return db.query(BizItem).filter(BizItem.id == item_id).first()

    def get_by_biz_item_id(
        self, db: Session, business_id: int, biz_item_id: str
    ) -> Optional[BizItem]:
        """business_id + biz_item_id로 아이템 조회"""
        return db.query(BizItem).filter(
            BizItem.business_id == business_id,
            BizItem.biz_item_id == biz_item_id
        ).first()

    def create(self, db: Session, data: BizItemCreate) -> BizItem:
        """아이템 생성"""
        booking_options_json = None
        if data.booking_options_override:
            booking_options_json = json.dumps(data.booking_options_override, ensure_ascii=False)

        item = BizItem(
            business_id=data.business_id,
            biz_item_id=data.biz_item_id,
            name=data.name,
            base_url=data.base_url,
            is_enabled=data.is_enabled,
            time_range=data.time_range,
            auto_booking_enabled=data.auto_booking_enabled,
            max_bookings_per_schedule=data.max_bookings_per_schedule,
            booking_options_override=booking_options_json,
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        return item

    def update(self, db: Session, item_id: int, data: BizItemUpdate) -> Optional[BizItem]:
        """아이템 수정"""
        item = self.get_by_id(db, item_id)
        if not item:
            return None

        update_data = data.model_dump(exclude_unset=True)

        # booking_options_override JSON 변환
        if "booking_options_override" in update_data and update_data["booking_options_override"] is not None:
            update_data["booking_options_override"] = json.dumps(
                update_data["booking_options_override"], ensure_ascii=False
            )

        for key, value in update_data.items():
            setattr(item, key, value)

        item.updated_at = datetime.now()
        db.commit()
        db.refresh(item)
        return item

    def delete(self, db: Session, item_id: int) -> bool:
        """아이템 삭제 (하위 일정 모두 삭제)"""
        item = self.get_by_id(db, item_id)
        if not item:
            return False

        db.delete(item)
        db.commit()
        return True

    def get_or_create(
        self,
        db: Session,
        business_id: int,
        biz_item_id: str,
        name: Optional[str] = None,
        base_url: Optional[str] = None,
        time_range: Optional[str] = None,
        auto_booking_enabled: bool = False,
    ) -> BizItem:
        """아이템 조회 또는 생성"""
        item = self.get_by_biz_item_id(db, business_id, biz_item_id)
        if item:
            return item

        # 없으면 생성
        data = BizItemCreate(
            business_id=business_id,
            biz_item_id=biz_item_id,
            name=name or f"Item_{biz_item_id}",
            base_url=base_url,
            time_range=time_range,
            auto_booking_enabled=auto_booking_enabled,
        )
        return self.create(db, data)


# 싱글톤 인스턴스
biz_item_service = BizItemService()
