"""Dev Runner Pydantic Schemas"""

import json as _json
from pydantic import BaseModel, Field, field_validator
from datetime import date, datetime
from typing import Literal, Optional, List, Union

SUPPORTED_RUN_ENGINES = {"claude", "gemini", "codex", "cc-codex"}

RunnerMetadataState = Union[bool, Literal["unknown"]]


# ========== 스키마 ==========

class RunRequest(BaseModel):
    """실행 요청 스키마"""
    plan_file: Optional[str] = Field(None, description="Plan 파일 경로 (null=전체 실행)")
    engine: Optional[str] = Field(None, description="AI 실행 엔진 (claude | gemini | codex | cc-codex)")
    fix_engine: Optional[str] = Field(None, description="Fix/Resolver 전용 AI 엔진 (claude | gemini | codex | cc-codex)")
    max_cycles: Optional[int] = Field(0, description="최대 사이클 수 (0=무제한)")
    max_tokens: Optional[int] = Field(0, description="최대 토큰 수 (0=무제한)")
    until: Optional[str] = Field(None, description="종료 시각 (HH:MM 형식)")
    dry_run: bool = Field(False, description="DRY_RUN 모드")
    skip_plan: bool = Field(False, description="plan 단계 스킵")
    parallel: bool = Field(False, description="병렬 실행 모드")
    projects: Optional[str] = Field(None, description="프로젝트 목록 (쉼표 구분)")
    worktree: bool = Field(True, description="worktree 모드 (격리 실행 + 머지 큐)")
    test_source: Optional[str] = Field(None, description="테스트 출처 (pytest TC 추적용)")
    trigger: Optional[str] = Field(None, description="트리거 소스 (user, user:all, tc:{name}, api, scheduler:{handler_name})")
    session_id: Optional[str] = Field(None, description="fused 세션 ID (UUID). 미지정 시 자동 발급.")
    fused_session: bool = Field(False, description="fused 세션 모드 활성화: 동일 session_id로 단계 간 CLI 세션 연속 유지")
    profile: Optional[str] = Field(None, description="AI 프로필 이름 (엔진별, claude/gemini만 지원)")

    @field_validator("profile", mode="before")
    @classmethod
    def validate_profile(cls, value):
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("프로필 값은 문자열이어야 합니다")
        normalized = value.strip()
        return None if not normalized else normalized

    @field_validator("engine", "fix_engine", mode="before")
    @classmethod
    def validate_engine(cls, value):
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("엔진 값은 문자열이어야 합니다")
        normalized = value.strip()
        if not normalized:
            return None
        if normalized not in SUPPORTED_RUN_ENGINES:
            engines = ", ".join(sorted(SUPPORTED_RUN_ENGINES))
            raise ValueError(f"지원되지 않는 엔진: {normalized} (지원: {engines})")
        return normalized


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
    execution_count: Optional[int] = None
    exit_code: Optional[int] = None  # None=실행중/미시작, 0=정상종료, 그 외=crash
    crashed: bool = False  # exit_code != 0일 때 True
    current_plan_name: Optional[str] = None  # 전체실행 시 현재 실행 중인 plan 파일명
    runner_id: Optional[str] = None
    attached: bool = False  # True = 기존 워커에 연결됨 (새 워커 생성 안 함)
    session_id: Optional[str] = None  # fused 세션 ID (UUID4 형식)
    exit_reason: Optional[str] = None  # 종료 사유 (completed/no_progress/rate_limit/error 등)
    error: Optional[str] = None  # 종료 에러 요약
    worktree_exists: RunnerMetadataState = Field("unknown", description="plan-runner snapshot field; true/false or unknown when absent")
    branch_exists: RunnerMetadataState = Field("unknown", description="plan-runner snapshot field; true/false or unknown when absent")
    branch_merged_to_main: RunnerMetadataState = Field("unknown", description="plan-runner snapshot field; true/false or unknown when absent")
    metadata_checked_at: str = Field("unknown", description="plan-runner snapshot check timestamp or unknown when absent")
    claim_id: Optional[str] = None
    claim_state: Optional[str] = None
    claim_owner_runner_id: Optional[str] = None
    claim_message: Optional[str] = None


