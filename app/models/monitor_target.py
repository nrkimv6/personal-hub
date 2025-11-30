from typing import Optional, Literal
from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Enum, Float, Text
from sqlalchemy.ext.declarative import declarative_base
import enum

Base = declarative_base()

class ServiceType(str, enum.Enum):
    """모니터링 대상의 서비스 타입"""
    COUPANG = "coupang"
    NAVER = "naver"

class MonitorTarget(Base):
    __tablename__ = "monitor_targets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    url = Column(String, nullable=False)
    base_url = Column(String, nullable=False)
    label = Column(String, nullable=False)
    date = Column(String, nullable=False)
    times = Column(Text, nullable=False)
    category = Column(String, nullable=False)
    service_type = Column(Enum(ServiceType), nullable=False, default=ServiceType.COUPANG)
    is_active = Column(Boolean, default=True)
    is_enabled = Column(Boolean, default=True)
    run_status = Column(String, default='idle')
    last_error = Column(String, nullable=True)
    error_count = Column(Integer, default=0)
    interval = Column(Float, nullable=True)
    custom_interval = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    # 예약 관련 필드 (신규)
    auto_booking_enabled = Column(Boolean, default=False)  # 자동 예약 활성화
    max_bookings = Column(Integer, default=1)  # 최대 예약 횟수
    booking_count = Column(Integer, default=0)  # 현재 예약 횟수
    time_range = Column(String, nullable=True)  # 예약 시간 범위 (예: "10:00-21:00")
    last_booking_time = Column(DateTime, nullable=True)  # 마지막 예약 시각
    booking_options = Column(Text, nullable=True)  # JSON: 사업자별 옵션 설정 오버라이드

    def __repr__(self):
        return f"<MonitorTarget(id={self.id}, url={self.url}, label={self.label}, service_type={self.service_type}, date={self.date})>" 