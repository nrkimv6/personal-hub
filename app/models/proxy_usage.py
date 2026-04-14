"""
프록시 사용 이력 모델
작성일: 2025-12-18

Note: ProxyUsageLog는 메인 DB(monitor.db)에 저장되므로
      ProxyBase가 아닌 일반 Base를 사용합니다.
"""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime

from app.models.base import Base


class ProxyUsageLog(Base):
    """프록시 사용 이력 테이블"""
    __tablename__ = "proxy_usage_logs"

    id = Column(Integer, primary_key=True)

    # 연결 정보
    monitoring_event_id = Column(
        Integer,
        ForeignKey("monitoring_events.id", ondelete="SET NULL"),
        nullable=True
    )
    schedule_id = Column(
        Integer,
        ForeignKey("monitor_schedules.id", ondelete="CASCADE"),
        nullable=False
    )

    # 프록시 정보
    proxy_url = Column(Text, nullable=False)
    proxy_host = Column(Text)  # 통계/인덱싱용

    # 시도 정보
    attempt_number = Column(Integer, nullable=False)
    request_id = Column(Text)  # 동일 요청 그룹 식별자 (UUID)

    # 결과 정보
    success = Column(Integer, default=0)  # 0/1
    http_status = Column(Integer)
    error_type = Column(Text)  # timeout, connection_error, http_403, etc.
    error_message = Column(Text)
    response_time_ms = Column(Integer)

    # 컨텍스트
    target_url = Column(Text)
    fetch_method = Column(Text)  # graphql_api, anonymous_api, html_scrape
    http_method = Column(Text)  # get, post

    # 타임스탬프
    timestamp = Column(DateTime, default=datetime.now)

    # Relationships
    monitoring_event = relationship(
        "MonitoringEvent",
        back_populates="proxy_usage_logs",
        foreign_keys=[monitoring_event_id]
    )
    schedule = relationship(
        "MonitorSchedule",
        back_populates="proxy_usage_logs",
        foreign_keys=[schedule_id]
    )

    @property
    def is_success(self) -> bool:
        """성공 여부를 bool로 반환"""
        return self.success == 1

    @staticmethod
    def extract_host(proxy_url: str) -> str:
        """프록시 URL에서 호스트 추출

        지원 프로토콜: http, https, socks4, socks5
        예시:
            - http://1.2.3.4:8080 -> 1.2.3.4
            - socks4://user:pass@1.2.3.4:1080 -> 1.2.3.4
            - socks5://1.2.3.4:1080 -> 1.2.3.4
        """
        try:
            url = proxy_url
            # 모든 프로토콜 제거
            for protocol in ["http://", "https://", "socks4://", "socks5://"]:
                url = url.replace(protocol, "")
            # 인증 정보 제거 (user:pass@)
            if "@" in url:
                url = url.split("@")[1]
            # 포트 제거
            return url.split(":")[0]
        except Exception:
            return proxy_url
