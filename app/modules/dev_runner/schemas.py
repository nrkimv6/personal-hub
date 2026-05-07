"""Dev Runner Pydantic Schemas"""

import json as _json
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from datetime import date, datetime
from typing import Any, Literal, Optional, List, Union

SUPPORTED_RUN_ENGINES = {"claude", "gemini", "codex", "cc-codex"}
PLAN_ARCHIVE_BLOCKED_PROVIDERS = {"cc-codex"}

RunnerMetadataState = Union[bool, Literal["unknown"]]
RunnerDisplaySeverity = Literal["info", "warn", "error", "approval", "success", "muted"]


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
    display_state: str = "stopped"
    display_label: str = "중지됨"
    display_severity: RunnerDisplaySeverity = "muted"
    display_secondary: Optional[str] = None
    hide_stale_branch_badge: bool = False
    gate_evidence_summary: Optional[dict[str, Any]] = None


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
    remaining_post_merge_tasks: Optional[int] = None  # completed 오분류 진단: T4/T5/Phase Z 잔여 수
    merge_evidence_missing: Optional[bool] = None  # completed 오분류 진단: branch/worktree evidence 없음
    worktree_exists: RunnerMetadataState = Field("unknown", description="plan-runner snapshot field; true/false or unknown when absent")
    branch_exists: RunnerMetadataState = Field("unknown", description="plan-runner snapshot field; true/false or unknown when absent")
    branch_merged_to_main: RunnerMetadataState = Field("unknown", description="plan-runner snapshot field; true/false or unknown when absent")
    metadata_checked_at: str = Field("unknown", description="plan-runner snapshot check timestamp or unknown when absent")
    display_state: str = "stopped"
    display_label: str = "중지됨"
    display_severity: RunnerDisplaySeverity = "muted"
    display_secondary: Optional[str] = None
    hide_stale_branch_badge: bool = False
    gate_evidence_summary: Optional[dict[str, Any]] = None


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
    relation_refreshed: int = 0


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


class PlanArchiveDbReadinessResponse(BaseModel):
    """Plan Archive DB readiness summary."""
    ok: bool
    required_tables: List[str] = []
    missing_tables: List[str] = []


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
    category_pollution_candidates: int = 0
    oldest_file_delete_after: Optional[str] = None
    latest_failed_request: Optional[PlanArchiveFailedRequestResponse] = None
    oldest_unprocessed_at: Optional[str] = None
    plan_archive_schedule: Optional[PlanArchiveScheduleSnapshot] = None
    retrieval_db_readiness: PlanArchiveDbReadinessResponse
    execution_db_readiness: PlanArchiveDbReadinessResponse


class PlanArchiveCategoryRepairRequest(BaseModel):
    apply: bool = False
    limit: int = Field(default=100, ge=1, le=1000)


class PlanArchiveCategoryRepairItem(BaseModel):
    record_id: int
    filename_hash: str
    file_path: Optional[str] = None
    old_category: Optional[str] = None
    suggested_category: str
    applied: bool = False


class PlanArchiveCategoryRepairResponse(BaseModel):
    apply: bool = False
    matched: int = 0
    repaired: int = 0
    items: List[PlanArchiveCategoryRepairItem] = Field(default_factory=list)


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
    repo_key: Optional[str] = None
    relation_type: Optional[str] = None
    semantic_cluster_id: Optional[str] = None
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


class PlanArchiveCrossRepoIndexRequest(BaseModel):
    record_id: int
    max_commits: int = Field(default=30, ge=1, le=200)
    apply: bool = False


class PlanArchiveCrossRepoIndexResponse(BaseModel):
    dry_run: bool
    record_id: int
    repos: int = 0
    indexed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: List[str] = []


class PlanArchiveEmbeddingIndexRequest(BaseModel):
    """Archive chunk embedding backfill request."""
    limit: int = Field(default=50, ge=1, le=500)
    force: bool = False
    apply: bool = False
    provider: Optional[str] = None
    model: Optional[str] = None
    dimension: Optional[int] = Field(default=None, ge=1, le=4096)
    timeout_seconds: Optional[int] = Field(default=None, ge=1, le=3600)


