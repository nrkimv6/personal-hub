"""
Business 모델 - 업체 정보
설계 문서: 2025-12-01_monitoring_restructure_design.md
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean
from sqlalchemy.orm import relationship

from app.models.base import Base, ServiceType


class Business(Base):
    """업체 정보 (business_id 단위)"""
    __tablename__ = "businesses"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 식별자
    business_id = Column(String, nullable=False, unique=True)  # 네이버 business_id
    business_type_id = Column(Integer, nullable=True)  # 네이버 business_type_id

    # 기본 정보
    name = Column(String, nullable=False)  # 업체명
    service_type = Column(String, nullable=False, default="naver")  # naver/coupang
    category = Column(String, nullable=True)  # 카테고리

    # 업체 레벨 설정
    booking_options = Column(Text, nullable=True)  # JSON: 사업자별 예약 옵션

    # 활성화 상태
    is_enabled = Column(Boolean, default=True)  # 업체 전체 활성화/비활성화

    # 메타
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    # 관계
    items = relationship("BizItem", back_populates="business", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Business(id={self.id}, business_id={self.business_id}, name={self.name})>"
