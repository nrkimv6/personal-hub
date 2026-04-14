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
    request_method: str = "get"

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
            request_method=row.get("request_method", "get"),
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


@dataclass
class ProxyUsageStats:
    """
    프록시 사용 통계 (메모리 누적용)

    풀 갱신 시점까지 메모리에 누적되며, 갱신 시 배치로 DB에 저장됩니다.
    """
    proxy_id: int
    success_count: int = 0
    fail_count: int = 0
    total_response_time: float = 0.0
    request_count: int = 0
    last_error_type: Optional[str] = None
    last_error_message: Optional[str] = None
    min_response_time: Optional[float] = None
    max_response_time: Optional[float] = None

    def record_success(self, response_time: float) -> None:
        """성공 기록"""
        self.success_count += 1
        self.request_count += 1
        self.total_response_time += response_time

        if self.min_response_time is None or response_time < self.min_response_time:
            self.min_response_time = response_time
        if self.max_response_time is None or response_time > self.max_response_time:
            self.max_response_time = response_time

    def record_failure(self, error_type: str, error_message: Optional[str] = None) -> None:
        """실패 기록"""
        self.fail_count += 1
        self.request_count += 1
        self.last_error_type = error_type
        self.last_error_message = error_message

    @property
    def avg_response_time(self) -> Optional[float]:
        """평균 응답시간"""
        if self.success_count > 0:
            return self.total_response_time / self.success_count
        return None

    @property
    def success_rate(self) -> Optional[float]:
        """성공률 (0.0 ~ 1.0)"""
        if self.request_count > 0:
            return self.success_count / self.request_count
        return None


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
    request_method: Optional[str] = None
    validation_url: Optional[str] = None


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
    request_method: str = "get"
    status: str
    total_checks: int
    success_count: int
    fail_count: int
    avg_response_time: Optional[float] = None
    priority_score: float
    get_status: Optional[str] = None
    post_status: Optional[str] = None
    get_total_checks: Optional[int] = None
    post_total_checks: Optional[int] = None
    get_success_count: Optional[int] = None
    post_success_count: Optional[int] = None
    get_fail_count: Optional[int] = None
    post_fail_count: Optional[int] = None
    get_avg_response_time: Optional[float] = None
    post_avg_response_time: Optional[float] = None
    get_min_response_time: Optional[float] = None
    post_min_response_time: Optional[float] = None
    get_max_response_time: Optional[float] = None
    post_max_response_time: Optional[float] = None
    get_priority_score: Optional[float] = None
    post_priority_score: Optional[float] = None
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

    @classmethod
    def from_proxy(cls, proxy: Any, request_method: str = "get") -> "ProxyResponse":
        """ORM 프록시에서 메서드별 응답 생성."""
        method = "post" if (request_method or "get").lower() == "post" else "get"
        status_value = getattr(proxy, f"{method}_status", None)
        total_checks_value = getattr(proxy, f"{method}_total_checks", None)
        success_count_value = getattr(proxy, f"{method}_success_count", None)
        fail_count_value = getattr(proxy, f"{method}_fail_count", None)
        avg_response_time_value = getattr(proxy, f"{method}_avg_response_time", None)
        priority_score_value = getattr(proxy, f"{method}_priority_score", None)
        last_checked_at_value = getattr(proxy, f"{method}_last_checked_at", None)
        last_success_at_value = getattr(proxy, f"{method}_last_success_at", None)
        data = {
            "id": proxy.id,
            "url": proxy.url,
            "protocol": proxy.protocol,
            "host": proxy.host,
            "port": proxy.port,
            "username": proxy.username,
            "password": proxy.password,
            "source": getattr(proxy, "source", None),
            "country": getattr(proxy, "country", None),
            "tags": getattr(proxy, "tags", None),
            "request_method": method,
            "status": status_value if status_value is not None else proxy.status,
            "total_checks": total_checks_value if total_checks_value is not None else (proxy.total_checks or 0),
            "success_count": success_count_value if success_count_value is not None else (proxy.success_count or 0),
            "fail_count": fail_count_value if fail_count_value is not None else (proxy.fail_count or 0),
            "avg_response_time": avg_response_time_value if avg_response_time_value is not None else proxy.avg_response_time,
            "priority_score": priority_score_value if priority_score_value is not None else (proxy.priority_score or 0.0),
            "get_status": getattr(proxy, "get_status", None),
            "post_status": getattr(proxy, "post_status", None),
            "get_total_checks": getattr(proxy, "get_total_checks", None),
            "post_total_checks": getattr(proxy, "post_total_checks", None),
            "get_success_count": getattr(proxy, "get_success_count", None),
            "post_success_count": getattr(proxy, "post_success_count", None),
            "get_fail_count": getattr(proxy, "get_fail_count", None),
            "post_fail_count": getattr(proxy, "post_fail_count", None),
            "get_avg_response_time": getattr(proxy, "get_avg_response_time", None),
            "post_avg_response_time": getattr(proxy, "post_avg_response_time", None),
            "get_min_response_time": getattr(proxy, "get_min_response_time", None),
            "post_min_response_time": getattr(proxy, "post_min_response_time", None),
            "get_max_response_time": getattr(proxy, "get_max_response_time", None),
            "post_max_response_time": getattr(proxy, "post_max_response_time", None),
            "get_priority_score": getattr(proxy, "get_priority_score", None),
            "post_priority_score": getattr(proxy, "post_priority_score", None),
            "first_seen_at": proxy.first_seen_at,
            "last_checked_at": last_checked_at_value if last_checked_at_value is not None else proxy.last_checked_at,
            "last_success_at": last_success_at_value if last_success_at_value is not None else proxy.last_success_at,
        }
        return cls.model_validate(data)

    class Config:
        from_attributes = True


class ProxyDetailResponse(ProxyResponse):
    """프록시 상세 응답 스키마 (검증 이력 포함)"""
    min_response_time: Optional[float] = None
    max_response_time: Optional[float] = None
    last_seen_at: Optional[datetime] = None
    check_history: List[ProxyCheckHistoryResponse] = []

    @classmethod
    def from_proxy(cls, proxy: Any, request_method: str = "get") -> "ProxyDetailResponse":
        response = cls.model_validate(ProxyResponse.from_proxy(proxy, request_method=request_method))
        method = "post" if (request_method or "get").lower() == "post" else "get"
        min_response_time_value = getattr(proxy, f"{method}_min_response_time", None)
        max_response_time_value = getattr(proxy, f"{method}_max_response_time", None)
        response.min_response_time = min_response_time_value if min_response_time_value is not None else proxy.min_response_time
        response.max_response_time = max_response_time_value if max_response_time_value is not None else proxy.max_response_time
        response.last_seen_at = proxy.last_seen_at
        return response

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
    request_method: str = Field("get", description="조회 기준 메서드")
    by_method: Dict[str, Any] = Field(default_factory=dict, description="메서드별 통계")


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
    request_method: str = Field("get", description="조회 기준 메서드")


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
