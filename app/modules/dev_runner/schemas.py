"""Dev Runner Pydantic Schemas"""

import json as _json
from pydantic import BaseModel, Field, field_validator
from datetime import date, datetime
from typing import Optional, List


# ========== 스키마 ==========

class RunRequest(BaseModel):
    """실행 요청 스키마"""
    plan_file: Optional[str] = Field(None, description="Plan 파일 경로 (null=전체 실행)")
    engine: Optional[str] = Field("claude", description="AI 실행 엔진 (claude | gemini)")
    fix_engine: Optional[str] = Field("claude", description="Fix/Resolver 전용 AI 엔진 (claude | gemini)")
    max_cycles: Optional[int] = Field(0, description="최대 사이클 수 (0=무제한)")
    max_tokens: Optional[int] = Field(0, description="최대 토큰 수 (0=무제한)")
    until: Optional[str] = Field(None, description="종료 시각 (HH:MM 형식)")
    dry_run: bool = Field(False, description="DRY_RUN 모드")
    skip_plan: bool = Field(False, description="plan 단계 스킵")
    parallel: bool = Field(False, description="병렬 실행 모드")
    projects: Optional[str] = Field(None, description="프로젝트 목록 (쉼표 구분)")
    worktree: bool = Field(True, description="worktree 모드 (격리 실행 + 머지 큐)")
    test_source: Optional[str] = Field(None, description="테스트 출처 (pytest TC 추적용)")
    trigger: Optional[str] = Field(None, description="트리거 소스 (user, user:all, tc:{name}, api)")


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
    trigger: Optional[str] = None
    visible: bool = False  # 탭 표시 여부 (user/user:all 트리거만 True, 기본 숨김)
    orphan: bool = False  # Workflow DB에 running/merge_pending이지만 Redis에 없는 runner
    exit_reason: Optional[str] = None  # 종료 사유 (completed/no_progress/rate_limit/error 등)


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
    progress: Optional[PlanProgressResponse] = None  # 리스트 API에서는 None, 상세 조회 시 포함
    source: str = "common"  # 경로 기반 자동 결정 (common, 프로젝트명, 폴더명)
    ignored: bool = False  # 완료/빈 plan
    path_type: Optional[str] = None  # "file" | "folder" | None (등록된 경로일 때만 설정)
    summary: Optional[str] = None  # > 요약: 헤더에서 추출한 요약 텍스트


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


class ImportArchivedResponse(BaseModel):
    """archived plan DB 이관 응답"""
    created: int
    updated: int
    skipped: int
    errors: List[str]


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
    category: Optional[str] = None
    tags: Optional[list] = None
    summary: Optional[str] = None
    superseded_by: Optional[str] = None
    recurrence_count: int = 1
    chain_root_hash: Optional[str] = None
    recurrence_suggestion: Optional[str] = None
    intent: Optional[str] = None
    trigger: Optional[str] = None
    scope: Optional[list] = None
    plan_date: Optional[date] = None
    applied_at: Optional[datetime] = None
    llm_processed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    @field_validator("scope", mode="before")
    @classmethod
    def deserialize_scope(cls, v):
        if v is None:
            return None
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            try:
                parsed = _json.loads(v)
                return parsed if isinstance(parsed, list) else [parsed]
            except Exception:
                return [v]
        return v


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
    worktree_path: Optional[str] = None
    branch: Optional[str] = None
    merge_status: Optional[str] = None
    trigger: Optional[str] = None


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


class MergeHistoryItem(BaseModel):
    """Merge 실행 이력 항목 스키마"""
    runner_id: str
    branch: str = ""
    plan_file: str = ""
    project: str = ""
    timestamp: str = ""
    worktree_path: str = ""
    status: str = ""
    success: bool = False
    test_passed: Optional[bool] = None
    fix_attempts: int = 0
    message: str = ""


class DevRunnerSettingsResponse(BaseModel):
    """Dev Runner 설정 응답 스키마"""
    max_concurrent_runners: int
    updated_at: Optional[str] = None


class DevRunnerSettingsUpdateRequest(BaseModel):
    """Dev Runner 설정 업데이트 요청 스키마"""
    max_concurrent_runners: int = Field(..., ge=1, le=10, description="최대 동시 실행 수 (1~10)")


class WorkflowResponse(BaseModel):
    """워크플로우 응답 스키마"""
    id: int
    slug: str
    plan_file: Optional[str] = None
    branch: Optional[str] = None
    runner_id: Optional[str] = None
    status: str
    engine: Optional[str] = None
    error_message: Optional[str] = None
    commit_hash: Optional[str] = None
    worktree_path: Optional[str] = None
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    merged_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class WorkflowCreateRequest(BaseModel):
    """워크플로우 수동 생성 요청 스키마"""
    plan_file: Optional[str] = None
    slug: Optional[str] = None


class MergeQueueEnqueueRequest(BaseModel):
    """Merge Queue 직접 투입 요청 스키마 (테스트/수동용)"""
    branch: str = Field(..., description="머지할 브랜치명 (필수)")
    plan_file: str = Field(default="", description="Plan 파일 경로")
    project: str = Field(default="monitor-page", description="대상 프로젝트명")
    worktree_path: str = Field(default="", description="워크트리 경로 (빈 값 허용)")


class DirectMergeRequest(BaseModel):
    """직접 머지 요청 스키마 — 러너 없이 branch/worktree만으로 머지 실행"""
    branch: str = Field(..., description="머지할 브랜치명 (필수)")
    worktree_path: Optional[str] = Field(default=None, description="워크트리 경로 (없으면 branch로 추론)")
    plan_file: Optional[str] = Field(default=None, description="Plan 파일 경로 (없으면 전체 실행)")


class RetryMergeRequest(BaseModel):
    """retry-merge Redis 키 재발급용 요청 스키마 — Redis 키가 만료됐을 때 payload로 재설정"""
    worktree_path: Optional[str] = Field(default=None, description="워크트리 경로")
    plan_file: Optional[str] = Field(default=None, description="Plan 파일 경로")
    branch: Optional[str] = Field(default=None, description="브랜치명")


__all__ = [
    'PlanEventResponse',
    'PlanRecordResponse',
    'PlanRecordWithEventsResponse',
    'ImportArchivedResponse',
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
    'MergeHistoryItem',
    'RunHistoryItem',
    'RunHistoryResponse',
    'FullLogResponse',
    'DevRunnerSettingsResponse',
    'DevRunnerSettingsUpdateRequest',
    'WorkflowResponse',
    'WorkflowCreateRequest',
    'MergeQueueEnqueueRequest',
    'DirectMergeRequest',
    'RetryMergeRequest',
]
