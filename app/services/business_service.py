"""
Business 서비스 - 업체 CRUD
설계 문서: 2025-12-01_monitoring_restructure_design.md
"""
import json
from typing import List, Optional
from sqlalchemy.orm import Session
from datetime import datetime

from app.models.business import Business
from app.schemas.business import BusinessCreate, BusinessUpdate


class BusinessService:
    """업체 관리 서비스"""

    def get_all(self, db: Session) -> List[Business]:
        """전체 업체 목록 조회"""
        return db.query(Business).order_by(Business.name).all()

    def get_by_id(self, db: Session, business_id: int) -> Optional[Business]:
        """ID로 업체 조회"""
        return db.query(Business).filter(Business.id == business_id).first()

    def get_by_business_id(self, db: Session, business_id: str) -> Optional[Business]:
        """네이버 business_id로 업체 조회"""
        return db.query(Business).filter(Business.business_id == business_id).first()

    def create(self, db: Session, data: BusinessCreate) -> Business:
        """업체 생성"""
        booking_options_json = None
        if data.booking_options:
            booking_options_json = json.dumps(data.booking_options, ensure_ascii=False)

        business = Business(
            business_id=data.business_id,
            business_type_id=data.business_type_id,
            name=data.name,
            service_type=data.service_type,
            category=data.category,
            booking_options=booking_options_json,
            is_enabled=data.is_enabled,
        )
        db.add(business)
        db.commit()
        db.refresh(business)
        return business

    def update(self, db: Session, business_id: int, data: BusinessUpdate) -> Optional[Business]:
        """업체 수정"""
        business = self.get_by_id(db, business_id)
        if not business:
            return None

        update_data = data.model_dump(exclude_unset=True)

        # booking_options JSON 변환
        if "booking_options" in update_data and update_data["booking_options"] is not None:
            update_data["booking_options"] = json.dumps(update_data["booking_options"], ensure_ascii=False)

        for key, value in update_data.items():
            setattr(business, key, value)

        business.updated_at = datetime.now()
        db.commit()
        db.refresh(business)
        return business

    def delete(self, db: Session, business_id: int) -> bool:
        """업체 삭제 (하위 아이템/일정 모두 삭제)"""
        business = self.get_by_id(db, business_id)
        if not business:
            return False

        db.delete(business)
        db.commit()
        return True

    def get_or_create(
        self,
        db: Session,
        business_id: str,
        business_type_id: Optional[int] = None,
        name: Optional[str] = None,
        service_type: str = "naver",
        category: Optional[str] = None,
    ) -> Business:
        """업체 조회 또는 생성"""
        business = self.get_by_business_id(db, business_id)
        if business:
            return business

        # 없으면 생성
        data = BusinessCreate(
            business_id=business_id,
            business_type_id=business_type_id,
            name=name or f"Business_{business_id}",
            service_type=service_type,
            category=category,
        )
        return self.create(db, data)

    def mark_api_synced(self, db: Session, business_id: int) -> Optional[Business]:
        """API 동기화 시간 업데이트"""
        business = self.get_by_id(db, business_id)
        if not business:
            return None

        business.api_synced_at = datetime.now()
        db.commit()
        db.refresh(business)
        return business


# 싱글톤 인스턴스
business_service = BusinessService()
