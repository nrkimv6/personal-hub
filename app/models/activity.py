"""Activity SQLAlchemy Models - 문화/체육센터 강좌 수집 시스템."""

from datetime import datetime, date
from typing import Optional

from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Date, Boolean, Float, ForeignKey, JSON
)
from sqlalchemy.orm import relationship

from .base import Base


class ActivityCenter(Base):
    """문화/체육센터 모델."""

    __tablename__ = "activity_centers"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 기본 정보
    name = Column(String(200), nullable=False, index=True)
    center_type = Column(String(50), nullable=False, index=True)
    operator = Column(String(200), nullable=True)

    # 위치
    region_sido = Column(String(20), nullable=True, index=True)
    region_sigungu = Column(String(30), nullable=True, index=True)
    address = Column(String(500), nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)

    # 연락처
    phone = Column(String(50), nullable=True)
    website = Column(String(500), nullable=True)

    # 크롤링 설정
    crawl_url = Column(String(500), nullable=True)
    crawl_method = Column(String(20), default="static")
    crawl_config = Column(JSON, default=dict)

    # 메타
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    last_crawled_at = Column(DateTime, nullable=True)

    # 관계
    courses = relationship(
        "ActivityCourse",
        back_populates="center",
        cascade="all, delete-orphan"
    )
    crawl_runs = relationship(
        "ActivityCrawlRun",
        back_populates="center"
    )

    # 센터 타입 상수
    TYPE_PUBLIC_CITY = "public_city"         # 시/도 운영 (광역)
    TYPE_PUBLIC_DISTRICT = "public_district"  # 구/시 운영
    TYPE_PUBLIC_DONG = "public_dong"          # 동 단위 (주민센터)
    TYPE_DEPARTMENT = "department"            # 백화점
    TYPE_MART = "mart"                        # 대형마트
    TYPE_PRIVATE = "private"                  # 사설

    # 크롤링 방식 상수
    CRAWL_STATIC = "static"    # requests 기반
    CRAWL_DYNAMIC = "dynamic"  # Playwright 기반
    CRAWL_API = "api"          # API 호출

    def __repr__(self):
        return f"<ActivityCenter(id={self.id}, name={self.name})>"


class ActivityCourse(Base):
    """강좌 모델."""

    __tablename__ = "activity_courses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    center_id = Column(
        Integer, ForeignKey("activity_centers.id", ondelete="CASCADE"),
        nullable=False, index=True
    )

    # 식별자 (중복 방지)
    source_id = Column(String(100), nullable=True, index=True)
    source_url = Column(String(500), nullable=True)

    # 기본 정보
    name = Column(String(300), nullable=False, index=True)
    description = Column(Text, nullable=True)
    category = Column(String(50), nullable=True, index=True)
    subcategory = Column(String(100), nullable=True)

    # 대상
    target_age = Column(String(50), nullable=True, index=True)
    level = Column(String(20), nullable=True)
    capacity = Column(Integer, nullable=True)

    # 비용
    fee = Column(Integer, nullable=True)
    material_fee = Column(Integer, nullable=True)
    fee_note = Column(String(200), nullable=True)

    # 일정 - 접수
    registration_start = Column(DateTime, nullable=True, index=True)
    registration_end = Column(DateTime, nullable=True, index=True)

    # 일정 - 강좌
    course_start = Column(Date, nullable=True, index=True)
    course_end = Column(Date, nullable=True)
    day_of_week = Column(String(50), nullable=True)
    time_start = Column(String(10), nullable=True)
    time_end = Column(String(10), nullable=True)
    total_sessions = Column(Integer, nullable=True)

    # 강사
    instructor_name = Column(String(100), nullable=True)
    instructor_bio = Column(Text, nullable=True)

    # 상태
    status = Column(String(20), default="active", index=True)
    current_enrollment = Column(Integer, nullable=True)

    # 메타
    collected_at = Column(DateTime, default=datetime.now, index=True)
    source_updated_at = Column(DateTime, nullable=True)

    # 관계
    center = relationship("ActivityCenter", back_populates="courses")

    # 카테고리 상수
    CATEGORY_EXERCISE = "exercise"
    CATEGORY_COOKING = "cooking"
    CATEGORY_ART = "art"
    CATEGORY_MUSIC = "music"
    CATEGORY_LANGUAGE = "language"
    CATEGORY_CERTIFICATE = "certificate"
    CATEGORY_HOBBY = "hobby"
    CATEGORY_OTHER = "other"

    # 대상 연령 상수
    AGE_INFANT = "infant"      # 유아
    AGE_CHILD = "child"        # 어린이
    AGE_YOUTH = "youth"        # 청소년
    AGE_ADULT = "adult"        # 성인
    AGE_SENIOR = "senior"      # 시니어
    AGE_ALL = "all"            # 전체

    # 레벨 상수
    LEVEL_BEGINNER = "beginner"
    LEVEL_INTERMEDIATE = "intermediate"
    LEVEL_ADVANCED = "advanced"

    # 상태 상수
    STATUS_ACTIVE = "active"
    STATUS_CLOSED = "closed"
    STATUS_FULL = "full"
    STATUS_CANCELLED = "cancelled"

    def __repr__(self):
        return f"<ActivityCourse(id={self.id}, name={self.name})>"

    def is_registration_open(self, at: Optional[datetime] = None) -> bool:
        """접수 중인지 확인."""
        if not self.registration_start or not self.registration_end:
            return False
        check_time = at or datetime.now()
        return self.registration_start <= check_time <= self.registration_end


class ActivityCrawlRun(Base):
    """크롤링 실행 기록."""

    __tablename__ = "activity_crawl_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    center_id = Column(
        Integer, ForeignKey("activity_centers.id", ondelete="SET NULL"),
        nullable=True, index=True
    )

    # 실행 정보
    started_at = Column(DateTime, default=datetime.now, index=True)
    completed_at = Column(DateTime, nullable=True)
    status = Column(String(20), default="running", index=True)

    # 결과
    courses_found = Column(Integer, default=0)
    courses_new = Column(Integer, default=0)
    courses_updated = Column(Integer, default=0)

    # 에러
    error_message = Column(Text, nullable=True)

    # 관계
    center = relationship("ActivityCenter", back_populates="crawl_runs")

    # 상태 상수
    STATUS_RUNNING = "running"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"

    def __repr__(self):
        return f"<ActivityCrawlRun(id={self.id}, center_id={self.center_id}, status={self.status})>"

    def mark_completed(self, found: int, new: int, updated: int):
        """완료 표시."""
        self.status = self.STATUS_COMPLETED
        self.completed_at = datetime.now()
        self.courses_found = found
        self.courses_new = new
        self.courses_updated = updated

    def mark_failed(self, error: str):
        """실패 표시."""
        self.status = self.STATUS_FAILED
        self.completed_at = datetime.now()
        self.error_message = error