class RunnerListItem(BaseModel):
    """활성 runner 목록 항목"""
    runner_id: str
    running: bool
    plan_file: Optional[str] = None
    engine: Optional[str] = None
    start_time: Optional[datetime] = None
    execution_count: Optional[int] = None
    pid: Optional[int] = None
    worktree_path: Optional[str] = None
    branch: Optional[str] = None
    merge_status: Optional[str] = None
    merge_reason: Optional[str] = None
    merge_message: Optional[str] = None
    trigger: Optional[str] = None
    visible: bool = False  # 탭 표시 여부 (user/user:all 트리거만 True, 기본 숨김)
    orphan: bool = False  # Workflow DB에 running/merge_pending/merging 이지만 Redis에 없는 runner
    orphan_alive: bool = False  # active/recent에는 없지만 heartbeat/log evidence가 남은 live runner
    redis_missing: bool = False  # active/recent registry에서 소실되어 fallback으로 복구된 runner
    log_file_found: bool = False  # filesystem/recent-meta fallback으로 표시 가능한 로그가 확인됨
    exit_reason: Optional[str] = None  # 종료 사유 (completed/no_progress/rate_limit/error 등)
    stop_stage: Optional[str] = None  # stopped 세부 단계 (pre_review|post_review|unknown)
    error: Optional[str] = None  # 종료 에러 요약
    display_plan_name: Optional[str] = None  # UI fallback 표시명 (plan_file 소실 시 recent-meta/log/branch에서 복원)
    worktree_exists: RunnerMetadataState = Field("unknown", description="plan-runner snapshot field; true/false or unknown when absent")
    branch_exists: RunnerMetadataState = Field("unknown", description="plan-runner snapshot field; true/false or unknown when absent")
    branch_merged_to_main: RunnerMetadataState = Field("unknown", description="plan-runner snapshot field; true/false or unknown when absent")
    metadata_checked_at: str = Field("unknown", description="plan-runner snapshot check timestamp or unknown when absent")


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
    created_at: Optional[str] = None  # > 작성일시: 헤더에서 추출한 생성시각 (정렬용)
    branch: Optional[str] = None  # > branch: 헤더에서 추출한 impl 브랜치명
    worktree_path: Optional[str] = None  # > worktree: 헤더에서 추출한 워크트리 경로
    worktree_owner: Optional[str] = None  # > worktree-owner: 헤더에서 추출한 소유 plan 경로
    execution_claim_id: Optional[str] = None
    execution_claim_state: Optional[str] = None  # queued | active | released | stale
    execution_claim_runner_id: Optional[str] = None
    execution_claim_stale: bool = False


class RegisteredPathResponse(BaseModel):
    """등록된 경로 응답 스키마"""
    path: str
    type: str  # "file" | "folder"
    plan_count: int
    path_type: str = "plan"  # "plan" | "archive"


class PlanStorageRootChangeItem(BaseModel):
    """plans storage root 변경 파일 요약."""
    status: str
    path: str


class PlanStorageRootStatusItem(BaseModel):
    """Plans 탭 상단에 노출할 root별 compact status."""
    project: str
    repo_root: str
    worktree_path: str
    branch: Optional[str] = None
    upstream: Optional[str] = None
    exists: bool
    status: str
    dirty_count: int = 0
    docs_changes_count: int = 0
    archive_changes_count: int = 0
    policy_changes_count: int = 0
    ahead: int = 0
    behind: int = 0
    push_needed: bool = False
    checked_at: str
    representative_changes: List[PlanStorageRootChangeItem] = Field(default_factory=list)
    error: Optional[str] = None


class PlanStorageRootStatusResponse(BaseModel):
    """등록된 plan storage root들의 상태 요약."""
    checked_at: str
    roots: List[PlanStorageRootStatusItem]
    total: int
    dirty_count: int = 0
    push_needed_count: int = 0


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
    reason: Optional[str] = None
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


class PlanArchiveScheduleSnapshot(BaseModel):
    """Plan Archive scheduler snapshot for health UI."""
    id: int
    enabled: bool
    schedule_value: Optional[str] = None
    last_run: Optional[str] = None
    last_success: Optional[str] = None
    last_failure: Optional[str] = None


class PlanArchiveFailedRequestResponse(BaseModel):
    """Latest failed Plan Archive LLM request."""
    id: int
    caller_id: str
    requested_at: Optional[str] = None
    error_message: Optional[str] = None


class PlanArchiveHealthResponse(BaseModel):
    """Plan Archive health summary."""
    archived_total: int
    llm_processed: int
    llm_unprocessed: int
    real_unprocessed: int
    temp_pytest_total: int
    temp_pytest_unprocessed: int
    pending_or_processing_requests: int
    failed_requests: int
    file_retention_due: int = 0
    file_retention_scheduled: int = 0
    file_removed: int = 0
    oldest_file_delete_after: Optional[str] = None
    latest_failed_request: Optional[PlanArchiveFailedRequestResponse] = None
    oldest_unprocessed_at: Optional[str] = None
    plan_archive_schedule: Optional[PlanArchiveScheduleSnapshot] = None