class PlanArchiveEmbeddingIndexResponse(BaseModel):
    dry_run: bool
    indexed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: List[str] = []
    provider: str
    model: str
    dimension: int


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
    repo_key: str = "monitor-page"
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


class PlanRecordRelationPlanSummary(BaseModel):
    id: int
    filename_hash: str
    file_path: str
    title: Optional[str] = None
    status: Optional[str] = None
    archived_at: Optional[datetime] = None


class PlanRecordRelationResponse(BaseModel):
    id: int
    direction: Literal["outgoing", "incoming"]
    relation_type: str
    score: int
    evidence: Optional[dict[str, Any]] = None
    source: PlanRecordRelationPlanSummary
    target: PlanRecordRelationPlanSummary
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class PlanRecordRelationStatisticsResponse(BaseModel):
    relation_counts: dict[str, int] = {}
    unresolved_followup_count: int = 0
    recent_unresolved_followups: List[PlanRecordRelationResponse] = []
    top_sources: List[dict[str, Any]] = []
    top_targets: List[dict[str, Any]] = []


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
    repo_key: Optional[str] = None


class PlanArchiveMissingFileCandidate(BaseModel):
    module: str
    count: int
    paths: List[str] = []


class PlanArchiveDownstreamSyncMissingCandidate(BaseModel):
    repo_key: str
    path: str
    count: int = 0


class PlanArchiveMetricsResponse(BaseModel):
    total_plans: int
    followup_rates: PlanArchiveFollowupRates
    top_file_refs: List[PlanArchiveTopFileRef] = []
    missing_file_candidates: List[PlanArchiveMissingFileCandidate] = []
    relation_counts: dict = {}
    chain_depth_max: int = 0
    repo_counts: dict = {}
    cross_repo_plan_count: int = 0
    multi_repo_plan_count: int = 0
    downstream_sync_missing_candidates: List[PlanArchiveDownstreamSyncMissingCandidate] = []


class PlanArchiveInsightBatchRequest(BaseModel):
    """Plan Archive metrics insight batch request."""
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    grouping: str = "category"
    category: Optional[str] = None
    path: Optional[str] = None
    limit: int = Field(default=20, ge=1, le=100)
    token_budget: int = Field(default=3000, ge=200, le=20000)
    provider: Optional[str] = None
    model: Optional[str] = None
    apply: bool = False
    force: bool = False


class PlanArchiveInsightBatchResponse(BaseModel):
    dry_run: bool
    queued: bool = False
    skipped: bool = False
    reason: Optional[str] = None
    report_id: Optional[int] = None
    llm_request_id: Optional[int] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    metrics_hash: str
    metrics: dict = {}
    evidence: List[dict] = []
    prompt: Optional[str] = None
    warnings: List[str] = []


class PlanArchiveInsightReportResponse(BaseModel):
    id: int
    range_start: Optional[datetime] = None
    range_end: Optional[datetime] = None
    grouping: str
    metrics_hash: str
    provider: str
    model: str
    status: str
    review_status: str
    review_note: Optional[str] = None
    promoted_plan_path: Optional[str] = None
    warning: Optional[str] = None
    error_message: Optional[str] = None
    llm_request_id: Optional[int] = None
    created_at: datetime
    completed_at: Optional[datetime] = None
    summary: Optional[str] = None
    root_causes: List[str] = []
    recommendations: List[str] = []
    suggested_plan_candidates: List[dict] = []


class PlanArchiveInsightReportListResponse(BaseModel):
    items: List[PlanArchiveInsightReportResponse] = []
    total: int = 0


class PlanArchiveInsightReportDetailResponse(PlanArchiveInsightReportResponse):
    metrics: dict = {}
    evidence: List[dict] = []
    insight: dict = {}
    raw_response: Optional[str] = None


class PlanArchiveInsightReviewUpdateRequest(BaseModel):
    review_status: str
    review_note: Optional[str] = None


