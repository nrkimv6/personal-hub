"""Dev Runner Pydantic Schemas"""

from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List


# ========== 기본 스키마 ==========

class TaskResponse(BaseModel):
    """작업 응답 스키마"""
    id: str
    type: str
    source_path: str
    text: str
    priority: int
    status: str
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    output_tokens: int = 0
    input_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    error_message: Optional[str] = None
    model_used: Optional[str] = None

    class Config:
        from_attributes = True


class TaskListResponse(BaseModel):
    """작업 목록 응답 스키마"""
    tasks: List[TaskResponse]
    total: int


class StatsResponse(BaseModel):
    """통계 응답 스키마"""
    total: int
    pending: int
    running: int
    success: int
    failed: int
    skipped: int
    completed: int  # success + failed + skipped
    completion_rate: float  # completed / total
    success_rate: float  # success / completed (completed > 0일 때만)
    total_input_tokens: int
    total_output_tokens: int
    total_cache_tokens: int
    total_tokens: int  # input + output + cache
    total_duration_ms: int


# ========== 추가 스키마 ==========

class RunRequest(BaseModel):
    """실행 요청 스키마"""
    plan_file: Optional[str] = Field(None, description="Plan 파일 경로 (null=전체 실행)")
    max_cycles: Optional[int] = Field(0, description="최대 사이클 수 (0=무제한)")
    max_tokens: Optional[int] = Field(0, description="최대 토큰 수 (0=무제한)")
    until: Optional[str] = Field(None, description="종료 시각 (HH:MM 형식)")
    dry_run: bool = Field(False, description="DRY_RUN 모드")
    skip_plan: bool = Field(False, description="plan 단계 스킵")
    parallel: bool = Field(False, description="병렬 실행 모드")
    projects: Optional[str] = Field(None, description="프로젝트 목록 (쉼표 구분)")


class RunStatusResponse(BaseModel):
    """실행 상태 응답 스키마"""
    running: bool
    listener_alive: bool = False
    redis_connected: bool = False
    pid: Optional[int] = None
    plan_file: Optional[str] = None
    start_time: Optional[datetime] = None
    current_cycle: Optional[int] = None
    exit_code: Optional[int] = None  # None=실행중/미시작, 0=정상종료, 그 외=crash
    crashed: bool = False  # exit_code != 0일 때 True


class PlanProgressResponse(BaseModel):
    """Plan 진행률 스키마"""
    done: int
    total: int
    percent: int


class PlanFileResponse(BaseModel):
    """Plan 파일 응답 스키마"""
    path: str
    filename: str
    status: str
    progress: PlanProgressResponse
    source: str = "common"  # 경로 기반 자동 결정 (common, 프로젝트명, 폴더명)
    ignored: bool = False  # 완료/빈 plan
    path_type: Optional[str] = None  # "file" | "folder" | None (등록된 경로일 때만 설정)


class RegisteredPathResponse(BaseModel):
    """등록된 경로 응답 스키마"""
    path: str
    type: str  # "file" | "folder"
    plan_count: int


class PlanItemResponse(BaseModel):
    """plan 항목 (체크박스 1개)"""
    level: int  # 0=상위(번호), 1=하위(대시)
    text: str
    checked: bool
    children: List['PlanItemResponse'] = []
    file_path: Optional[str] = None  # 파일 경로 언급 시


class PlanPhaseResponse(BaseModel):
    """plan Phase 단위"""
    name: str
    items: List[PlanItemResponse]
    done_count: int
    total_count: int


class PlanDetailResponse(BaseModel):
    """plan 상세 (항목 파싱 결과)"""
    path: str
    filename: str
    status: str
    phases: List[PlanPhaseResponse]
    progress: PlanProgressResponse


class HistoryEntry(BaseModel):
    """작업 히스토리 엔트리"""
    date: str
    count: int
    success: int
    failed: int


class DuplicateTaskResponse(BaseModel):
    """중복 작업 응답 스키마"""
    text: str
    count: int
    tasks: List[TaskResponse]


class LogResponse(BaseModel):
    """로그 응답 스키마"""
    lines: List[str]
    total_lines: int


class CurrentTrackingResponse(BaseModel):
    """현재 TaskTracker 추적 중인 체크박스 응답 스키마 (Redis 기반)"""
    text: str
    confidence: str         # HIGH / MEDIUM
    line_num: Optional[int] = None
    plan_file: Optional[str] = None
    stale: bool = False     # TTL 만료 여부 (60초 TTL 기반)


__all__ = [
    'TaskResponse',
    'TaskListResponse',
    'StatsResponse',
    'RunRequest',
    'RunStatusResponse',
    'PlanFileResponse',
    'PlanProgressResponse',
    'RegisteredPathResponse',
    'HistoryEntry',
    'DuplicateTaskResponse',
    'LogResponse',
    'CurrentTrackingResponse',
    'PlanItemResponse',
    'PlanPhaseResponse',
    'PlanDetailResponse',
]