class PlanArchiveRetrievalQuery(BaseModel):
    """Archive retrieval filter + lexical query."""
    q: Optional[str] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    category: Optional[str] = None
    tags: Optional[List[str]] = None
    intent: Optional[str] = None
    scope: Optional[str] = None
    path: Optional[str] = None
    relation_type: Optional[str] = None
    limit: int = Field(default=20, ge=1, le=100)


class PlanArchiveIndexRequest(BaseModel):
    """Archive retrieval index backfill request."""
    record_id: Optional[int] = None
    limit: int = Field(default=50, ge=1, le=500)
    force: bool = False
    since: Optional[datetime] = None
    apply: bool = False


class PlanArchiveIndexResponse(BaseModel):
    dry_run: bool
    indexed: int = 0
    failed: int = 0
    skipped: int = 0
    run_id: Optional[int] = None
    errors: List[str] = []


class PlanArchiveChunkHit(BaseModel):
    id: int
    section_type: Optional[str] = None
    heading: Optional[str] = None
    text: str
    snippet: Optional[str] = None
    score: Optional[float] = None


class PlanArchiveFileRefHit(BaseModel):
    id: int
    path: str
    source_type: str
    module: Optional[str] = None
    commit_sha: Optional[str] = None
    exists_at_index: Optional[bool] = None


class PlanArchivePlanHit(BaseModel):
    id: int
    filename_hash: str
    file_path: str
    title: Optional[str] = None
    status: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[list] = None
    summary: Optional[str] = None
    intent: Optional[str] = None
    scope: Optional[Union[str, list]] = None
    archived_at: Optional[datetime] = None


class PlanArchiveRetrievalHit(BaseModel):
    plan: PlanArchivePlanHit
    score: float
    score_detail: dict
    chunks: List[PlanArchiveChunkHit] = []
    file_refs: List[PlanArchiveFileRefHit] = []


class PlanArchiveRetrievalResult(BaseModel):
    results: List[PlanArchiveRetrievalHit] = []
    total: int = 0


class PlanArchiveContextRequest(PlanArchiveRetrievalQuery):
    token_budget: int = Field(default=3000, ge=200, le=20000)
    include_raw: bool = False


class PlanArchiveMetricsQuery(PlanArchiveRetrievalQuery):
    pass


class PlanArchiveFollowupRates(BaseModel):
    days_7: float = 0
    days_14: float = 0
    days_30: float = 0


class PlanArchiveTopFileRef(BaseModel):
    path: str
    count: int
    mentioned_count: int = 0
    changed_count: int = 0


class PlanArchiveMissingFileCandidate(BaseModel):
    module: str
    count: int
    paths: List[str] = []


class PlanArchiveMetricsResponse(BaseModel):
    total_plans: int
    followup_rates: PlanArchiveFollowupRates
    top_file_refs: List[PlanArchiveTopFileRef] = []
    missing_file_candidates: List[PlanArchiveMissingFileCandidate] = []
    relation_counts: dict = {}
    chain_depth_max: int = 0


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
    file_delete_after: Optional[datetime] = None
    file_removed_at: Optional[datetime] = None
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
    from_line: int = 0  # 파일 내 시작 줄 번호 (since_line 계산용)


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
    status: str = ""  # "merging" | "queued" | "done" | "failed" | "test_failed" | "error"
    timestamp: str = ""
    worktree_path: str = ""


class MergeStatusResponse(BaseModel):
    """Merge 상태 응답 스키마"""
    runner_id: str
    status: str
    test_passed: Optional[bool] = None
    fix_attempts: int = 0
    message: str = ""
    reason: Optional[str] = None
    quarantine_diff_path: Optional[str] = None


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
    reason: Optional[str] = None
    quarantine_diff_path: Optional[str] = None


class DevRunnerSettingsResponse(BaseModel):
    """Dev Runner 설정 응답 스키마"""
    max_concurrent_runners: int
    default_engine: str = "claude"
    default_fix_engine: str = "claude"
    updated_at: Optional[str] = None


class DevRunnerSettingsUpdateRequest(BaseModel):
    """Dev Runner 설정 업데이트 요청 스키마"""
    max_concurrent_runners: Optional[int] = Field(None, ge=1, le=10, description="최대 동시 실행 수 (1~10)")
    default_engine: Optional[str] = Field(None, description="기본 실행 엔진")
    default_fix_engine: Optional[str] = Field(None, description="기본 fix 엔진")

    @field_validator("default_engine", "default_fix_engine", mode="before")
    @classmethod
    def validate_default_engine(cls, value):
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("엔진 값은 문자열이어야 합니다")
        normalized = value.strip()
        if not normalized:
            return None
        if normalized not in SUPPORTED_RUN_ENGINES:
            engines = ", ".join(sorted(SUPPORTED_RUN_ENGINES))
            raise ValueError(f"지원되지 않는 엔진: {normalized} (지원: {engines})")
        return normalized


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


