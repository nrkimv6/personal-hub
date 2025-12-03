"""
BizItem 모델 - 아이템 정보
설계 문서: 2025-12-01_monitoring_restructure_design.md
업데이트: 2025-12-03 - GraphQL API 상세정보 컬럼 추가 (REQ-DATA-004)
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
    # DEPRECATED: account_id moved to MonitorSchedule (2025-12-03)
    # 컬럼은 SQLite 제한으로 유지하되 사용하지 않음
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True)

    # 식별자
    biz_item_id = Column(String, nullable=False)  # 네이버 biz_item_id

    # 기본 정보
    name = Column(String, nullable=False)  # 아이템명
    base_url = Column(String, nullable=True)  # 기본 URL (날짜 제외)
    description = Column(Text, nullable=True)  # 상품 설명

    # 아이템 상세정보 (REQ-DATA-004)
    biz_item_type = Column(String, nullable=True)  # 아이템 타입 (예: "STANDARD")
    biz_item_sub_type = Column(String, nullable=True)  # 아이템 서브타입 (예: "RESTAURANT_VISIT")
    booking_count_type = Column(String, nullable=True)  # 예약 타입 (예: "PERSON")
    min_booking_count = Column(Integer, nullable=True)  # 최소 예약 인원
    max_booking_count = Column(Integer, nullable=True)  # 최대 예약 인원
    start_date = Column(String, nullable=True)  # 아이템 시작일
    end_date = Column(String, nullable=True)  # 아이템 종료일

    # 상세정보 JSON (REQ-DATA-004)
    extra_desc_json = Column(Text, nullable=True)  # JSON: 추가 설명 목록
    booking_precaution_json = Column(Text, nullable=True)  # JSON: 예약 주의사항

    # 활성화 상태
    is_enabled = Column(Boolean, default=True)  # 아이템 활성화/비활성화

    # 아이템 레벨 설정
    time_range = Column(String, nullable=True)  # 예약 시간 범위 (예: "10:00-21:00")
    auto_booking_enabled = Column(Boolean, default=False)  # 자동 예약 활성화
    max_bookings_per_schedule = Column(Integer, default=1)  # 일정당 최대 예약 횟수
    booking_options_override = Column(Text, nullable=True)  # JSON: 업체 설정 오버라이드

    # API 데이터 동기화
    api_synced_at = Column(DateTime, nullable=True)  # 마지막 API 동기화 시간

    # 메타
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    # 관계
    business = relationship("Business", back_populates="items")
    account = relationship("Account", back_populates="biz_items")
    schedules = relationship("MonitorSchedule", back_populates="biz_item", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<BizItem(id={self.id}, biz_item_id={self.biz_item_id}, name={self.name})>"
