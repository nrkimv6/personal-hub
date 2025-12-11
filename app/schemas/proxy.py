"""
프록시 관련 Pydantic 스키마
작성일: 2025-12-11
"""
from pydantic import BaseModel, Field, computed_field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum
from dataclasses import dataclass, field


class ProxyStatus(str, Enum):
    """프록시 상태"""
    PENDING = "pending"
    ACTIVE = "active"
    INACTIVE = "inactive"
    BLACKLISTED = "blacklisted"


class ProxyProtocol(str, Enum):
    """프록시 프로토콜"""
    HTTP = "http"
    HTTPS = "https"
    SOCKS5 = "socks5"


# ============== 프록시 정보 (런타임용) ==============

@dataclass
class ProxyInfo:
    """
    프록시 정보 데이터 클래스 (런타임 사용)

    ProxyManagerV2에서 활성 풀 관리 및 프록시 선택에 사용
    """
    id: int
    url: str
    protocol: str
    host: str
    port: int
    username: Optional[str] = None
    password: Optional[str] = None

    # 품질 메트릭
    priority_score: float = 0.0
    avg_response_time: Optional[float] = None
    success_count: int = 0
    fail_count: int = 0
    total_checks: int = 0

    def to_aiohttp_proxy(self) -> str:
        """aiohttp용 프록시 URL 반환"""
        if self.username and self.password:
            return f"{self.protocol}://{self.username}:{self.password}@{self.host}:{self.port}"
        return f"{self.protocol}://{self.host}:{self.port}"

    def to_playwright_proxy(self) -> dict:
        """Playwright용 프록시 설정 반환"""
        config = {"server": f"{self.protocol}://{self.host}:{self.port}"}
        if self.username:
            config["username"] = self.username
            config["password"] = self.password or ""
        return config

    @property
    def success_rate(self) -> Optional[float]:
        """성공률 (0.0 ~ 1.0)"""
        if self.total_checks > 0:
            return self.success_count / self.total_checks
        return None

    @classmethod
    def from_db_row(cls, row: dict) -> "ProxyInfo":
        """DB 조회 결과에서 ProxyInfo 생성"""
        return cls(
            id=row["id"],
            url=row["url"],
            protocol=row["protocol"],
            host=row["host"],
            port=row["port"],
            username=row.get("username"),
            password=row.get("password"),
            priority_score=row.get("priority_score", 0.0),
            avg_response_time=row.get("avg_response_time"),
            success_count=row.get("success_count", 0),
            fail_count=row.get("fail_count", 0),
            total_checks=row.get("total_checks", 0),
        )


@dataclass
class ValidationResult:
    """프록시 검증 결과"""
    is_valid: bool
    response_time: Optional[float] = None
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    detected_ip: Optional[str] = None
    is_anonymous: Optional[bool] = None
    http_status: Optional[int] = None


# ============== 검증 이력 ==============

class ProxyCheckHistoryBase(BaseModel):
    """검증 이력 기본 스키마"""
    is_valid: bool
    response_time: Optional[float] = None
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    http_status: Optional[int] = None
    detected_ip: Optional[str] = None
    is_anonymous: Optional[bool] = None


class ProxyCheckHistoryCreate(ProxyCheckHistoryBase):
    """검증 이력 생성 스키마"""
    proxy_id: int


class ProxyCheckHistoryResponse(ProxyCheckHistoryBase):
    """검증 이력 응답 스키마"""
    id: int
    proxy_id: int
    checked_at: datetime

    class Config:
        from_attributes = True


# ============== 프록시 ==============

class ProxyBase(BaseModel):
    """프록시 기본 스키마"""
    url: str
    protocol: str
    host: str
    port: int
    username: Optional[str] = None
    password: Optional[str] = None
    source: Optional[str] = None
    country: Optional[str] = None
    tags: Optional[str] = None


class ProxyCreate(ProxyBase):
    """프록시 생성 스키마"""
    pass


class ProxyUpdate(BaseModel):
    """프록시 수정 스키마"""
    status: Optional[str] = None
    tags: Optional[str] = None