class DirectMergeRequest(BaseModel):
    """직접 머지 요청 스키마 — 러너 없이 branch/worktree만으로 머지 실행"""
    branch: str = Field(..., description="머지할 브랜치명 (필수)")
    worktree_path: Optional[str] = Field(default=None, description="워크트리 경로 (없으면 branch로 추론)")
    plan_file: Optional[str] = Field(default=None, description="Plan 파일 경로 (없으면 전체 실행)")
    approve_service_lock: bool = Field(default=False, description="service_lock 경고를 확인했음을 표시 (1회 override)")


class RetryMergeRequest(BaseModel):
    """retry-merge Redis 키 재발급용 요청 스키마 — Redis 키가 만료됐을 때 payload로 재설정"""
    worktree_path: Optional[str] = Field(default=None, description="워크트리 경로")
    plan_file: Optional[str] = Field(default=None, description="Plan 파일 경로")
    branch: Optional[str] = Field(default=None, description="브랜치명")
    approve_service_lock: bool = Field(default=False, description="service_lock 경고를 확인했음을 표시 (1회 override)")


class CommitDiffStat(BaseModel):
    """커밋별 파일 변경 통계"""
    file: str
    changes: str  # 예: "+5 -2"


class WorktreeCommit(BaseModel):
    """워크트리 커밋 정보"""
    hash: str
    short_hash: str
    message: str
    date: str
    diff_stat: List[CommitDiffStat]


class WorktreeInfoLite(BaseModel):
    """v2 워크트리 상태 정보 (커밋 상세 lazy-load 전용 lite 스키마)"""
    branch: str
    worktree_path: str
    created_at: Optional[str]
    ahead: int
    behind: int
    locked: bool
    commit_count: int
    plan_file: Optional[str]
    plan_mtime: Optional[str] = None
    is_test: bool = False
    plan_file_archived: bool = False
    cleanable: bool = False


class WorktreeInfo(WorktreeInfoLite):
    """v1 워크트리 상태 정보 (full 커밋 포함)"""
    commits: List[WorktreeCommit]


class MainDirtyStatus(BaseModel):
    dirty_count: int = 0
    files: List[str] = Field(default_factory=list)


class PlanOnlyBranch(BaseModel):
    plan_file: str
    branch: str
    plan_mtime: Optional[str] = None
    is_test: bool = False


class BranchUnresolvedPlan(BaseModel):
    plan_file: str
    reason: str
    plan_mtime: Optional[str] = None
    is_test: bool = False


class WorktreeCleanupRequest(BaseModel):
    branches: List[str] = Field(default_factory=list)
    dry_run: bool = True


class WorktreeCleanupResult(BaseModel):
    branch: str
    status: Literal["removed", "skipped", "failed"]
    reason: str = ""
    worktree_removed: bool = False
    branch_removed: bool = False


class WorktreeCleanupResponse(BaseModel):
    results: List[WorktreeCleanupResult] = Field(default_factory=list)
    summary: dict[str, int] = Field(default_factory=dict)


class WorktreeListResponse(BaseModel):
    worktrees: List[WorktreeInfoLite] = Field(default_factory=list)
    plan_only: List[PlanOnlyBranch] = Field(default_factory=list)
    branch_unresolved: List[BranchUnresolvedPlan] = Field(default_factory=list)
    main_dirty: MainDirtyStatus = Field(default_factory=MainDirtyStatus)


__all__ = [
    'PlanEventResponse',
    'PlanRecordResponse',
    'PlanRecordWithEventsResponse',
    'ImportArchivedResponse',
    'PlanArchiveHealthResponse',
    'PlanArchiveRetrievalQuery',
    'PlanArchiveRetrievalResult',
    'PlanArchiveChunkHit',
    'PlanArchiveFileRefHit',
    'PlanArchiveIndexRequest',
    'PlanArchiveIndexResponse',
    'PlanArchiveContextRequest',
    'PlanArchiveMetricsQuery',
    'PlanArchiveMetricsResponse',
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
    'DirectMergeRequest',
    'RetryMergeRequest',
    'CommitDiffStat',
    'WorktreeCommit',
    'WorktreeInfoLite',
    'WorktreeInfo',
    'MainDirtyStatus',
    'PlanOnlyBranch',
    'BranchUnresolvedPlan',
    'WorktreeCleanupRequest',
    'WorktreeCleanupResult',
    'WorktreeCleanupResponse',
    'WorktreeListResponse',
]
