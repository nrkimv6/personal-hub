"""Dev Runner Pydantic Schemas"""

from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List


# ========== 스키마 ==========

class RunRequest(BaseModel):
    """실행 요청 스키마"""
    plan_file: Optional[str] = Field(None, description="Plan 파일 경로 (null=전체 실행)")
    engine: Optional[str] = Field("claude", description="AI 실행 엔진 (claude | gemini)")
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
    engine: Optional[str] = None
    listener_alive: bool = False
    redis_connected: bool = False
    pid: Optional[int] = None
    plan_file: Optional[str] = None
    start_time: Optional[datetime] = None
    current_cycle: Optional[int] = None
    exit_code: Optional[int] = None  # None=실행중/미시작, 0=정상종료, 그 외=crash
    crashed: bool = False  # exit_code != 0일 때 True
    current_plan_name: Optional[str] = None  # 전체실행 시 현재 실행 중인 plan 파일명
    runner_id: Optional[str] = None


class RunnerListItem(BaseModel):
    """활성 runner 목록 항목"""
    runner_id: str
    running: bool
    plan_file: Optional[str] = None
    engine: Optional[str] = None
    start_time: Optional[datetime] = None
    pid: Optional[int] = None
    worktree_path: Optional[str] = None
    branch: Optional[str] = None
    merge_status: Optional[str] = None
    visible: bool = True  # 탭 표시 여부 (dismiss 전까지 True)


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
    path_type: str = "plan"  # "plan" | "archive"


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
    summary: Optional[str] = None


class DoneResponse(BaseModel):
    """완료 처리 응답 스키마"""
    success: bool
    message: str
    output: Optional[str] = None
    remaining_tasks: int = 0
    total_tasks: int = 0
    plan_status: str = ""


class BatchDoneResultItem(BaseModel):
    """일괄 완료 처리 개별 결과"""
    path: str
    filename: str
    success: bool
    message: str


class BatchDoneResponse(BaseModel):
    """일괄 완료 처리 응답 스키마"""
    total: int
    success: int
    failed: int
    results: List[BatchDoneResultItem]


class VerifyResult(BaseModel):
    """코드베이스 검증 기반 완료 판정 결과"""
    total: int
    verified: int
    unverified_items: List[str]
    percent: float
    can_done: bool


class PlanEventResponse(BaseModel):
    """계획서 이벤트 응답"""
    id: int
    event_type: str
    detail: Optional[dict] = None
    created_at: datetime


class PlanRecordResponse(BaseModel):
    """계획서 레코드 응답"""
    id: int
    filename_hash: str
    file_path: str
    project: Optional[str] = None
    title: Optional[str] = None
    status: Optional[str] = None
    memo: Optional[str] = None
    memo_draft: Optional[str] = None
    archived_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class PlanRecordWithEventsResponse(PlanRecordResponse):
    """계획서 레코드 + 이벤트 목록"""
    events: List[PlanEventResponse] = []


class MemoUpdateRequest(BaseModel):
    """메모 업데이트 요청"""
    action: str  # "draft" | "confirm" | "rollback"
    text: Optional[str] = None  # draft 저장 시 사용


class LogResponse(BaseModel):
    """로그 응답 스키마"""
    lines: List[str]
    total_lines: int


class RunHistoryItem(BaseModel):
    """실행 이력 항목 스키마"""
    runner_id: str
    plan_file: Optional[str] = None
    engine: Optional[str] = None
    status: str = "completed"  # "running" | "completed" | "unknown"
    pid: Optional[int] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    log_file: Optional[str] = None
    has_log: bool = False


class RunHistoryResponse(BaseModel):
    """실행 이력 목록 응답 스키마"""
    runs: List[RunHistoryItem]
    total: int


class FullLogResponse(BaseModel):
    """전체 로그 응답 스키마 (offset/limit 기반 페이지네이션)"""
    lines: List[str]
    total_lines: int
    offset: int
    has_more: bool


class CurrentTrackingResponse(BaseModel):
    """현재 TaskTracker 추적 중인 체크박스 응답 스키마 (Redis 기반)"""
    text: str
    confidence: str         # HIGH / MEDIUM
    line_num: Optional[int] = None
    plan_file: Optional[str] = None
    stale: bool = False     # TTL 만료 여부 (60초 TTL 기반)


class MergeQueueItem(BaseModel):
    """Merge Queue 항목 스키마"""
    runner_id: str
    branch: str
    plan_file: str
    project: str
    status: str
    timestamp: str
    worktree_path: str = ""


class MergeStatusResponse(BaseModel):
    """Merge 상태 응답 스키마"""
    runner_id: str
    status: str
    test_passed: Optional[bool] = None
    fix_attempts: int = 0
    message: str = ""


__all__ = [
    'PlanEventResponse',
    'PlanRecordResponse',
    'PlanRecordWithEventsResponse',
    'MemoUpdateRequest',
    'RunRequest',
    'RunStatusResponse',
    'RunnerListItem',
    'PlanFileResponse',
    'PlanProgressResponse',
    'RegisteredPathResponse',
    'LogResponse',
    'CurrentTrackingResponse',
    'PlanItemResponse',
    'PlanPhaseResponse',
    'PlanDetailResponse',
    'DoneResponse',
    'BatchDoneResponse',
    'BatchDoneResultItem',
    'VerifyResult',
    'MergeQueueItem',
    'MergeStatusResponse',
    'RunHistoryItem',
    'RunHistoryResponse',
    'FullLogResponse',
]
