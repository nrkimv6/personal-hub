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

    # 상세 정보 (2025-12-08 추가)
    fetch_method = Column(String, nullable=True)  # graphql_api, html_scrape, anonymous_api
    time_range = Column(String, nullable=True)  # 적용된 시간 필터 (예: "10:00-21:00")
    original_slot_count = Column(Integer, nullable=True)  # 필터링 전 전체 슬롯 개수
    filtered_slot_count = Column(Integer, nullable=True)  # 필터링 후 슬롯 개수
    target_time_matched = Column(Boolean, default=False)  # time_range 내 슬롯 존재 여부
    booking_triggered = Column(Boolean, default=False)  # 자동 예약 트리거 여부
    booking_success = Column(Boolean, nullable=True)  # 예약 성공 여부 (None: 미시도)

    # 프록시 정보 (2025-12-11 추가)
    proxy_url = Column(String, nullable=True)  # 사용한 프록시 URL (예: http://1.2.3.4:8080)

    # GraphQL 원본 응답 (2025-12-16 추가)
    graphql_response = Column(Text, nullable=True)  # JSON: GraphQL API 원본 응답 데이터

    # 타이밍 상세 (2025-12-16 추가)
    graphql_time_ms = Column(Float, nullable=True)  # GraphQL 호출 시간 (ms)
    proxy_retry_count = Column(Integer, nullable=True)  # 프록시 재시도 횟수
    booking_time_ms = Column(Float, nullable=True)  # 예약 실행 시간 (ms)
    booking_attempt_count = Column(Integer, nullable=True)  # 예약 시도 슬롯 수

    # 관계
    schedule = relationship("MonitorSchedule")
    proxy_usage_logs = relationship(
        "ProxyUsageLog",
        back_populates="monitoring_event",
        cascade="all, delete-orphan"
    )

    # 인덱스
    __table_args__ = (
        Index('ix_monitoring_events_schedule_timestamp', 'schedule_id', 'timestamp'),
        Index('ix_monitoring_events_timestamp', 'timestamp'),
        Index('ix_monitoring_events_status', 'status'),
    )

    def __repr__(self):
        return f"<MonitoringEvent(id={self.id}, schedule_id={self.schedule_id}, status={self.status})>"
