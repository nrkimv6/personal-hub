"""
ErrorLog 스키마 (Pydantic)
"""
from pydantic import BaseModel, field_validator
from datetime import datetime
from typing import Optional, List, Any
import json


class ErrorLogBase(BaseModel):
    """ErrorLog 기본 스키마"""
    source: str  # api, worker, naver, instagram, writing
    severity: str  # critical, error, warning
    error_type: str  # 예외 클래스명
    message: str
    traceback: Optional[str] = None
    context: Optional[dict] = None


class ErrorLogCreate(ErrorLogBase):
    """ErrorLog 생성 스키마"""
    pass


class ErrorLogUpdate(BaseModel):
    """ErrorLog 업데이트 스키마 (해결 처리용)"""
    resolved: Optional[bool] = None
    resolved_by: Optional[str] = None
    notes: Optional[str] = None


class ErrorLogResponse(ErrorLogBase):
    """ErrorLog 응답 스키마"""
    id: int
    created_at: datetime
    resolved: bool
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[str] = None
    notes: Optional[str] = None

    @field_validator('context', mode='before')
    @classmethod
    def parse_context(cls, v):
        """JSON 문자열을 딕셔너리로 변환"""
        if v is None:
            return None
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, TypeError):
                return None
        return v

    class Config:
        from_attributes = True


class ErrorLogList(BaseModel):
    """ErrorLog 목록 응답"""
    items: List[ErrorLogResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class ErrorLogStats(BaseModel):
    """에러 통계"""
    total_count: int = 0
    critical_count: int = 0
    error_count: int = 0
    warning_count: int = 0
    resolved_count: int = 0
    unresolved_count: int = 0
    resolve_rate: float = 0.0  # 해결률 (%)


class ErrorLogSourceStats(BaseModel):
    """소스별 에러 통계"""
    source: str
    count: int
    critical_count: int = 0
    error_count: int = 0
    warning_count: int = 0


class ErrorLogTypeStats(BaseModel):
    """에러 유형별 통계"""
    error_type: str
    count: int
    last_occurred: Optional[datetime] = None


class ErrorLogHourlyStats(BaseModel):
    """시간대별 에러 통계"""
    hour: int  # 0-23
    count: int
    critical_count: int = 0
    error_count: int = 0
    warning_count: int = 0


class ErrorLogStatsResponse(BaseModel):
    """에러 통계 전체 응답"""
    summary: ErrorLogStats
    by_source: List[ErrorLogSourceStats]
    by_type: List[ErrorLogTypeStats]
    by_hour: List[ErrorLogHourlyStats]
    period_hours: int  # 통계 기간 (시간)


class OperationalIssueResponse(BaseModel):
    """파일 기반 운영 장애 응답"""
    id: str
    created_at: datetime
    source: str
    severity: str
    error_type: str
    message: str
    traceback: Optional[str] = None
    context: Optional[dict[str, Any]] = None


class OperationalIssueList(BaseModel):
    """운영 장애 목록 응답"""
    items: List[OperationalIssueResponse]
    total: int