class PlanArchiveInsightPromotePlanRequest(BaseModel):
    candidate_index: int = Field(default=0, ge=0)
    confirm: bool = False
    title: Optional[str] = None


class PlanArchiveInsightPromotePlanResponse(BaseModel):
    path: str
    report: PlanArchiveInsightReportDetailResponse


class PlanArchiveDocPatchPreviewRequest(BaseModel):
    record_id: int
    patch_text: str = ""
    insight_report_id: Optional[int] = None
    target_path: Optional[str] = None


class PlanArchiveDocPatchApplyRequest(BaseModel):
    confirm: bool = False


class PlanArchiveDocPatchProposalResponse(BaseModel):
    id: int
    plan_record_id: int
    insight_report_id: Optional[int] = None
    status: str
    target_path: str
    patch_text: str
    preview_text: Optional[str] = None
    changed_lines_summary: List[dict] = []
    applied_commit: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    applied_at: Optional[datetime] = None


class PlanArchiveAnalyzeRequest(BaseModel):
    """Manual Plan Archive analyze request."""
    mode: Literal["preview", "apply"] = "preview"
    provider: Optional[str] = None
    model: Optional[str] = None
    timeout_seconds: int = Field(120, ge=1, le=3600)
    include_prompt: bool = False
    source: Optional[Literal["auto", "raw_content", "file_path"]] = "auto"


class PlanArchiveAnalyzeResponse(BaseModel):
    """Manual Plan Archive analyze response."""
    success: bool
    mode: str
    result: dict = Field(default_factory=dict)
    raw_response: str = ""
    provider: Optional[str] = None
    model: Optional[str] = None
    record_id: int
    filename_hash: Optional[str] = None
    file_path: Optional[str] = None
    elapsed_ms: int = 0
    prompt_preview: Optional[str] = None
    prompt_policy_id: Optional[str] = None
    prompt_policy_version: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)
    error: Optional[str] = None
    saved: bool = False
    record_after: Optional[dict] = None
    save_error: Optional[str] = None
    save_outcome_status: Optional[str] = None
    save_outcome_reason: Optional[str] = None


class PlanArchiveSelectedProfile(BaseModel):
    engine: str
    profile_name: str


class PlanArchiveExecutionTarget(BaseModel):
    """provider/model 기반 실행 대상. profile 없는 Codex/GPT도 지원."""
    provider: str
    model: str
    profile_key: Optional[str] = None
    engine: Optional[str] = None
    profile_name: Optional[str] = None
    label: Optional[str] = None

    @field_validator("provider", mode="before")
    @classmethod
    def validate_plan_archive_provider(cls, value):
        provider = str(value or "").strip()
        if provider in PLAN_ARCHIVE_BLOCKED_PROVIDERS:
            raise ValueError(f"Plan Archive target provider is blocked: {provider}")
        return provider

    def dedupe_key(self) -> str:
        """중복 방지 키.

        - profile-backed: 'profile:{profile_key}:{model|default}' 또는 'profile:{engine}:{profile_name}:{model|default}'
        - profile-less: 'profileless:{provider}:{model|default}'
        """
        model = (self.model or "").strip() or "default"
        if self.profile_key:
            return f"profile:{self.profile_key}:{model}"
        if self.engine and self.profile_name:
            return f"profile:{self.engine}:{self.profile_name}:{model}"
        provider = (self.provider or "").strip() or "unknown"
        return f"profileless:{provider}:{model}"


class PlanArchiveExecutionRunRequest(BaseModel):
    record_ids: List[int] = Field(default_factory=list)
    selected_profiles: List[PlanArchiveSelectedProfile] = Field(default_factory=list)
    selected_targets: List[PlanArchiveExecutionTarget] = Field(default_factory=list)


class PlanArchiveCandidateQueueRequest(BaseModel):
    """archive 후보 큐잉 요청. file_only → import 후 큐잉, matched/db_only → 기존 record로 큐잉."""
    candidate_keys: List[str] = Field(default_factory=list, description="파일 경로 기반 후보 키 목록")
    record_ids: List[int] = Field(default_factory=list, description="기존 PlanRecord id 목록")
    selected_targets: List[PlanArchiveExecutionTarget] = Field(default_factory=list)
    import_file_only: bool = Field(True, description="file_only 후보를 DB로 import한 뒤 큐잉")


