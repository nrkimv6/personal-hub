"""
프록시 관련 모델
작성일: 2025-12-11

Note: 프록시 모델은 별도의 DB 파일(proxies.db)을 사용하므로
메인 앱의 Base와 분리된 ProxyBase를 사용합니다.
"""
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

# 프록시 전용 Base (메인 앱 모델과 분리)
ProxyBase = declarative_base()


class Proxy(ProxyBase):
    """프록시 마스터 테이블"""
    __tablename__ = "proxies"

    id = Column(Integer, primary_key=True)
    url = Column(String, unique=True, nullable=False)
    protocol = Column(String, nullable=False)  # http/https/socks5
    host = Column(String, nullable=False)
    port = Column(Integer, nullable=False)
    username = Column(String)
    password = Column(String)

    # 상태: pending/active/inactive/blacklisted
    status = Column(String, default="pending")

    # 통계
    total_checks = Column(Integer, default=0)
    success_count = Column(Integer, default=0)
    fail_count = Column(Integer, default=0)  # 연속 실패 횟수
    avg_response_time = Column(Float)
    min_response_time = Column(Float)
    max_response_time = Column(Float)

    # 우선순위 점수 (0~100)
    priority_score = Column(Float, default=0)

    # 타임스탬프 (로컬 시간)
    first_seen_at = Column(DateTime, default=datetime.now)
    last_seen_at = Column(DateTime)
    last_checked_at = Column(DateTime)
    last_success_at = Column(DateTime)

    # 메타
    source = Column(String)
    country = Column(String)
    tags = Column(Text)  # JSON 배열

    # 관계
    check_history = relationship(
        "ProxyCheckHistory",
        back_populates="proxy",
        cascade="all, delete-orphan",
        order_by="desc(ProxyCheckHistory.checked_at)"
    )

    @property
    def success_rate(self) -> float | None:
        """성공률 계산"""
        if self.total_checks and self.total_checks > 0:
            return round(self.success_count / self.total_checks * 100, 1)
        return None


class ProxyCheckHistory(ProxyBase):
    """프록시 검증 이력 테이블"""
    __tablename__ = "proxy_check_history"

    id = Column(Integer, primary_key=True)
    proxy_id = Column(Integer, ForeignKey("proxies.id", ondelete="CASCADE"), nullable=False)
    checked_at = Column(DateTime, default=datetime.now)

    # 검증 결과
    is_valid = Column(Boolean, nullable=False)
    response_time = Column(Float)  # 응답 시간 (초)
    error_type = Column(String)  # timeout/connection_refused/http_error/unknown
    error_message = Column(Text)
    http_status = Column(Integer)

    # 추가 정보
    detected_ip = Column(String)
    is_anonymous = Column(Boolean)

    # 관계
    proxy = relationship("Proxy", back_populates="check_history")


class ProxyCollectionRun(ProxyBase):
    """프록시 수집 실행 이력 테이블"""
    __tablename__ = "proxy_collection_runs"

    id = Column(Integer, primary_key=True)
    started_at = Column(DateTime, default=datetime.now)
    finished_at = Column(DateTime)

    # 상태: running/completed/failed/cancelled
    status = Column(String, default="running")

    # 통계
    collected_count = Column(Integer, default=0)
    new_count = Column(Integer, default=0)
    validated_count = Column(Integer, default=0)
    valid_count = Column(Integer, default=0)

    # JSON 필드
    source_stats = Column(Text)  # {"ProxyScrape": 38789, ...}
    error_message = Column(Text)
    config = Column(Text)  # {"max_concurrent": 50, ...}

    @property
    def duration_seconds(self) -> float | None:
        """실행 시간 계산 (초)"""
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None
