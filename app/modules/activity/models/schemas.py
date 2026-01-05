"""Activity Pydantic Schemas - 문화/체육센터 강좌 스키마."""

from datetime import datetime, date
from typing import Optional, List, Any

from pydantic import BaseModel, Field


# ============================================================
# Center Schemas
# ============================================================

class CenterBase(BaseModel):
    """센터 기본 필드."""
    name: str = Field(..., max_length=200)
    center_type: str = Field(..., max_length=50)
    operator: Optional[str] = Field(None, max_length=200)
    region_sido: Optional[str] = Field(None, max_length=20)
    region_sigungu: Optional[str] = Field(None, max_length=30)
    address: Optional[str] = Field(None, max_length=500)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    phone: Optional[str] = Field(None, max_length=50)
    website: Optional[str] = Field(None, max_length=500)
    crawl_url: Optional[str] = Field(None, max_length=500)
    crawl_method: Optional[str] = Field("static", max_length=20)
    crawl_config: Optional[dict] = Field(default_factory=dict)


class CenterCreate(CenterBase):
    """센터 생성 스키마."""
    pass


class CenterUpdate(BaseModel):
    """센터 수정 스키마 (부분 업데이트)."""
    name: Optional[str] = Field(None, max_length=200)
    center_type: Optional[str] = Field(None, max_length=50)
    operator: Optional[str] = Field(None, max_length=200)
    region_sido: Optional[str] = Field(None, max_length=20)
    region_sigungu: Optional[str] = Field(None, max_length=30)
    address: Optional[str] = Field(None, max_length=500)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    phone: Optional[str] = Field(None, max_length=50)
    website: Optional[str] = Field(None, max_length=500)
    crawl_url: Optional[str] = Field(None, max_length=500)
    crawl_method: Optional[str] = Field(None, max_length=20)
    crawl_config: Optional[dict] = None
    is_active: Optional[bool] = None


class CenterResponse(CenterBase):
    """센터 응답 스키마."""
    id: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
    last_crawled_at: Optional[datetime] = None
    course_count: Optional[int] = None

    class Config:
        from_attributes = True


class CenterListResponse(BaseModel):
    """센터 목록 응답."""
    items: List[CenterResponse]
    total: int


# ============================================================
# Course Schemas
# ============================================================

class CourseBase(BaseModel):
    """강좌 기본 필드."""
    source_id: Optional[str] = Field(None, max_length=100)
    source_url: Optional[str] = Field(None, max_length=500)
    name: str = Field(..., max_length=300)
    description: Optional[str] = None
    category: Optional[str] = Field(None, max_length=50)
    subcategory: Optional[str] = Field(None, max_length=100)
    target_age: Optional[str] = Field(None, max_length=50)
    level: Optional[str] = Field(None, max_length=20)
    capacity: Optional[int] = None
    fee: Optional[int] = None
    material_fee: Optional[int] = None
    fee_note: Optional[str] = Field(None, max_length=200)
    registration_start: Optional[datetime] = None
    registration_end: Optional[datetime] = None
    course_start: Optional[date] = None
    course_end: Optional[date] = None
    day_of_week: Optional[str] = Field(None, max_length=50)
    time_start: Optional[str] = Field(None, max_length=10)
    time_end: Optional[str] = Field(None, max_length=10)
    total_sessions: Optional[int] = None
    instructor_name: Optional[str] = Field(None, max_length=100)
    instructor_bio: Optional[str] = None
    status: Optional[str] = Field("active", max_length=20)
    current_enrollment: Optional[int] = None


class CourseResponse(CourseBase):
    """강좌 응답 스키마."""
    id: int
    center_id: int
    collected_at: datetime
    source_updated_at: Optional[datetime] = None
    center_name: Optional[str] = None
    is_registration_open: Optional[bool] = None

    class Config:
        from_attributes = True


class CourseListResponse(BaseModel):
    """강좌 목록 응답."""
    items: List[CourseResponse]
    total: int
    page: int
    page_size: int


class CourseSearchParams(BaseModel):
    """강좌 검색 파라미터."""
    region_sido: Optional[str] = None
    region_sigungu: Optional[str] = None
    category: Optional[str] = None
    target_age: Optional[str] = None
    keyword: Optional[str] = None
    day_of_week: Optional[str] = None
    fee_min: Optional[int] = None
    fee_max: Optional[int] = None
    registration_open: Optional[bool] = None
    center_id: Optional[int] = None
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)


# ============================================================
# Import Schemas
# ============================================================

class CourseImportItem(BaseModel):
    """단일 강좌 임포트 데이터."""

    # 센터 식별 (기존 센터 매칭 또는 신규 생성)
    center_name: str = Field(..., max_length=200)
    center_type: Optional[str] = Field(None, max_length=50)
    center_region_sido: Optional[str] = Field(None, max_length=20)
    center_region_sigungu: Optional[str] = Field(None, max_length=30)
    center_website: Optional[str] = Field(None, max_length=500)

    # 강좌 정보 (필수)
    source_id: str = Field(..., max_length=100)
    name: str = Field(..., max_length=300)

    # 강좌 정보 (선택)
    source_url: Optional[str] = Field(None, max_length=500)
    description: Optional[str] = None
    category: Optional[str] = Field(None, max_length=50)
    subcategory: Optional[str] = Field(None, max_length=100)
    target_age: Optional[str] = Field(None, max_length=50)
    level: Optional[str] = Field(None, max_length=20)
    capacity: Optional[int] = None

    # 비용
    fee: Optional[int] = None
    material_fee: Optional[int] = None
    fee_note: Optional[str] = Field(None, max_length=200)

    # 일정
    registration_start: Optional[datetime] = None
    registration_end: Optional[datetime] = None
    course_start: Optional[date] = None
    course_end: Optional[date] = None
    day_of_week: Optional[str] = Field(None, max_length=50)
    time_start: Optional[str] = Field(None, max_length=10)
    time_end: Optional[str] = Field(None, max_length=10)
    total_sessions: Optional[int] = None

    # 강사
    instructor_name: Optional[str] = Field(None, max_length=100)
    instructor_bio: Optional[str] = None


class CourseImportRequest(BaseModel):
    """임포트 요청."""
    courses: List[CourseImportItem]
    update_existing: bool = True


class ImportErrorDetail(BaseModel):
    """임포트 에러 상세."""
    index: int
    source_id: str
    error: str


class CourseImportResponse(BaseModel):
    """임포트 결과."""
    total: int
    created: int
    updated: int
    skipped: int
    errors: List[ImportErrorDetail]


# ============================================================
# CrawlRun Schemas
# ============================================================

class CrawlRunResponse(BaseModel):
    """크롤링 실행 기록 응답."""
    id: int
    center_id: Optional[int]
    started_at: datetime
    completed_at: Optional[datetime]
    status: str
    courses_found: int
    courses_new: int
    courses_updated: int
    error_message: Optional[str]
    center_name: Optional[str] = None

    class Config:
        from_attributes = True


class CrawlRunListResponse(BaseModel):
    """크롤링 실행 기록 목록."""
    items: List[CrawlRunResponse]
    total: int