class PlanArchiveCandidateQueueSkipItem(BaseModel):
    candidate_key: Optional[str] = None
    record_id: Optional[int] = None
    reason: str


class PlanArchiveCandidateQueueErrorItem(BaseModel):
    candidate_key: Optional[str] = None
    record_id: Optional[int] = None
    error: str


class PlanArchiveCandidateQueueResponse(BaseModel):
    """archive 후보 큐잉 응답. 4구간 분류: queued / imported / skipped / errors."""
    queued: int = 0
    imported: int = 0
    skipped: List[PlanArchiveCandidateQueueSkipItem] = Field(default_factory=list)
    errors: List[PlanArchiveCandidateQueueErrorItem] = Field(default_factory=list)
    job_ids: List[int] = Field(default_factory=list)
    request_ids: List[int] = Field(default_factory=list)


class PlanArchiveCandidatePreviewResponse(BaseModel):
    """file_only candidate dry-run preview. DB write 없음."""
    candidate_key: str
    resolved_path: str
    filename_hash: str
    total_bytes: int
    total_lines: int
    is_binary: bool
    raw_content_preview: str  # 앞 8KB
    not_queueable: Optional[str] = None  # 큐잉 불가 사유 (있으면 preview만 가능)


class PlanArchiveExecutionRunResponse(BaseModel):
    queued: int = 0
    skipped_empty: int = 0
    skipped_active_request: int = 0
    skipped_active_job: int = 0
    skipped_temp: int = 0
    profile_count: int = 0
    job_ids: List[int] = Field(default_factory=list)
    request_ids: List[int] = Field(default_factory=list)


class PlanArchiveExecutionAttemptResponse(BaseModel):
    id: Optional[int] = None
    llm_request_id: Optional[int] = None
    status: Optional[str] = None
    engine: Optional[str] = None
    profile_name: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    requested_provider: Optional[str] = None
    requested_model: Optional[str] = None
    requested_engine: Optional[str] = None
    requested_profile_name: Optional[str] = None
    requested_profile_key: Optional[str] = None
    target_label: Optional[str] = None
    requested_target: Optional[dict] = None
    effective_target: Optional[dict] = None
    actual_target: Optional[dict] = None
    effective_provider_model: Optional[dict] = None
    actual_provider_model: Optional[dict] = None
    assigned_profile: Optional[dict] = None
    retryable: bool = False
    error_message: Optional[str] = None
    requested_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class PlanArchiveExecutionHistoryItem(BaseModel):
    id: int
    plan_record_id: int
    plan_title: Optional[str] = None
    file_path: Optional[str] = None
    trigger_source: str
    status: str
    selected_profiles: List[dict] = Field(default_factory=list)
    selected_targets: List[dict] = Field(default_factory=list)
    profile_count: int = 0
    latest_request_id: Optional[int] = None
    next_available_at: Optional[datetime] = None
    error_message: Optional[str] = None
    created_at: datetime
    queued_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    latest_attempt: Optional[PlanArchiveExecutionAttemptResponse] = None


class PlanArchiveExecutionHistoryResponse(BaseModel):
    items: List[dict] = Field(default_factory=list)
    total: int = 0
    limit: int = 50
    record_id: Optional[int] = None


class PlanArchiveExecutionSyncResponse(BaseModel):
    updated: int = 0
    checked: int = 0
    created: int = 0
    record_updated: int = 0
    missing: int = 0
    errors: List[str] = Field(default_factory=list)


class PlanRecordsSyncResponse(BaseModel):
    """plan_records 파일 동기화 응답"""
    created: int
    updated: int
    missing: int
    archive_created: int = 0
    archive_updated: int = 0
    archive_normalized: int = 0
    relation_refreshed: int = 0