class ProxyResponse(ProxyBase):
    """프록시 응답 스키마"""
    id: int
    status: str
    total_checks: int
    success_count: int
    fail_count: int
    avg_response_time: Optional[float] = None
    priority_score: float
    first_seen_at: Optional[datetime] = None
    last_checked_at: Optional[datetime] = None
    last_success_at: Optional[datetime] = None

    @computed_field
    @property
    def success_rate(self) -> Optional[float]:
        """성공률 (%)"""
        if self.total_checks > 0:
            return round(self.success_count / self.total_checks * 100, 1)
        return None

    class Config:
        from_attributes = True


class ProxyDetailResponse(ProxyResponse):
    """프록시 상세 응답 스키마 (검증 이력 포함)"""
    min_response_time: Optional[float] = None
    max_response_time: Optional[float] = None
    last_seen_at: Optional[datetime] = None
    check_history: List[ProxyCheckHistoryResponse] = []

    class Config:
        from_attributes = True


# ============== 수집 실행 이력 ==============

class ProxyCollectionRunBase(BaseModel):
    """수집 실행 기본 스키마"""
    status: str = "running"
    collected_count: int = 0
    new_count: int = 0
    validated_count: int = 0
    valid_count: int = 0


class ProxyCollectionRunCreate(BaseModel):
    """수집 실행 생성 스키마"""
    config: Optional[Dict[str, Any]] = None


class ProxyCollectionRunUpdate(BaseModel):
    """수집 실행 수정 스키마"""
    status: Optional[str] = None
    finished_at: Optional[datetime] = None
    collected_count: Optional[int] = None
    new_count: Optional[int] = None
    validated_count: Optional[int] = None
    valid_count: Optional[int] = None
    source_stats: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None


class ProxyCollectionRunResponse(ProxyCollectionRunBase):
    """수집 실행 응답 스키마"""
    id: int
    started_at: datetime
    finished_at: Optional[datetime] = None
    source_stats: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    config: Optional[Dict[str, Any]] = None

    @computed_field
    @property
    def duration_seconds(self) -> Optional[float]:
        """실행 시간 (초)"""
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None

    class Config:
        from_attributes = True


# ============== 통계 및 목록 ==============

class ProxyStatsResponse(BaseModel):
    """프록시 전체 통계 응답"""
    total: int = Field(description="전체 프록시 수")
    active: int = Field(description="활성 프록시 수")
    pending: int = Field(description="대기 중 프록시 수")
    inactive: int = Field(description="비활성 프록시 수")
    blacklisted: int = Field(description="블랙리스트 프록시 수")
    avg_response_time: Optional[float] = Field(None, description="평균 응답 시간 (초)")
    overall_success_rate: Optional[float] = Field(None, description="전체 성공률 (%)")
    by_protocol: Dict[str, int] = Field(default_factory=dict, description="프로토콜별 분포")
    by_country: List[Dict[str, Any]] = Field(default_factory=list, description="국가별 분포 (상위 10개)")
    today_checks: int = Field(0, description="오늘 검증 횟수")
    today_success_rate: Optional[float] = Field(None, description="오늘 성공률 (%)")


class ProxyListParams(BaseModel):
    """프록시 목록 조회 파라미터"""
    status: Optional[str] = Field(None, description="상태 필터")
    protocol: Optional[str] = Field(None, description="프로토콜 필터")
    country: Optional[str] = Field(None, description="국가 필터")
    search: Optional[str] = Field(None, description="검색어 (URL, IP)")
    sort_by: str = Field("priority_score", description="정렬 기준")
    sort_order: str = Field("desc", description="정렬 방향 (asc/desc)")
    page: int = Field(1, ge=1, description="페이지 번호")
    page_size: int = Field(50, ge=1, le=100, description="페이지당 항목 수")


class ProxyListResponse(BaseModel):
    """프록시 목록 응답"""
    items: List[ProxyResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class ProxyImportResult(BaseModel):
    """프록시 임포트 결과"""
    total_parsed: int = Field(description="파싱된 프록시 수")
    new_count: int = Field(description="신규 등록 수")
    updated_count: int = Field(description="업데이트 수")
    skipped_count: int = Field(description="스킵된 수")
    errors: List[str] = Field(default_factory=list, description="오류 목록")
