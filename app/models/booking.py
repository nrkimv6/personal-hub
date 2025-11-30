"""
예약 관련 데이터베이스 모델

- BookingHistory: 예약 이력 저장
- BusinessOption: 사업자별 옵션 설정
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, Float, ForeignKey, JSON
from sqlalchemy.orm import relationship

from app.database import Base


class BookingHistory(Base):
    """예약 이력 테이블"""
    __tablename__ = "booking_history"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 예약 대상 정보
    target_id = Column(Integer, ForeignKey("monitor_targets.id"), nullable=True)
    url = Column(String, nullable=False)
    tag = Column(String, nullable=False)

    # 예약 슬롯 정보
    slot_datetime = Column(String, nullable=False)  # 예: "2025-12-10 18:00:00"
    slot_info = Column(String, nullable=True)  # 예: "2025-12-10 18:00:00 (2매)"

    # 예약 결과
    success = Column(Boolean, default=False)
    error_message = Column(Text, nullable=True)

    # 예약 상세
    business_id = Column(String, nullable=True)
    item_id = Column(String, nullable=True)
    category = Column(String, nullable=True)

    # 메타데이터
    booking_method = Column(String, default="parallel")  # parallel, single
    dry_run = Column(Boolean, default=False)  # 테스트 모드 여부

    # 타임스탬프
    created_at = Column(DateTime, default=datetime.now)
    booking_started_at = Column(DateTime, nullable=True)
    booking_completed_at = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<BookingHistory(id={self.id}, tag={self.tag}, slot={self.slot_datetime}, success={self.success})>"


class BusinessOption(Base):
    """사업자별 옵션 설정 테이블"""
    __tablename__ = "business_options"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 사업자 식별
    business_id = Column(String, nullable=False, unique=True)
    business_name = Column(String, nullable=True)  # 사업자명 (선택)

    # 옵션 자동 선택 설정
    # JSON 형식: {"options": [0, 1], "items": {"6308953": {"options": [0, 1, 2]}}}
    option_config = Column(JSON, nullable=True)

    # 필수 입력 자동화 설정
    # JSON 형식: {"fields": [{"name": "성함", "value": "자동"}, ...]}
    auto_fill_config = Column(JSON, nullable=True)

    # 활성화 여부
    is_active = Column(Boolean, default=True)

    # 타임스탬프
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    def __repr__(self):
        return f"<BusinessOption(id={self.id}, business_id={self.business_id})>"


class MonitoringLog(Base):
    """모니터링 로그 테이블"""
    __tablename__ = "monitoring_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 모니터링 대상
    target_id = Column(Integer, ForeignKey("monitor_targets.id"), nullable=True)
    url = Column(String, nullable=False)
    tag = Column(String, nullable=False)

    # 모니터링 결과
    status = Column(String, nullable=False)  # success, error, no_slots, available
    available_slots_count = Column(Integer, default=0)
    available_slots = Column(JSON, nullable=True)  # 슬롯 리스트

    # 해시값 (변경 감지용)
    data_hash = Column(String, nullable=True)
    hash_changed = Column(Boolean, default=False)

    # API 응답
    api_response = Column(JSON, nullable=True)

    # 에러 정보
    error_message = Column(Text, nullable=True)

    # 성능
    response_time_ms = Column(Float, nullable=True)

    # 타임스탬프
    created_at = Column(DateTime, default=datetime.now)

    def __repr__(self):
        return f"<MonitoringLog(id={self.id}, tag={self.tag}, status={self.status})>"