class PlanRecordResponse(BaseModel):
    """계획서 레코드 응답"""
    model_config = ConfigDict(from_attributes=True)

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
    archive_state: Optional[str] = None
    execution_state: Optional[str] = None
    latest_attempt: Optional[PlanArchiveExecutionAttemptResponse] = None
    next_available_at: Optional[datetime] = None
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
    applied_request_id: Optional[int] = None

    @model_validator(mode="after")
    def compute_applied_request_id(self) -> "PlanRecordWithEventsResponse":
        """plan_archive_analysis_saved 이벤트에서 가장 최근 적용된 request_id 추출"""
        saved_events = [
            e for e in self.events
            if e.event_type == "plan_archive_analysis_saved" and e.detail
        ]
        if saved_events:
            latest = max(saved_events, key=lambda e: e.id)
            rid = latest.detail.get("request_id")
            if isinstance(rid, int):
                self.applied_request_id = rid
        return self


class ArchiveCandidateRecordResponse(BaseModel):
    """archive 후보에 붙이는 DB 레코드 요약"""
    id: int
    filename_hash: str
    file_path: str
    project: Optional[str] = None
    title: Optional[str] = None
    status: Optional[str] = None
    archived_at: Optional[datetime] = None
    category: Optional[str] = None
    tags: Optional[list] = None
    summary: Optional[str] = None
    intent: Optional[str] = None
    trigger: Optional[str] = None
    scope: Optional[list] = None
    llm_processed_at: Optional[datetime] = None
    updated_at: datetime

    @field_validator("scope", mode="before")
    @classmethod
    def deserialize_scope(cls, v):
        return PlanRecordResponse.deserialize_scope(v)


class ArchiveCandidateResponse(BaseModel):
    """archive 파일 + DB 상태를 합친 실행 후보"""
    filename_hash: str
    file_path: str
    file_exists: bool
    db_exists: bool
    state: str
    reason: str
    eligible_for_import: bool
    eligible_for_analysis: bool
    needs_archive_normalization: bool = False
    registered_path: Optional[str] = None
    duplicate_paths: List[str] = []
    file_mtime: Optional[datetime] = None
    file_size: Optional[int] = None
    attempt_count: int = 0
    last_attempt_status: Optional[str] = None
    last_attempt_at: Optional[datetime] = None
    record: Optional[ArchiveCandidateRecordResponse] = None


class ArchiveCandidateSummaryResponse(BaseModel):
    """archive 후보 목록 요약"""
    total: int
    returned: int
    file_only: int = 0
    db_only: int = 0
    matched: int = 0
    needs_archive_normalization: int = 0
    stale_path: int = 0
    duplicate_hash: int = 0
    llm_pending: int = 0
    candidates: List[ArchiveCandidateResponse]


class ArchiveAnalyzeRequest(BaseModel):
    """archive plan LLM 분석 큐잉 요청."""
    provider: Optional[str] = None
    model: Optional[str] = None
    profile_key: Optional[str] = None


class ArchiveAnalyzeResponse(BaseModel):
    """archive plan LLM 분석 큐잉 응답."""
    id: int
    caller_type: str
    caller_id: str
    status: str
    provider: str
    model: str
    profile_key: Optional[str] = None


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
    gate_evidence_summary: Optional[dict[str, Any]] = None


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
    gate_evidence_summary: Optional[dict[str, Any]] = None


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


# ── Phase 4-A: dashboard / list endpoint schemas ─────────────────────────────

class ArchiveQueueSummary(BaseModel):
    """LLMRequest queue count summary (counts only, no full rows)."""
    pending: int = 0
    processing: int = 0
    failed: int = 0
    completed_24h: int = 0
    recent_failures_by_category: dict = Field(default_factory=dict)


