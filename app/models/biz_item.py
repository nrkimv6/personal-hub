"""
BizItem 모델 - 아이템 정보
설계 문서: 2025-12-01_monitoring_restructure_design.md
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from app.models.base import Base


class BizItem(Base):
    """아이템 정보 (biz_item_id 단위)"""
    __tablename__ = "biz_items"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 관계
    business_id = Column(Integer, ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False)
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True)  # 다중 프로필 지원

    # 식별자
    biz_item_id = Column(String, nullable=False)  # 네이버 biz_item_id

    # 기본 정보
    name = Column(String, nullable=False)  # 아이템명
    base_url = Column(String, nullable=True)  # 기본 URL (날짜 제외)

    # 아이템 레벨 설정
    time_range = Column(String, nullable=True)  # 예약 시간 범위 (예: "10:00-21:00")
    auto_booking_enabled = Column(Boolean, default=False)  # 자동 예약 활성화
    max_bookings_per_schedule = Column(Integer, default=1)  # 일정당 최대 예약 횟수
    booking_options_override = Column(Text, nullable=True)  # JSON: 업체 설정 오버라이드

    # 메타
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    # 관계
    business = relationship("Business", back_populates="items")
    account = relationship("Account", back_populates="biz_items")
    schedules = relationship("MonitorSchedule", back_populates="biz_item", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<BizItem(id={self.id}, biz_item_id={self.biz_item_id}, name={self.name})>"
