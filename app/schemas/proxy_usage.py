"""
프록시 사용 이력 관련 Pydantic 스키마
작성일: 2025-12-18
"""
from pydantic import BaseModel, Field, computed_field
from typing import Optional, List, Dict
from datetime import datetime


# ============== 프록시 사용 로그 ==============

class ProxyUsageLogBase(BaseModel):
    """프록시 사용 로그 기본 스키마"""
    proxy_url: str
    attempt_number: int
    success: bool = False
    http_status: Optional[int] = None
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    response_time_ms: Optional[int] = None


class ProxyUsageLogCreate(ProxyUsageLogBase):
    """프록시 사용 로그 생성 스키마"""
    schedule_id: int
    request_id: str
    target_url: Optional[str] = None
    fetch_method: Optional[str] = None
    monitoring_event_id: Optional[int] = None


class ProxyUsageLogResponse(ProxyUsageLogBase):
    """프록시 사용 로그 응답 스키마"""
    id: int
    schedule_id: int
    monitoring_event_id: Optional[int] = None
    proxy_host: Optional[str] = None
    request_id: Optional[str] = None
    target_url: Optional[str] = None
    fetch_method: Optional[str] = None
    timestamp: datetime

    class Config:
        from_attributes = True


# ============== 프록시 사용 통계 ==============

class ProxyUsageStatItem(BaseModel):
    """개별 프록시 사용 통계"""
    proxy_host: str
    total_attempts: int
    success_count: int
    fail_count: int
    success_rate: float = Field(description="성공률 (%)")
    avg_response_time_ms: Optional[float] = None
    last_used_at: datetime
    error_types: Dict[str, int] = Field(default_factory=dict, description="에러 유형별 카운트")


class ProxyUsageStatsResponse(BaseModel):
    """프록시 사용 통계 응답"""
    total_proxies_used: int = Field(description="사용된 프록시 수")
    total_attempts: int = Field(description="총 시도 횟수")
    overall_success_rate: float = Field(description="전체 성공률 (%)")
    by_proxy: List[ProxyUsageStatItem] = Field(default_factory=list, description="프록시별 통계")
    by_error_type: Dict[str, int] = Field(default_factory=dict, description="에러 유형별 분포")


# ============== 재시도 이력 ==============

class RetryAttemptInfo(BaseModel):
    """재시도 시도 정보"""
    attempt_number: int
    proxy_url: str
    proxy_host: Optional[str] = None
    success: bool
    http_status: Optional[int] = None
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    response_time_ms: Optional[int] = None
    timestamp: datetime


class RetryHistoryResponse(BaseModel):
    """재시도 이력 응답"""
    request_id: str
    schedule_id: int
    business_name: Optional[str] = None
    biz_item_name: Optional[str] = None
    total_attempts: int
    final_success: bool
    attempts: List[RetryAttemptInfo] = Field(default_factory=list)
    started_at: datetime
    completed_at: datetime
    total_duration_ms: int


# ============== 필터링/조회 파라미터 ==============

class ProxyUsageStatsParams(BaseModel):
    """프록시 사용 통계 조회 파라미터"""
    date_from: Optional[str] = Field(None, description="시작 날짜 (YYYY-MM-DD)")
    date_to: Optional[str] = Field(None, description="종료 날짜 (YYYY-MM-DD)")
    schedule_id: Optional[int] = Field(None, description="스케줄 ID 필터")


class ProxyUsageRecentParams(BaseModel):
    """최근 프록시 사용 이력 조회 파라미터"""
    limit: int = Field(100, ge=1, le=500, description="조회 개수")
    proxy_host: Optional[str] = Field(None, description="프록시 호스트 필터")
    success_only: bool = Field(False, description="성공만 조회")


class RetryHistoryParams(BaseModel):
    """재시도 이력 조회 파라미터"""
    request_id: Optional[str] = Field(None, description="요청 ID")
    schedule_id: Optional[int] = Field(None, description="스케줄 ID")
    date_from: Optional[str] = Field(None, description="시작 날짜 (YYYY-MM-DD)")
    limit: int = Field(50, ge=1, le=200, description="조회 개수")


class FailedProxiesParams(BaseModel):
    """실패 많은 프록시 조회 파라미터"""
    hours: int = Field(24, ge=1, le=168, description="조회 기간 (시간)")
    min_failures: int = Field(3, ge=1, description="최소 실패 횟수")


# ============== 정리 결과 ==============

class ProxyUsageCleanupResult(BaseModel):
    """오래된 로그 정리 결과"""
    deleted_count: int = Field(description="삭제된 로그 수")
    before_count: int = Field(description="정리 전 전체 로그 수")
    after_count: int = Field(description="정리 후 전체 로그 수")
    cutoff_date: datetime = Field(description="정리 기준 날짜")