class ArchiveLLMRequestRow(BaseModel):
    """One LLMRequest row for archive queue list."""
    id: int
    status: str
    provider: str = ""
    model: str = ""
    profile_key: Optional[str] = None
    engine: Optional[str] = None
    profile_name: Optional[str] = None
    target_label: Optional[str] = None
    requested_provider: Optional[str] = None
    requested_model: Optional[str] = None
    requested_engine: Optional[str] = None
    requested_profile_name: Optional[str] = None
    requested_profile_key: Optional[str] = None
    effective_provider: Optional[str] = None
    effective_model: Optional[str] = None
    actual_provider: Optional[str] = None
    actual_model: Optional[str] = None
    actual_engine: Optional[str] = None
    actual_profile_name: Optional[str] = None
    requested_target: Optional[dict] = None
    effective_target: Optional[dict] = None
    actual_target: Optional[dict] = None
    effective_provider_model: Optional[dict] = None
    actual_provider_model: Optional[dict] = None
    assigned_profile: Optional[dict] = None
    record_id: Optional[str] = None
    candidate_key: Optional[str] = None
    source_schedule_run_id: Optional[int] = None
    failure_category: Optional[str] = None
    error_code: Optional[str] = None
    dedupe_key: Optional[str] = None
    requested_at: Optional[str] = None
    processed_at: Optional[str] = None
    error_message: Optional[str] = None
    retry_count: int = 0
    applied_request_id: Optional[int] = None
    is_applied_to_record: bool = False
    save_outcome_status: Optional[str] = None
    save_outcome_reason: Optional[str] = None


class ArchiveRelatedRecord(BaseModel):
    """Snapshot of the current PlanRecord DB stored values for result comparison."""
    record_id: int
    category: Optional[str] = None
    tags: Optional[List[str]] = None
    summary: Optional[str] = None
    intent: Optional[str] = None
    trigger: Optional[str] = None
    scope: Optional[List[str]] = None
    analyzed_at: Optional[str] = None


class ArchiveAuditSnapshot(BaseModel):
    """One plan_archive_analysis_overwritten PlanEvent entry."""
    event_id: int
    prior_summary: Optional[str] = None
    prior_category: Optional[str] = None
    prior_tags: Optional[List[str]] = None
    analyzed_at: Optional[str] = None
    created_at: Optional[str] = None


class ArchiveLLMRequestDetail(ArchiveLLMRequestRow):
    """Full LLMRequest detail including prompt, result, raw_response, cli_options."""
    prompt: Optional[str] = None
    result: Optional[str] = None
    raw_response: Optional[str] = None
    cli_options: Optional[str] = None
    related_record: Optional[ArchiveRelatedRecord] = None
    audit_snapshots: List[ArchiveAuditSnapshot] = Field(default_factory=list)


class ArchiveLLMRequestListResponse(BaseModel):
    items: List[ArchiveLLMRequestRow] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50
    filters: dict = Field(default_factory=dict)


class ArchiveScheduleRunRow(BaseModel):
    """One TaskScheduleRun row for schedule history list."""
    id: int
    schedule_id: int
    status: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error_message: Optional[str] = None
    stop_reason: Optional[str] = None
    retry_count: int = 0


class ArchiveScheduleRunListResponse(BaseModel):
    items: List[ArchiveScheduleRunRow] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50
    filters: dict = Field(default_factory=dict)


class ArchiveExecutionAttemptRow(BaseModel):
    """One PlanArchiveExecutionAttempt row for execution attempt history list."""
    id: int
    job_id: int
    llm_request_id: Optional[int] = None
    record_id: Optional[int] = None
    attempt_index: int = 1
    status: str
    provider: Optional[str] = None
    model: Optional[str] = None
    engine: Optional[str] = None
    profile_name: Optional[str] = None
    requested_provider: Optional[str] = None
    requested_model: Optional[str] = None
    requested_engine: Optional[str] = None
    requested_profile_name: Optional[str] = None
    requested_profile_key: Optional[str] = None
    target_label: Optional[str] = None
    requested_target: Optional[dict] = None
    effective_target: Optional[dict] = None
    actual_target: Optional[dict] = None
    effective_provider_model: Optional[dict] = None
    actual_provider_model: Optional[dict] = None
    assigned_profile: Optional[dict] = None
    error_message: Optional[str] = None
    save_outcome_status: Optional[str] = None
    save_outcome_reason: Optional[str] = None
    requested_at: Optional[str] = None
    finished_at: Optional[str] = None


