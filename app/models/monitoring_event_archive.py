"""Monitoring Event Archive SQLAlchemy Model (read-only)."""

from sqlalchemy import Column, Integer, String, Boolean, Float, Text, DateTime
from datetime import datetime

from .base import Base


class MonitoringEventArchive(Base):
    """모니터링 이벤트 아카이브 모델 (read-only).

    monitoring_events_archive 파티셔닝 부모 테이블 매핑.
    관계(relationship) 없음 — 조회 전용.
    """
    __tablename__ = "monitoring_events_archive"

    id = Column(Integer, primary_key=True)
    schedule_id = Column(Integer, nullable=False, index=True)

    timestamp = Column(DateTime, default=datetime.now, nullable=False, index=True)
    event_type = Column(String, nullable=False)

    status = Column(String, nullable=False, index=True)
    available_count = Column(Integer, default=0)
    slots_info = Column(Text)

    error_message = Column(Text)
    response_time_ms = Column(Float)

    data_hash = Column(String)
    hash_changed = Column(Boolean, default=False)

    fetch_method = Column(String)
    time_range = Column(String)
    original_slot_count = Column(Integer)
    filtered_slot_count = Column(Integer)
    target_time_matched = Column(Boolean, default=False)
    booking_triggered = Column(Boolean, default=False)
    booking_success = Column(Boolean)

    proxy_url = Column(String)
    graphql_response = Column(Text)

    graphql_time_ms = Column(Float)
    proxy_retry_count = Column(Integer)
    booking_time_ms = Column(Float)
    booking_attempt_count = Column(Integer)

    def __repr__(self):
        return f"<MonitoringEventArchive(id={self.id}, schedule_id={self.schedule_id}, status={self.status})>"
