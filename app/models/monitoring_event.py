"""
MonitoringEvent 모델 - 모니터링 이벤트 로그
스케줄별 모니터링 체크 결과를 기록합니다.
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, Float, Text, DateTime, ForeignKey, Index
from sqlalchemy.orm import relationship

from app.models.base import Base


class MonitoringEvent(Base):
    """모니터링 이벤트 (체크 결과)"""
    __tablename__ = "monitoring_events"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 관계
    schedule_id = Column(Integer, ForeignKey("monitor_schedules.id", ondelete="CASCADE"), nullable=False)

    # 이벤트 정보
    timestamp = Column(DateTime, default=datetime.now, nullable=False)
    event_type = Column(String, nullable=False)  # check, slot_detected, slot_booked, error

    # 결과
    status = Column(String, nullable=False)  # success, available, no_slots, error
    available_count = Column(Integer, default=0)  # 발견된 슬롯 수
    slots_info = Column(Text, nullable=True)  # JSON: 슬롯 상세 정보

    # 에러 정보
    error_message = Column(Text, nullable=True)

    # 성능
    response_time_ms = Column(Float, nullable=True)

    # 변경 감지
    data_hash = Column(String, nullable=True)
    hash_changed = Column(Boolean, default=False)

    # 관계
    schedule = relationship("MonitorSchedule")

    # 인덱스
    __table_args__ = (
        Index('ix_monitoring_events_schedule_timestamp', 'schedule_id', 'timestamp'),
        Index('ix_monitoring_events_timestamp', 'timestamp'),
        Index('ix_monitoring_events_status', 'status'),
    )

    def __repr__(self):
        return f"<MonitoringEvent(id={self.id}, schedule_id={self.schedule_id}, status={self.status})>"