class ArchiveExecutionAttemptListResponse(BaseModel):
    items: List[ArchiveExecutionAttemptRow] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50
    filters: dict = Field(default_factory=dict)


class ArchiveScheduleDashboardResponse(BaseModel):
    """Archive schedule dashboard summary — all in one, full rows in separate endpoints."""
    schedule: Optional[PlanArchiveScheduleSnapshot] = None
    health: Optional[dict] = None
    retrieval_readiness: Optional[PlanArchiveDbReadinessResponse] = None
    queue_summary: ArchiveQueueSummary = Field(default_factory=ArchiveQueueSummary)
    recent_requests: List[ArchiveLLMRequestRow] = Field(default_factory=list)
    recent_schedule_runs: List[ArchiveScheduleRunRow] = Field(default_factory=list)
    recent_execution_attempts: List[ArchiveExecutionAttemptRow] = Field(default_factory=list)


class ArchiveSchedulePauseResumeResponse(BaseModel):
    schedule_id: int
    enabled: bool
    action: str


__all__ = [
    'PlanEventResponse',
    'PlanRecordResponse',
    'PlanRecordWithEventsResponse',
    'ImportArchivedResponse',
    'PlanArchiveHealthResponse',
    'PlanArchiveCategoryRepairRequest',
    'PlanArchiveCategoryRepairResponse',
    'PlanArchiveCategoryRepairItem',
    'PlanArchiveDbReadinessResponse',
    'PlanArchiveRetrievalQuery',
    'PlanArchiveRetrievalResult',
    'PlanArchiveChunkHit',
    'PlanArchiveFileRefHit',
    'PlanArchiveIndexRequest',
    'PlanArchiveIndexResponse',
    'PlanArchiveCrossRepoIndexRequest',
    'PlanArchiveCrossRepoIndexResponse',
    'PlanArchiveEmbeddingIndexRequest',
    'PlanArchiveEmbeddingIndexResponse',
    'PlanArchiveContextRequest',
    'PlanArchiveMetricsQuery',
    'PlanArchiveMetricsResponse',
    'PlanArchiveInsightBatchRequest',
    'PlanArchiveInsightBatchResponse',
    'PlanArchiveInsightReportResponse',
    'PlanArchiveInsightReportListResponse',
    'PlanArchiveInsightReportDetailResponse',
    'PlanArchiveInsightReviewUpdateRequest',
    'PlanArchiveInsightPromotePlanRequest',
    'PlanArchiveInsightPromotePlanResponse',
    'PlanArchiveDocPatchPreviewRequest',
    'PlanArchiveDocPatchApplyRequest',
    'PlanArchiveDocPatchProposalResponse',
    'PlanArchiveAnalyzeRequest',
    'PlanArchiveAnalyzeResponse',
    'PlanRecordsSyncResponse',
    'ArchiveCandidateRecordResponse',
    'ArchiveCandidateResponse',
    'ArchiveCandidateSummaryResponse',
    'ArchiveAnalyzeRequest',
    'ArchiveAnalyzeResponse',
    'PlanArchiveCandidateQueueRequest',
    'PlanArchiveCandidateQueueResponse',
    'PlanArchiveCandidateQueueSkipItem',
    'PlanArchiveCandidateQueueErrorItem',
    'PlanArchiveCandidatePreviewResponse',
    'PlanArchiveExecutionTarget',
    'PlanArchiveExecutionRunRequest',
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
    # Phase 4-A dashboard / list
    'ArchiveQueueSummary',
    'ArchiveLLMRequestRow',
    'ArchiveLLMRequestDetail',
    'ArchiveLLMRequestListResponse',
    'ArchiveScheduleRunRow',
    'ArchiveScheduleRunListResponse',
    'ArchiveExecutionAttemptRow',
    'ArchiveExecutionAttemptListResponse',
    'ArchiveScheduleDashboardResponse',
    'ArchiveSchedulePauseResumeResponse',
]
