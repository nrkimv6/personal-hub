"""
Plan Records API Routes
GET    /api/v1/plans/records         - 레코드 목록 (project, status, category, tags 필터, skip/limit)
GET    /api/v1/plans/records/{id}    - 레코드 상세 (events 포함)
GET    /api/v1/plans/records/{id}/content - raw_content 반환
POST   /api/v1/plans/records/{id}/restore - raw_content → 파일 복원
PATCH  /api/v1/plans/records/{id}/memo - 메모 업데이트 (draft/confirm/rollback)
POST   /api/v1/plans/records/sync   - 수동 동기화 (등록된 경로 전체 스캔)
POST   /api/v1/plans/records/import-archived - archived plan 일괄 DB 이관
POST   /api/v1/plans/records/ingest - 단건 archive ingest (wtools HTTP 호출용)
GET    /api/v1/plans/events         - 이벤트 목록 (타임라인용)
GET    /api/v1/plans/records/by-path - file_path로 get_or_create
"""
import logging
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import PROJECT_ROOT
from app.database import get_db
from app.modules.dev_runner.services.plan_record_service import PlanRecordService
from app.modules.dev_runner.services.plan_service import plan_service as _plan_service
from app.modules.dev_runner.services.plan_archive_context_service import PlanArchiveContextService
from app.modules.dev_runner.services.plan_archive_index_service import PlanArchiveIndexService
from app.modules.dev_runner.services.plan_archive_cross_repo_index_service import PlanArchiveCrossRepoIndexWriter
from app.modules.dev_runner.services.plan_archive_embedding_service import (
    PlanArchiveEmbeddingService,
)
from app.modules.dev_runner.services.plan_archive_metrics_service import PlanArchiveMetricsService
from app.modules.dev_runner.services.plan_archive_insight_service import (
    PlanArchiveInsightBatchQuery,
    PlanArchiveInsightService,
)
from app.modules.dev_runner.services.plan_archive_insight_review_service import (
    PlanArchiveInsightReviewService,
)
from app.modules.dev_runner.services.plan_archive_doc_patch_service import (
    PlanArchiveDocPatchService,
)
from app.modules.dev_runner.services.plan_archive_retrieval_service import (
    PlanArchiveRetrievalService,
    RetrievalQuery,
)
from app.modules.dev_runner.services.plan_archive_retrieval_readiness import (
    get_plan_archive_retrieval_readiness,
)
from app.modules.dev_runner.services.plan_archive_execution_readiness import (
    check_plan_archive_execution_readiness,
)
from app.modules.dev_runner.schemas import (
    PlanRecordResponse, PlanRecordWithEventsResponse,
    PlanEventResponse, MemoUpdateRequest, ImportArchivedResponse,
    PlanArchiveAnalyzeRequest, PlanArchiveAnalyzeResponse,
    PlanArchiveExecutionHistoryResponse,
    PlanArchiveExecutionRunRequest,
    PlanArchiveExecutionRunResponse,
    PlanArchiveExecutionSyncResponse,
    PlanArchiveHealthResponse,
    PlanArchiveContextRequest,
    PlanArchiveIndexRequest,
    PlanArchiveIndexResponse,
    PlanArchiveCrossRepoIndexRequest,
    PlanArchiveCrossRepoIndexResponse,
    PlanArchiveEmbeddingIndexRequest,
    PlanArchiveEmbeddingIndexResponse,
    PlanArchiveMetricsQuery,
    PlanArchiveMetricsResponse,
    PlanArchiveRetrievalQuery,
    PlanArchiveRetrievalResult,
    PlanArchiveInsightBatchRequest,
    PlanArchiveInsightBatchResponse,
    PlanArchiveInsightReportListResponse,
    PlanArchiveInsightReportDetailResponse,
    PlanArchiveInsightReviewUpdateRequest,
    PlanArchiveInsightPromotePlanRequest,
    PlanArchiveInsightPromotePlanResponse,
    PlanArchiveDocPatchPreviewRequest,
    PlanArchiveDocPatchApplyRequest,
    PlanArchiveDocPatchProposalResponse,
    PlanRecordsSyncResponse, ArchiveCandidateSummaryResponse,
    ArchiveAnalyzeRequest, ArchiveAnalyzeResponse,
    PlanRecordRelationResponse,
    PlanRecordRelationStatisticsResponse,
    PlanArchiveCandidateQueueRequest,
    PlanArchiveCandidateQueueResponse,
    PlanArchiveCandidatePreviewResponse,
    ArchiveScheduleDashboardResponse,
    ArchiveLLMRequestListResponse,
    ArchiveLLMRequestDetail,
    ArchiveScheduleRunListResponse,
    ArchiveExecutionAttemptListResponse,
    ArchiveSchedulePauseResumeResponse,
)


class IngestSingleRequest(BaseModel):
    """단건 ingest 요청 (wtools PS1 → HTTP 호출용)"""
    file_path: str
    project: Optional[str] = None
    raw_content: Optional[str] = None
    title: Optional[str] = None
    status: Optional[str] = None


class ReanalyzeRequest(BaseModel):
    """archive record LLM 재분석 요청."""
    provider: str
    model: str = ""
    profile_key: Optional[str] = None

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/plans", tags=["plan-records"])
router_admin = APIRouter(prefix="/api/v1/plans", tags=["plan-records-admin"])
_DEFAULT_PLANS_ARCHIVE_DIR = PROJECT_ROOT / ".worktrees" / "plans" / "docs" / "archive"


def _extract_profile_fields(cli: dict) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    profile_key = cli.get("profile_key") if isinstance(cli.get("profile_key"), str) else None
    target_label = cli.get("target_label") if isinstance(cli.get("target_label"), str) else None
    engine = None
    profile_name = None
    cps = cli.get("candidate_profiles")
    if isinstance(cps, list) and cps:
        first = cps[0] if isinstance(cps[0], dict) else None
        if first:
            engine = str(first.get("engine") or "").strip() or None
            profile_name = str(first.get("profile_name") or "").strip() or None
    return profile_key, engine, profile_name, target_label


@router.get("/records/by-path")
def get_record_by_path(file_path: str, include_claim: bool = False, db: Session = Depends(get_db)):
    """file_path로 레코드 get_or_create (메모 편집 시 진입점).

    include_claim=true 시 응답에 현재 active claim 요약을 포함한다.
    """
    svc = PlanRecordService(db)
    record = svc.get_or_create(file_path)
    db.commit()
    db.refresh(record)
    result = PlanRecordResponse.model_validate(record)
    if include_claim:
        claim_summary = svc.get_active_claim(file_path)
        return {**result.model_dump(), "execution_claim": claim_summary}
    return result


@router.get("/records/guide-status")
def get_guide_status(include_history: bool = False, db: Session = Depends(get_db)):
    """가이드별 staleness 정보 반환 (pending archive 건수 포함)"""
    svc = PlanRecordService(db)
    return svc.get_guide_status(include_history=include_history)


@router.get("/records/archive-health", response_model=PlanArchiveHealthResponse)
def get_archive_health(include_temp: bool = False, db: Session = Depends(get_db)):
    """Plan Archive scheduler health summary."""
    svc = PlanRecordService(db)
    return svc.get_plan_archive_health(include_temp=include_temp)


# ── Phase 4-A: dashboard + list endpoints ────────────────────────────────────

@router.get("/records/archive-schedule-dashboard", response_model=ArchiveScheduleDashboardResponse)
def get_archive_schedule_dashboard(db: Session = Depends(get_db)):
    """archive schedule 운영 대시보드 — summary + recent N=20 rows."""
    from app.modules.dev_runner.services.plan_record_service import PlanRecordService as _PRS
    from app.modules.dev_runner.services.plan_archive_retrieval_readiness import get_plan_archive_retrieval_readiness
    from app.modules.claude_worker.models.llm_request import LLMRequest
    from app.models.plan_archive_execution import PlanArchiveExecutionAttempt, PlanArchiveExecutionJob
    from app.models.task_schedule import TaskScheduleRun, TaskSchedule
    from app.modules.dev_runner.schemas import (
        ArchiveQueueSummary, ArchiveLLMRequestRow, ArchiveScheduleRunRow,
        ArchiveExecutionAttemptRow, PlanArchiveScheduleSnapshot,
    )
    from datetime import timedelta
    from sqlalchemy import func as sqlfunc

    svc = _PRS(db)
    health_raw = svc.get_plan_archive_health()

    schedule_snap = health_raw.get("plan_archive_schedule")
    schedule_obj = None
    if schedule_snap:
        schedule_obj = PlanArchiveScheduleSnapshot(**schedule_snap) if isinstance(schedule_snap, dict) else schedule_snap

    readiness = get_plan_archive_retrieval_readiness(db)

    # queue summary
    now = datetime.utcnow()
    cutoff_24h = now - timedelta(hours=24)
    req_q = db.query(LLMRequest).filter(
        LLMRequest.caller_type == "plan_archive_analyze",
        LLMRequest.deleted_at.is_(None),
    )
    completed_24h = req_q.filter(
        LLMRequest.status == "completed",
        LLMRequest.processed_at >= cutoff_24h,
    ).count()
    failures_by_cat = dict(
        db.query(LLMRequest.failure_category, sqlfunc.count(LLMRequest.id))
        .filter(
            LLMRequest.caller_type == "plan_archive_analyze",
            LLMRequest.status == "failed",
            LLMRequest.failure_category.isnot(None),
            LLMRequest.deleted_at.is_(None),
        )
        .group_by(LLMRequest.failure_category)
        .all()
    )
    queue_summary = ArchiveQueueSummary(
        pending=health_raw.get("pending_or_processing_requests", 0),
        processing=0,
        failed=health_raw.get("failed_requests", 0),
        completed_24h=completed_24h,
        recent_failures_by_category=failures_by_cat,
    )

    # recent requests N=20
    recent_reqs = (
        req_q.order_by(LLMRequest.requested_at.desc()).limit(20).all()
    )
    import json as _json_recent

    def _parse_cli_opt_recent(r):
        try:
            return _json_recent.loads(r.cli_options) if r.cli_options else {}
        except Exception:
            return {}

    recent_request_rows: list[ArchiveLLMRequestRow] = []
    for r in recent_reqs:
        cli = _parse_cli_opt_recent(r)
        pk, eng, pn, tl = _extract_profile_fields(cli)
        recent_request_rows.append(
            ArchiveLLMRequestRow(
                id=r.id,
                status=r.status,
                provider=r.provider or "",
                model=r.model or "",
                profile_key=pk,
                engine=eng,
                profile_name=pn,
                target_label=tl,
                record_id=r.caller_id,
                failure_category=r.failure_category,
                dedupe_key=r.dedupe_key,
                requested_at=r.requested_at.isoformat() if r.requested_at else None,
                processed_at=r.processed_at.isoformat() if r.processed_at else None,
                error_message=r.error_message,
                retry_count=r.retry_count or 0,
            )
        )

    # recent schedule runs N=20
    schedule = db.query(TaskSchedule).filter(
        TaskSchedule.target_type == TaskSchedule.TARGET_TYPE_PLAN_ARCHIVE_ANALYZE
    ).order_by(TaskSchedule.id.asc()).first()
    recent_run_rows: list = []
    if schedule:
        recent_runs = (
            db.query(TaskScheduleRun)
            .filter(TaskScheduleRun.schedule_id == schedule.id)
            .order_by(TaskScheduleRun.started_at.desc())
            .limit(20)
            .all()
        )
        recent_run_rows = [
            ArchiveScheduleRunRow(
                id=r.id,
                schedule_id=r.schedule_id,
                status=r.status,
                started_at=r.started_at.isoformat() if r.started_at else None,
                finished_at=r.finished_at.isoformat() if r.finished_at else None,
                error_message=r.error_message,
                stop_reason=r.stop_reason,
                retry_count=r.retry_count or 0,
            )
            for r in recent_runs
        ]

    # recent execution attempts N=20
    recent_attempts = (
        db.query(PlanArchiveExecutionAttempt)
        .order_by(PlanArchiveExecutionAttempt.created_at.desc())
        .limit(20)
        .all()
    )
    recent_attempt_rows = [
        ArchiveExecutionAttemptRow(
            id=a.id,
            job_id=a.job_id,
            llm_request_id=a.llm_request_id,
            record_id=a.job.plan_record_id if a.job else None,
            attempt_index=a.attempt_index,
            status=a.status,
            provider=a.provider,
            model=a.model,
            engine=a.engine,
            profile_name=a.profile_name,
            error_message=a.error_message,
            requested_at=a.requested_at.isoformat() if a.requested_at else None,
            finished_at=a.finished_at.isoformat() if a.finished_at else None,
        )
        for a in recent_attempts
    ]

    health_summary = {
        k: v for k, v in health_raw.items()
        if k not in ("plan_archive_schedule", "latest_failed_request")
    }

    return ArchiveScheduleDashboardResponse(
        schedule=schedule_obj,
        health=health_summary,
        retrieval_readiness=readiness,
        queue_summary=queue_summary,
        recent_requests=recent_request_rows,
        recent_schedule_runs=recent_run_rows,
        recent_execution_attempts=recent_attempt_rows,
    )


@router.get("/records/archive-llm-requests", response_model=ArchiveLLMRequestListResponse)
def list_archive_llm_requests(
    status: Optional[str] = None,
    category: Optional[str] = None,
    record_id: Optional[str] = None,
    source_schedule_run_id: Optional[int] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    page: int = 1,
    page_size: int = 50,
    db: Session = Depends(get_db),
):
    """LLMRequest 목록 — status/category/record_id/시간 범위 필터, pagination."""
    from app.modules.claude_worker.models.llm_request import LLMRequest
    from app.modules.dev_runner.schemas import ArchiveLLMRequestRow

    if page_size > 200:
        raise HTTPException(status_code=422, detail="page_size 최대 200")
    if page < 1:
        page = 1

    q = db.query(LLMRequest).filter(
        LLMRequest.caller_type == "plan_archive_analyze",
        LLMRequest.deleted_at.is_(None),
    )
    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        if statuses:
            q = q.filter(LLMRequest.status.in_(statuses))
    if category:
        q = q.filter(LLMRequest.failure_category == category)
    if record_id:
        q = q.filter(LLMRequest.caller_id == str(record_id))
    if since:
        q = q.filter(LLMRequest.requested_at >= since)
    if until:
        q = q.filter(LLMRequest.requested_at <= until)

    total = q.count()
    items = q.order_by(LLMRequest.requested_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

    import json as _json_list

    def _parse_cli_opt(r):
        try:
            return _json_list.loads(r.cli_options) if r.cli_options else {}
        except Exception:
            return {}

    rows: list[ArchiveLLMRequestRow] = []
    for r in items:
        cli = _parse_cli_opt(r)
        pk, eng, pn, tl = _extract_profile_fields(cli)
        rows.append(
            ArchiveLLMRequestRow(
                id=r.id,
                status=r.status,
                provider=r.provider or "",
                model=r.model or "",
                profile_key=pk,
                engine=eng,
                profile_name=pn,
                target_label=tl,
                record_id=r.caller_id,
                candidate_key=cli.get("candidate_key"),
                source_schedule_run_id=cli.get("source_schedule_run_id"),
                failure_category=r.failure_category,
                dedupe_key=r.dedupe_key,
                requested_at=r.requested_at.isoformat() if r.requested_at else None,
                processed_at=r.processed_at.isoformat() if r.processed_at else None,
                error_message=r.error_message,
                retry_count=r.retry_count or 0,
            )
        )

    return ArchiveLLMRequestListResponse(
        items=rows,
        total=total,
        page=page,
        page_size=page_size,
        filters={
            "status": status,
            "category": category,
            "record_id": record_id,
            "since": since.isoformat() if since else None,
            "until": until.isoformat() if until else None,
        },
    )


@router.get("/records/archive-llm-requests/{request_id}", response_model=ArchiveLLMRequestDetail)
def get_archive_llm_request_detail(request_id: int, db: Session = Depends(get_db)):
    """LLMRequest 상세 — prompt, result, raw_response, cli_options 포함."""
    from app.modules.claude_worker.models.llm_request import LLMRequest
    from app.models.plan_record import PlanEvent

    r = db.query(LLMRequest).filter(
        LLMRequest.id == request_id,
        LLMRequest.caller_type == "plan_archive_analyze",
        LLMRequest.deleted_at.is_(None),
    ).first()
    if not r:
        raise HTTPException(status_code=404, detail="LLMRequest not found")

    # applied_request_id: plan_archive_analysis_saved 이벤트에서 derive
    applied_request_id = None
    is_applied = False
    try:
        caller_id_int = int(r.caller_id)
        saved_event = (
            db.query(PlanEvent)
            .filter(
                PlanEvent.plan_record_id == caller_id_int,
                PlanEvent.event_type == "plan_archive_analysis_saved",
            )
            .order_by(PlanEvent.created_at.desc())
            .first()
        )
        if saved_event and saved_event.detail:
            import json as _json
            detail = _json.loads(saved_event.detail) if isinstance(saved_event.detail, str) else saved_event.detail
            applied_request_id = detail.get("request_id")
            is_applied = (applied_request_id == r.id)
    except (ValueError, TypeError):
        pass

    # profile identity from cli_options (best-effort)
    import json as _json_cli
    try:
        cli = _json_cli.loads(r.cli_options) if r.cli_options else {}
    except Exception:
        cli = {}
    profile_key = cli.get("profile_key") if isinstance(cli.get("profile_key"), str) else None
    target_label = cli.get("target_label") if isinstance(cli.get("target_label"), str) else None
    engine = None
    profile_name = None
    cps = cli.get("candidate_profiles")
    if isinstance(cps, list) and cps:
        first = cps[0] if isinstance(cps[0], dict) else None
        if first:
            engine = str(first.get("engine") or "").strip() or None
            profile_name = str(first.get("profile_name") or "").strip() or None

    # related_record: current DB stored values from PlanRecord
    from app.models.plan_record import PlanRecord as PlanRecordModel, PlanEvent as PlanEventModel
    from app.modules.dev_runner.schemas import ArchiveRelatedRecord, ArchiveAuditSnapshot
    import json as _json2

    related_record = None
    audit_snapshots = []
    try:
        caller_id_int = int(r.caller_id)
        pr = db.query(PlanRecordModel).filter(PlanRecordModel.id == caller_id_int).first()
        if pr:
            related_record = ArchiveRelatedRecord(
                record_id=pr.id,
                category=pr.category,
                tags=pr.tags if isinstance(pr.tags, list) else (_json2.loads(pr.tags) if pr.tags else None),
                summary=pr.summary,
                intent=pr.intent,
                trigger=pr.trigger,
                scope=_json2.loads(pr.scope) if pr.scope and isinstance(pr.scope, str) else pr.scope,
                analyzed_at=pr.analyzed_at.isoformat() if hasattr(pr, "analyzed_at") and pr.analyzed_at else None,
            )
        # audit_snapshots: plan_archive_analysis_overwritten events
        overwritten_events = (
            db.query(PlanEventModel)
            .filter(
                PlanEventModel.plan_record_id == caller_id_int,
                PlanEventModel.event_type == "plan_archive_analysis_overwritten",
            )
            .order_by(PlanEventModel.created_at.desc())
            .limit(10)
            .all()
        )
        for ev in overwritten_events:
            d = _json2.loads(ev.detail) if isinstance(ev.detail, str) else (ev.detail or {})
            audit_snapshots.append(ArchiveAuditSnapshot(
                event_id=ev.id,
                prior_summary=d.get("prior_summary"),
                prior_category=d.get("prior_category"),
                prior_tags=d.get("prior_tags"),
                analyzed_at=d.get("analyzed_at"),
                created_at=ev.created_at.isoformat() if ev.created_at else None,
            ))
    except (ValueError, TypeError):
        pass

    return ArchiveLLMRequestDetail(
        id=r.id,
        status=r.status,
        provider=r.provider or "",
        model=r.model or "",
        profile_key=profile_key,
        engine=engine,
        profile_name=profile_name,
        target_label=target_label,
        record_id=r.caller_id,
        failure_category=r.failure_category,
        dedupe_key=r.dedupe_key,
        requested_at=r.requested_at.isoformat() if r.requested_at else None,
        processed_at=r.processed_at.isoformat() if r.processed_at else None,
        error_message=r.error_message,
        retry_count=r.retry_count or 0,
        prompt=r.prompt,
        result=r.result,
        raw_response=r.raw_response,
        cli_options=r.cli_options,
        applied_request_id=applied_request_id,
        is_applied_to_record=is_applied,
        related_record=related_record,
        audit_snapshots=audit_snapshots,
    )


@router.get("/records/archive-schedule-runs", response_model=ArchiveScheduleRunListResponse)
def list_archive_schedule_runs(
    status: Optional[str] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    page: int = 1,
    page_size: int = 50,
    db: Session = Depends(get_db),
):
    """TaskScheduleRun history — status/시간 범위 필터, pagination."""
    from app.models.task_schedule import TaskScheduleRun, TaskSchedule
    from app.modules.dev_runner.schemas import ArchiveScheduleRunRow

    if page_size > 200:
        raise HTTPException(status_code=422, detail="page_size 최대 200")
    if page < 1:
        page = 1

    schedule = db.query(TaskSchedule).filter(
        TaskSchedule.target_type == TaskSchedule.TARGET_TYPE_PLAN_ARCHIVE_ANALYZE
    ).order_by(TaskSchedule.id.asc()).first()
    if not schedule:
        return ArchiveScheduleRunListResponse(total=0)

    q = db.query(TaskScheduleRun).filter(TaskScheduleRun.schedule_id == schedule.id)
    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        if statuses:
            q = q.filter(TaskScheduleRun.status.in_(statuses))
    if since:
        q = q.filter(TaskScheduleRun.started_at >= since)
    if until:
        q = q.filter(TaskScheduleRun.started_at <= until)

    total = q.count()
    items = q.order_by(TaskScheduleRun.started_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

    return ArchiveScheduleRunListResponse(
        items=[
            ArchiveScheduleRunRow(
                id=r.id,
                schedule_id=r.schedule_id,
                status=r.status,
                started_at=r.started_at.isoformat() if r.started_at else None,
                finished_at=r.finished_at.isoformat() if r.finished_at else None,
                error_message=r.error_message,
                stop_reason=r.stop_reason,
                retry_count=r.retry_count or 0,
            )
            for r in items
        ],
        total=total,
        page=page,
        page_size=page_size,
        filters={
            "status": status,
            "since": since.isoformat() if since else None,
            "until": until.isoformat() if until else None,
        },
    )


@router.get("/records/archive-execution-attempts", response_model=ArchiveExecutionAttemptListResponse)
def list_archive_execution_attempts(
    status: Optional[str] = None,
    record_id: Optional[int] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    page: int = 1,
    page_size: int = 50,
    db: Session = Depends(get_db),
):
    """PlanArchiveExecutionAttempt history — status/record_id/시간 범위 필터, pagination."""
    from app.models.plan_archive_execution import PlanArchiveExecutionAttempt, PlanArchiveExecutionJob
    from app.modules.dev_runner.schemas import ArchiveExecutionAttemptRow

    if page_size > 200:
        raise HTTPException(status_code=422, detail="page_size 최대 200")
    if page < 1:
        page = 1

    q = db.query(PlanArchiveExecutionAttempt)
    if record_id is not None:
        q = q.join(PlanArchiveExecutionJob, PlanArchiveExecutionAttempt.job_id == PlanArchiveExecutionJob.id).filter(
            PlanArchiveExecutionJob.plan_record_id == record_id
        )
    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        if statuses:
            q = q.filter(PlanArchiveExecutionAttempt.status.in_(statuses))
    if since:
        q = q.filter(PlanArchiveExecutionAttempt.created_at >= since)
    if until:
        q = q.filter(PlanArchiveExecutionAttempt.created_at <= until)

    total = q.count()
    items = q.order_by(PlanArchiveExecutionAttempt.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

    return ArchiveExecutionAttemptListResponse(
        items=[
            ArchiveExecutionAttemptRow(
                id=a.id,
                job_id=a.job_id,
                llm_request_id=a.llm_request_id,
                record_id=a.job.plan_record_id if a.job else None,
                attempt_index=a.attempt_index,
                status=a.status,
                provider=a.provider,
                model=a.model,
                engine=a.engine,
                profile_name=a.profile_name,
                error_message=a.error_message,
                requested_at=a.requested_at.isoformat() if a.requested_at else None,
                finished_at=a.finished_at.isoformat() if a.finished_at else None,
            )
            for a in items
        ],
        total=total,
        page=page,
        page_size=page_size,
        filters={
            "status": status,
            "record_id": record_id,
            "since": since.isoformat() if since else None,
            "until": until.isoformat() if until else None,
        },
    )


@router_admin.post("/records/archive-schedule/pause", response_model=ArchiveSchedulePauseResumeResponse)
def pause_archive_schedule(db: Session = Depends(get_db)):
    """archive schedule을 pause한다 (enabled=False). admin 전용."""
    schedule = _get_plan_archive_schedule_or_404(db)
    schedule.enabled = False
    db.commit()
    return ArchiveSchedulePauseResumeResponse(schedule_id=schedule.id, enabled=False, action="pause")


@router_admin.post("/records/archive-schedule/resume", response_model=ArchiveSchedulePauseResumeResponse)
def resume_archive_schedule(db: Session = Depends(get_db)):
    """archive schedule을 resume한다 (enabled=True). admin 전용."""
    schedule = _get_plan_archive_schedule_or_404(db)
    schedule.enabled = True
    db.commit()
    return ArchiveSchedulePauseResumeResponse(schedule_id=schedule.id, enabled=True, action="resume")


def _get_plan_archive_schedule_or_404(db: Session):
    """6101 admin frontend must call this through the admin API proxy, not the public router."""
    from app.models.task_schedule import TaskSchedule

    schedule = db.query(TaskSchedule).filter(
        TaskSchedule.target_type == TaskSchedule.TARGET_TYPE_PLAN_ARCHIVE_ANALYZE
    ).order_by(TaskSchedule.id.asc()).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="Plan archive schedule not found")
    return schedule


def _to_retrieval_query(req: PlanArchiveRetrievalQuery) -> RetrievalQuery:
    return RetrievalQuery(
        q=req.q,
        date_from=req.date_from,
        date_to=req.date_to,
        category=req.category,
        tags=req.tags,
        intent=req.intent,
        scope=req.scope,
        path=req.path,
        repo_key=req.repo_key,
        relation_type=req.relation_type,
        semantic_cluster_id=req.semantic_cluster_id,
        limit=req.limit,
    )


def _serialize_retrieval_result(result: dict) -> dict:
    serialized = {"total": result.get("total", 0), "results": []}
    for hit in result.get("results", []):
        plan = hit["plan"]
        serialized["results"].append(
            {
                "plan": {
                    "id": plan.id,
                    "filename_hash": plan.filename_hash,
                    "file_path": plan.file_path,
                    "title": plan.title,
                    "status": plan.status,
                    "category": plan.category,
                    "tags": plan.tags,
                    "summary": plan.summary,
                    "intent": plan.intent,
                    "scope": plan.scope,
                    "archived_at": plan.archived_at,
                },
                "score": hit["score"],
                "score_detail": hit["score_detail"],
                "chunks": hit["chunks"],
                "file_refs": hit["file_refs"],
            }
        )
    return serialized


def _ensure_retrieval_db_ready(db: Session) -> None:
    readiness = get_plan_archive_retrieval_readiness(db)
    if readiness["ok"]:
        return
    raise HTTPException(
        status_code=503,
        detail={
            "message": "Plan Archive retrieval DB is not ready",
            "retrieval_db_readiness": readiness,
        },
    )


def _ensure_execution_db_ready(db: Session) -> dict:
    readiness = check_plan_archive_execution_readiness(db)
    if readiness["ok"]:
        return readiness
    raise HTTPException(
        status_code=503,
        detail={
            "message": "Plan Archive execution DB is not ready",
            "execution_db_readiness": readiness,
            "missing_tables": readiness["missing_tables"],
        },
    )


@router.post("/retrieval/search", response_model=PlanArchiveRetrievalResult)
def search_archive(req: PlanArchiveRetrievalQuery, db: Session = Depends(get_db)):
    """Search archived plans through metadata, lexical chunks, and file refs."""
    _ensure_retrieval_db_ready(db)
    svc = PlanArchiveRetrievalService(db)
    return _serialize_retrieval_result(svc.search(_to_retrieval_query(req)))


@router.post("/retrieval/context")
def build_archive_context(req: PlanArchiveContextRequest, db: Session = Depends(get_db)):
    """Build bounded LLM context from retrieval results."""
    _ensure_retrieval_db_ready(db)
    retrieval = PlanArchiveRetrievalService(db).search(_to_retrieval_query(req))
    context = PlanArchiveContextService().assemble(
        retrieval,
        token_budget=req.token_budget,
        include_raw=req.include_raw,
    )
    return context


@router.post("/retrieval/metrics", response_model=PlanArchiveMetricsResponse)
def get_archive_metrics(req: PlanArchiveMetricsQuery, db: Session = Depends(get_db)):
    """Return follow-up and file-ref metrics for archive retrieval."""
    _ensure_retrieval_db_ready(db)
    return PlanArchiveMetricsService(db).calculate(_to_retrieval_query(req))


@router.post("/insights/batch", response_model=PlanArchiveInsightBatchResponse)
def queue_archive_insight_batch(req: PlanArchiveInsightBatchRequest, db: Session = Depends(get_db)):
    """Preview or queue period/group Plan Archive insight generation."""
    if req.date_from and req.date_to and req.date_from > req.date_to:
        raise HTTPException(status_code=400, detail="date_from must be before date_to")
    query = PlanArchiveInsightBatchQuery(
        date_from=req.date_from,
        date_to=req.date_to,
        grouping=req.grouping,
        category=req.category,
        path=req.path,
        limit=req.limit,
        token_budget=req.token_budget,
    )
    return PlanArchiveInsightService(db).preview_or_enqueue(
        query,
        apply=req.apply,
        force=req.force,
        provider=req.provider,
        model=req.model,
        requested_by="api",
    )


@router.get("/insights/reports", response_model=PlanArchiveInsightReportListResponse)
def list_archive_insight_reports(
    status: Optional[str] = None,
    review_status: Optional[str] = None,
    grouping: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    return PlanArchiveInsightReviewService(db).list_reports(
        status=status,
        review_status=review_status,
        grouping=grouping,
        skip=skip,
        limit=limit,
    )


@router.get("/insights/reports/{report_id}", response_model=PlanArchiveInsightReportDetailResponse)
def get_archive_insight_report(report_id: int, db: Session = Depends(get_db)):
    result = PlanArchiveInsightReviewService(db).get_detail(report_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return result


@router.get("/insights/reports/{report_id}/evidence/{source_type}/{source_id}")
def get_archive_insight_evidence(report_id: int, source_type: str, source_id: int, db: Session = Depends(get_db)):
    try:
        result = PlanArchiveInsightReviewService(db).get_evidence_source(report_id, source_type, source_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Evidence not found")
    return result


@router.patch("/insights/reports/{report_id}", response_model=PlanArchiveInsightReportDetailResponse)
def update_archive_insight_review(
    report_id: int,
    req: PlanArchiveInsightReviewUpdateRequest,
    db: Session = Depends(get_db),
):
    try:
        return PlanArchiveInsightReviewService(db).update_review(
            report_id,
            req.review_status,
            req.review_note,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Report not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/insights/reports/{report_id}/promote-plan", response_model=PlanArchiveInsightPromotePlanResponse)
def promote_archive_insight_plan(
    report_id: int,
    req: PlanArchiveInsightPromotePlanRequest,
    db: Session = Depends(get_db),
):
    try:
        return PlanArchiveInsightReviewService(db).promote_plan_candidate(
            report_id,
            req.candidate_index,
            confirm=req.confirm,
            title=req.title,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Report not found") from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        detail = str(exc)
        status_code = 409 if detail == "CANDIDATE_NOT_FOUND" else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc


@router.post("/doc-patches/preview", response_model=PlanArchiveDocPatchProposalResponse)
def preview_archive_doc_patch(req: PlanArchiveDocPatchPreviewRequest, db: Session = Depends(get_db)):
    try:
        return PlanArchiveDocPatchService(db).preview(
            record_id=req.record_id,
            insight_report_id=req.insight_report_id,
            target_path=req.target_path,
            patch_text=req.patch_text,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/doc-patches/{proposal_id}/apply", response_model=PlanArchiveDocPatchProposalResponse)
def apply_archive_doc_patch(
    proposal_id: int,
    req: PlanArchiveDocPatchApplyRequest,
    db: Session = Depends(get_db),
):
    try:
        return PlanArchiveDocPatchService(db).apply(proposal_id, confirm=req.confirm)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/doc-patches/{proposal_id}/reject", response_model=PlanArchiveDocPatchProposalResponse)
def reject_archive_doc_patch(proposal_id: int, db: Session = Depends(get_db)):
    try:
        return PlanArchiveDocPatchService(db).reject(proposal_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/records/index", response_model=PlanArchiveIndexResponse)
def index_archive_records(req: PlanArchiveIndexRequest, db: Session = Depends(get_db)):
    """Index archived plan records. Default is dry-run; set apply=true to write."""
    svc = PlanArchiveIndexService(db, PROJECT_ROOT)
    dry_run = not req.apply
    if req.record_id:
        try:
            svc.index_record(req.record_id, force=req.force, dry_run=dry_run)
            if not dry_run:
                db.commit()
            return {"dry_run": dry_run, "indexed": 1, "failed": 0, "skipped": 0, "run_id": None, "errors": []}
        except Exception as exc:
            if not dry_run:
                db.rollback()
            return {"dry_run": dry_run, "indexed": 0, "failed": 1, "skipped": 0, "run_id": None, "errors": [str(exc)]}
    result = svc.index_archived_records(limit=req.limit, force=req.force, since=req.since, dry_run=dry_run)
    if not dry_run:
        db.commit()
    return {"run_id": None, **result}


@router.post("/retrieval/cross-repo/index", response_model=PlanArchiveCrossRepoIndexResponse)
def index_cross_repo_archive(req: PlanArchiveCrossRepoIndexRequest, db: Session = Depends(get_db)):
    """Collect cross-repo git evidence for one archive record."""
    _ensure_retrieval_db_ready(db)
    dry_run = not req.apply
    try:
        result = PlanArchiveCrossRepoIndexWriter(db).index_record(
            req.record_id,
            max_commits=req.max_commits,
            dry_run=dry_run,
        )
        if not dry_run:
            db.commit()
        return result
    except Exception as exc:
        if not dry_run:
            db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/retrieval/embeddings/index", response_model=PlanArchiveEmbeddingIndexResponse)
def index_archive_embeddings(req: PlanArchiveEmbeddingIndexRequest, db: Session = Depends(get_db)):
    """Backfill semantic embeddings for archived plan chunks."""
    try:
        config = PlanArchiveEmbeddingService.resolve_config(
            provider=req.provider,
            model=req.model,
            dimension=req.dimension,
            batch_limit=req.limit,
            timeout_seconds=req.timeout_seconds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    svc = PlanArchiveEmbeddingService(db, config=config)
    dry_run = not req.apply
    result = svc.index_embeddings(limit=req.limit, force=req.force, dry_run=dry_run)
    if not dry_run:
        db.commit()
    return {
        **result,
        "provider": config.provider,
        "model": config.model,
        "dimension": config.dimension,
    }


@router.get("/records", response_model=list[PlanRecordResponse])
def list_records(
    project: Optional[str] = None,
    status: Optional[str] = None,
    category: Optional[str] = None,
    tags: Optional[str] = None,
    q: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    skip: int = 0,
    limit: int = 50,
    deep: bool = False,
    include_temp: bool = False,
    db: Session = Depends(get_db),
):
    tags_list = [t.strip() for t in tags.split(",")] if tags else None
    svc = PlanRecordService(db)
    return svc.list_records(
        project=project, status=status, category=category, tags=tags_list,
        q=q, date_from=date_from, date_to=date_to,
        skip=skip, limit=limit, deep=deep, exclude_temp=not include_temp,
    )


@router.post("/records/archive-executions/run", response_model=PlanArchiveExecutionRunResponse)
def run_archive_executions(req: PlanArchiveExecutionRunRequest, db: Session = Depends(get_db)):
    """Queue Plan Archive analysis jobs for selected records or current backlog."""
    from app.models.plan_record import PlanRecord
    from app.modules.dev_runner.services.plan_archive_execution_service import (
        PlanArchiveExecutionService,
    )

    _ensure_execution_db_ready(db)
    svc = PlanArchiveExecutionService(db)
    if req.record_ids:
        records = db.query(PlanRecord).filter(PlanRecord.id.in_(req.record_ids)).all()
    else:
        records = (
            db.query(PlanRecord)
            .filter(PlanRecord.archived_at.isnot(None), PlanRecord.llm_processed_at.is_(None))
            .order_by(PlanRecord.archived_at.asc())
            .limit(50)
            .all()
        )
    selected_targets = [t.model_dump() for t in req.selected_targets] if req.selected_targets else None
    selected_profiles = [item.model_dump() for item in req.selected_profiles] if req.selected_profiles else None
    result = svc.enqueue_records(
        records,
        trigger_source="manual:plan_archive_analyze",
        selected_targets=selected_targets,
        selected_profiles=selected_profiles,
        requested_by="api",
    )
    db.commit()
    return result


@router.post("/records/archive-executions/sync", response_model=PlanArchiveExecutionSyncResponse)
def sync_archive_executions(db: Session = Depends(get_db)):
    """Reconcile execution job/attempt rows from current LLMRequest state."""
    from app.modules.dev_runner.services.plan_archive_execution_service import (
        PlanArchiveExecutionService,
    )

    registered = _plan_service.list_registered_paths()
    paths = [{"path": r.path, "type": r.path_type} for r in registered]
    record_sync = PlanRecordService(db).sync_all(paths)
    readiness = check_plan_archive_execution_readiness(db)
    if not readiness["ok"]:
        errors = list(record_sync.get("errors") or [])
        errors.append(
            "Plan Archive execution DB is not ready: missing_tables="
            + ",".join(readiness["missing_tables"])
        )
        return {
            "updated": 0,
            "checked": 0,
            "created": record_sync.get("created", 0),
            "record_updated": record_sync.get("updated", 0),
            "missing": record_sync.get("missing", 0),
            "errors": errors,
        }
    result = PlanArchiveExecutionService(db).sync()
    result["created"] = record_sync.get("created", 0)
    result["record_updated"] = record_sync.get("updated", 0)
    result["missing"] = record_sync.get("missing", 0)
    result["errors"] = list(result.get("errors") or []) + list(record_sync.get("errors") or [])
    db.commit()
    return result


@router.get("/records/archive-executions/history", response_model=PlanArchiveExecutionHistoryResponse)
def list_archive_execution_history(
    record_id: Optional[int] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    from app.modules.dev_runner.services.plan_archive_execution_service import (
        PlanArchiveExecutionService,
    )

    items = PlanArchiveExecutionService(db).history(record_id=record_id, limit=limit)
    return {
        "items": items,
        "total": len(items),
        "limit": max(1, min(limit, 200)),
        "record_id": record_id,
    }


@router.get("/records/archive-candidates", response_model=ArchiveCandidateSummaryResponse)
def list_archive_candidates(
    include_temp: bool = False,
    skip: int = 0,
    limit: int = 50,
    state: Optional[str] = None,
    q: Optional[str] = None,
    eligible: Optional[bool] = None,
    archived_after: Optional[str] = None,
    archived_before: Optional[str] = None,
    last_attempt_after: Optional[str] = None,
    last_attempt_before: Optional[str] = None,
    attempt_state: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """archive 파일과 DB 레코드를 합친 실행/이관 후보 목록.

    limit 기본값 50, 최대 200. 초과 시 422.
    attempt_state: never_attempted / in_progress / last_failed / last_succeeded
    """
    from datetime import datetime as dt
    if limit > 200:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="limit must be <= 200")

    def _parse_dt(s: Optional[str]):
        if not s:
            return None
        try:
            return dt.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None

    registered = _plan_service.list_registered_paths()
    paths = [{"path": r.path, "type": r.path_type} for r in registered]
    svc = PlanRecordService(db)
    return svc.list_archive_candidates(
        paths,
        include_temp=include_temp,
        skip=skip,
        limit=limit,
        state=state,
        q=q,
        eligible=eligible,
        archived_after=_parse_dt(archived_after),
        archived_before=_parse_dt(archived_before),
        last_attempt_after=_parse_dt(last_attempt_after),
        last_attempt_before=_parse_dt(last_attempt_before),
        attempt_state=attempt_state,
    )


@router_admin.post("/records/archive-candidates/queue", response_model=PlanArchiveCandidateQueueResponse)
def queue_archive_candidates(
    req: PlanArchiveCandidateQueueRequest,
    db: Session = Depends(get_db),
):
    """archive 후보를 큐에 등록한다.

    - file_only candidate (candidate_keys): import 후 큐잉
    - 기존 record (record_ids): 바로 큐잉
    - db_only: 파일 내용이 없으면 not_queueable 반환
    admin(:8001) 전용 mutation.
    """
    from app.modules.dev_runner.services.plan_archive_execution_service import (
        PlanArchiveExecutionService,
    )
    registered = _plan_service.list_registered_paths()
    paths = [{"path": r.path, "type": r.path_type} for r in registered]
    svc = PlanRecordService(db)
    exec_svc = PlanArchiveExecutionService(db)
    selected_targets = [t.model_dump() for t in req.selected_targets]

    response = PlanArchiveCandidateQueueResponse()

    # 1. candidate_keys (file_only import → queue)
    for key in req.candidate_keys:
        try:
            import_result = svc.import_archive_candidate(key, paths)
        except Exception as exc:
            response.errors.append({"candidate_key": key, "error": str(exc)})
            continue
        if import_result.get("not_queueable"):
            response.skipped.append({
                "candidate_key": key,
                "reason": import_result["not_queueable"],
            })
            continue
        record = import_result["record"]
        if import_result.get("created"):
            response.imported += 1
        try:
            result = exec_svc.enqueue_record(
                record,
                trigger_source="api:archive-candidates/queue",
                selected_targets=selected_targets,
                requested_by="api",
                candidate_key=key,
            )
        except Exception as exc:
            response.errors.append({"candidate_key": key, "error": str(exc)})
            continue
        status_key = result.get("status_key")
        if status_key == "queued":
            response.queued += 1
            if result.get("job_id"):
                response.job_ids.append(result["job_id"])
            for rid in result.get("request_ids") or ([result["request_id"]] if result.get("request_id") else []):
                response.request_ids.append(rid)
        elif status_key in ("skipped_active_request", "skipped_active_job"):
            response.skipped.append({"candidate_key": key, "reason": status_key})
        elif status_key == "skipped_empty":
            response.skipped.append({"candidate_key": key, "reason": "empty_content"})
        else:
            response.skipped.append({"candidate_key": key, "reason": status_key or "unknown"})

    # 2. record_ids (기존 record → queue)
    if req.record_ids:
        from app.models.plan_record import PlanRecord
        records = db.query(PlanRecord).filter(PlanRecord.id.in_(req.record_ids)).all()
        found_ids = {r.id for r in records}
        for rid in req.record_ids:
            if rid not in found_ids:
                response.errors.append({"record_id": rid, "error": "record not found"})
        for record in records:
            if not record.raw_content and not record.file_path:
                response.skipped.append({"record_id": record.id, "reason": "db_only_no_content"})
                continue
            try:
                result = exec_svc.enqueue_record(
                    record,
                    trigger_source="api:archive-candidates/queue",
                    selected_targets=selected_targets,
                    requested_by="api",
                )
            except Exception as exc:
                response.errors.append({"record_id": record.id, "error": str(exc)})
                continue
            status_key = result.get("status_key")
            if status_key == "queued":
                response.queued += 1
                if result.get("job_id"):
                    response.job_ids.append(result["job_id"])
                for req_id in result.get("request_ids") or ([result["request_id"]] if result.get("request_id") else []):
                    response.request_ids.append(req_id)
            elif status_key in ("skipped_active_request", "skipped_active_job"):
                response.skipped.append({"record_id": record.id, "reason": status_key})
            elif status_key == "skipped_empty":
                response.skipped.append({"record_id": record.id, "reason": "empty_content"})
            else:
                response.skipped.append({"record_id": record.id, "reason": status_key or "unknown"})

    db.commit()
    return response


@router_admin.post("/records/archive-candidates/preview", response_model=PlanArchiveCandidatePreviewResponse)
def preview_archive_candidate(
    candidate_key: str,
    db: Session = Depends(get_db),
):
    """file_only candidate 의 dry-run preview. DB write 없음.

    앞 8KB raw_content, total_bytes, total_lines, filename_hash, resolved_path, is_binary 반환.
    admin(:8001) 전용.
    """
    from pathlib import Path as _Path
    import hashlib as _hashlib

    registered = _plan_service.list_registered_paths()
    paths = [{"path": r.path, "type": r.path_type} for r in registered]
    svc = PlanRecordService(db)

    try:
        resolved_info = svc.resolve_archive_candidate_key(candidate_key, paths)
    except ValueError as exc:
        return PlanArchiveCandidatePreviewResponse(
            candidate_key=candidate_key,
            resolved_path="",
            filename_hash="",
            total_bytes=0,
            total_lines=0,
            is_binary=False,
            raw_content_preview="",
            not_queueable=str(exc),
        )

    resolved_path = resolved_info["resolved_path"]
    path = _Path(resolved_path)
    filename_hash = _hashlib.sha256(path.name.encode("utf-8")).hexdigest()

    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        return PlanArchiveCandidatePreviewResponse(
            candidate_key=candidate_key,
            resolved_path=resolved_path,
            filename_hash=filename_hash,
            total_bytes=0,
            total_lines=0,
            is_binary=False,
            raw_content_preview="",
            not_queueable=f"파일 읽기 오류: {exc}",
        )

    total_bytes = len(raw_bytes)
    # 이진 파일 감지 (앞 8KB에 null byte 존재)
    sample = raw_bytes[:8192]
    is_binary = b"\x00" in sample

    if is_binary:
        return PlanArchiveCandidatePreviewResponse(
            candidate_key=candidate_key,
            resolved_path=resolved_path,
            filename_hash=filename_hash,
            total_bytes=total_bytes,
            total_lines=0,
            is_binary=True,
            raw_content_preview="",
            not_queueable="이진 파일은 import/queue 불가",
        )

    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return PlanArchiveCandidatePreviewResponse(
            candidate_key=candidate_key,
            resolved_path=resolved_path,
            filename_hash=filename_hash,
            total_bytes=total_bytes,
            total_lines=0,
            is_binary=True,
            raw_content_preview="",
            not_queueable="UTF-8 디코딩 실패",
        )

    total_lines = text.count("\n") + 1
    preview = text[:8192]
    not_queueable: Optional[str] = None
    if total_bytes > PlanRecordService.MAX_IMPORT_BYTES:
        not_queueable = f"파일 크기 초과 (최대 10MB): {total_bytes} bytes"

    return PlanArchiveCandidatePreviewResponse(
        candidate_key=candidate_key,
        resolved_path=resolved_path,
        filename_hash=filename_hash,
        total_bytes=total_bytes,
        total_lines=total_lines,
        is_binary=False,
        raw_content_preview=preview,
        not_queueable=not_queueable,
    )


@router.post("/records/archive-analyze/{record_id}", response_model=ArchiveAnalyzeResponse)
def queue_archive_analyze(
    record_id: int,
    req: ArchiveAnalyzeRequest,
    db: Session = Depends(get_db),
):
    """archived plan record를 plan_archive_analyze LLM 큐에 등록한다.

    provider/model은 실행 target이고 profile_key는 optional context이다.
    Codex처럼 profile 없는 provider는 profile_key 없이 큐잉 가능해야 한다.
    """
    import json
    from pathlib import Path

    from app.modules.claude_worker.services import provider_registry
    from app.modules.claude_worker.services.llm_service import LLMService
    from app.modules.claude_worker.services.plan_analyze_handler import build_plan_analyze_prompt

    svc = PlanRecordService(db)
    record = svc.get_record(record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Record not found")
    if record.archived_at is None:
        raise HTTPException(status_code=400, detail="archive 분석은 archived_at이 있는 record만 큐잉할 수 있습니다")
    if req.provider and not provider_registry.is_supported(req.provider):
        raise HTTPException(status_code=400, detail=f"지원되지 않는 provider: {req.provider}")
    if req.provider and not (req.model or "").strip():
        raise HTTPException(status_code=400, detail="provider를 직접 지정할 때는 model도 함께 지정해야 합니다")

    file_content = record.raw_content or ""
    if not file_content and record.file_path:
        try:
            fp = Path(record.file_path)
            if fp.exists():
                file_content = fp.read_text(encoding="utf-8", errors="replace")
        except Exception:
            file_content = ""

    prompt = build_plan_analyze_prompt(
        file_content=file_content,
        filename=Path(record.file_path).name if record.file_path else record.filename_hash,
    )
    cli_options = {
        "source": "archive_tab",
        "profile_key": req.profile_key,
        "profile_optional": True,
    }
    llm_req = LLMService(db).enqueue(
        caller_type="plan_archive_analyze",
        caller_id=record.filename_hash,
        prompt=prompt,
        requested_by="archive_tab",
        request_source="archive_tab_manual",
        provider=req.provider,
        model=req.model,
        queue_name="utility",
        cli_options=cli_options,
    )
    return ArchiveAnalyzeResponse(
        id=llm_req.id,
        caller_type=llm_req.caller_type,
        caller_id=llm_req.caller_id,
        status=llm_req.status,
        provider=llm_req.provider,
        model=llm_req.model,
        profile_key=json.loads(llm_req.cli_options or "{}").get("profile_key"),
    )


@router.get("/records/{record_id}", response_model=PlanRecordWithEventsResponse)
def get_record(record_id: int, db: Session = Depends(get_db)):
    svc = PlanRecordService(db)
    record = svc.get_record(record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Record not found")
    return record


@router.patch("/records/{record_id}/memo", response_model=PlanRecordResponse)
def update_memo(record_id: int, req: MemoUpdateRequest, db: Session = Depends(get_db)):
    svc = PlanRecordService(db)
    if req.action == "draft":
        record = svc.update_memo_draft(record_id, req.text or "")
    elif req.action == "confirm":
        record = svc.confirm_memo(record_id)
    elif req.action == "rollback":
        record = svc.rollback_memo(record_id)
    else:
        raise HTTPException(status_code=400, detail=f"Invalid action: {req.action}")
    if not record:
        raise HTTPException(status_code=404, detail="Record not found")
    db.commit()
    db.refresh(record)
    return record


@router.get("/records/{record_id}/content")
def get_record_content(record_id: int, db: Session = Depends(get_db)):
    """raw_content 반환 (file_removed_at 이후에도 DB에서 조회 가능)"""
    svc = PlanRecordService(db)
    record = svc.get_record(record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Record not found")
    return {"id": record.id, "raw_content": record.raw_content}


def _serialize_relation(relation, direction: str) -> dict:
    def _plan(record) -> dict:
        return {
            "id": record.id,
            "filename_hash": record.filename_hash,
            "file_path": record.file_path,
            "title": record.title,
            "status": record.status,
            "archived_at": record.archived_at,
        }

    return {
        "id": relation.id,
        "direction": direction,
        "relation_type": relation.relation_type,
        "score": relation.score,
        "evidence": relation.evidence,
        "source": _plan(relation.source_record),
        "target": _plan(relation.target_record),
        "created_at": relation.created_at,
        "updated_at": relation.updated_at,
    }


@router.get("/records/{record_id}/relations", response_model=list[PlanRecordRelationResponse])
def get_record_relations(
    record_id: int,
    direction: str = "both",
    relation_type: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Return incoming/outgoing plan relations for one record."""
    from app.models.plan_record import PlanRecord, PlanRecordRelation

    if direction not in {"outgoing", "incoming", "both"}:
        raise HTTPException(status_code=400, detail="direction must be outgoing, incoming, or both")
    record = db.query(PlanRecord).filter(PlanRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Record not found")

    payload: list[dict] = []
    if direction in {"outgoing", "both"}:
        query = db.query(PlanRecordRelation).filter(PlanRecordRelation.source_plan_record_id == record_id)
        if relation_type:
            query = query.filter(PlanRecordRelation.relation_type == relation_type)
        payload.extend(_serialize_relation(row, "outgoing") for row in query.order_by(PlanRecordRelation.score.desc()).all())
    if direction in {"incoming", "both"}:
        query = db.query(PlanRecordRelation).filter(PlanRecordRelation.target_plan_record_id == record_id)
        if relation_type:
            query = query.filter(PlanRecordRelation.relation_type == relation_type)
        payload.extend(_serialize_relation(row, "incoming") for row in query.order_by(PlanRecordRelation.score.desc()).all())
    return payload


@router.post("/records/{record_id}/analyze", response_model=PlanArchiveAnalyzeResponse)
def analyze_record(record_id: int, req: PlanArchiveAnalyzeRequest, db: Session = Depends(get_db)):
    """Manual analyze for one archive record.

    preview는 DB 저장 없음, apply는 저장 있음. 두 모드 모두 LLMRequest를 생성하지 않는다.
    """
    from app.modules.dev_runner.services.plan_archive_manual_analyze_service import (
        PlanArchiveManualAnalyzeService,
    )

    svc = PlanArchiveManualAnalyzeService(db)
    result = svc.analyze(
        record_id,
        mode=req.mode,
        provider=req.provider,
        model=req.model,
        timeout_seconds=req.timeout_seconds,
        include_prompt=req.include_prompt,
        source=req.source,
    )
    if result.get("error") == "RECORD_NOT_FOUND":
        raise HTTPException(status_code=404, detail="Record not found")
    if result.get("error") == "EMPTY_PLAN_CONTENT":
        raise HTTPException(status_code=422, detail="Archive content is empty")
    return result


@router.post("/records/{record_id}/analyze-dry-run", response_model=PlanArchiveAnalyzeResponse)
def analyze_record_dry_run(record_id: int, req: PlanArchiveAnalyzeRequest, db: Session = Depends(get_db)):
    """Preview-only alias. mode=apply is intentionally rejected here."""
    if req.mode != "preview":
        raise HTTPException(status_code=400, detail="analyze-dry-run only supports preview mode")
    req.mode = "preview"
    return analyze_record(record_id, req, db)


@router.post("/records/{record_id}/restore")
def restore_record(record_id: int, db: Session = Depends(get_db)):
    """raw_content → 파일 복원, file_removed_at 초기화"""
    svc = PlanRecordService(db)
    record = svc.restore_file(record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Record or raw_content not found")
    db.commit()
    return {"restored": True, "path": record.file_path}


@router.post("/records/ingest")
def ingest_single_record(req: IngestSingleRequest, db: Session = Depends(get_db)):
    """단건 archive ingest (wtools PS1 → HTTP 호출용): file_path 기준 upsert"""
    svc = PlanRecordService(db)
    record = svc.ingest_single(
        file_path=req.file_path,
        project=req.project,
        raw_content=req.raw_content,
        title=req.title,
        status=req.status,
    )
    db.commit()
    db.refresh(record)
    return {"id": record.id, "filename_hash": record.filename_hash, "file_path": record.file_path}


@router.post("/records/import-archived", response_model=ImportArchivedResponse)
def import_archived(archive_dir: Optional[str] = None, db: Session = Depends(get_db)):
    """archived plan 파일 일괄 DB 이관"""
    if not archive_dir:
        # 등록된 archive 경로 자동 감지
        registered = _plan_service.list_registered_paths()
        archive_dirs = [r.path for r in registered if getattr(r, "path_type", "") == "archive"]
        if not archive_dirs:
            archive_dirs = [str(_DEFAULT_PLANS_ARCHIVE_DIR)]
    else:
        archive_dirs = [archive_dir]

    total = {"created": 0, "updated": 0, "skipped": 0, "errors": []}
    svc = PlanRecordService(db)
    for d in archive_dirs:
        result = svc.bulk_import_archived(d)
        total["created"] += result["created"]
        total["updated"] += result["updated"]
        total["skipped"] += result["skipped"]
        total["errors"].extend(result["errors"])
    return total


@router.post("/records/sync", response_model=PlanRecordsSyncResponse)
def sync_records(db: Session = Depends(get_db)):
    registered = _plan_service.list_registered_paths()
    paths = [{"path": r.path, "type": r.path_type} for r in registered]
    svc = PlanRecordService(db)
    result = svc.sync_all(paths)
    db.commit()
    return result


@router.post("/records/{record_id}/reanalyze")
def reanalyze_record(record_id: int, req: ReanalyzeRequest, db: Session = Depends(get_db)):
    """archive record에 대해 LLM 재분석 요청을 큐에 등록한다.

    profile_key 없는 provider(codex 등)도 허용한다.
    이미 pending/processing 상태 요청이 있으면 기존 요청 id를 반환한다.
    """
    from app.modules.dev_runner.services.plan_archive_execution_service import PlanArchiveExecutionService
    svc = PlanRecordService(db)
    record = svc.get_record(record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Record not found")
    exec_svc = PlanArchiveExecutionService(db)
    try:
        llm_req, created = exec_svc.queue_analysis(
            record=record,
            provider=req.provider,
            model=req.model,
            profile_key=req.profile_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    return {"queued": created, "request_id": llm_req.id, "provider": llm_req.provider, "model": llm_req.model}


@router.get("/records/{record_id}/chain", response_model=list[PlanRecordResponse])
def get_record_chain(record_id: int, db: Session = Depends(get_db)):
    """체인 조회 — chain_root_hash 기준으로 연결된 반복 계획서 목록 반환 (recurrence_count 오름차순)"""
    from app.models.plan_record import PlanRecord
    from sqlalchemy import and_

    record = db.query(PlanRecord).filter(PlanRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Record not found")

    if not record.chain_root_hash:
        # 자기 자신만 반환 (단일 plan)
        return [record]

    chain = db.query(PlanRecord).filter(
        and_(
            PlanRecord.chain_root_hash == record.chain_root_hash,
        )
    ).order_by(PlanRecord.recurrence_count.asc()).all()

    # chain root 자체도 포함
    root = db.query(PlanRecord).filter_by(filename_hash=record.chain_root_hash).first()
    if root and root not in chain:
        chain = [root] + chain

    return chain


@router.get("/statistics/recurrence")
def get_recurrence_statistics(db: Session = Depends(get_db)):
    """반복 수정 통계 — recurrence_count >= 2 plan만 집계"""
    from app.models.plan_record import PlanRecord
    from sqlalchemy import and_, func
    from collections import Counter

    recurring = db.query(PlanRecord).filter(
        PlanRecord.recurrence_count >= 2
    ).all()

    by_category: dict = {}
    scope_counter: Counter = Counter()

    for r in recurring:
        cat = r.category or "unknown"
        by_category[cat] = by_category.get(cat, 0) + 1
        try:
            import json
            scopes = json.loads(r.scope or "[]") if r.scope else []
            for s in scopes:
                scope_counter[s] += 1
        except Exception:
            pass

    top_scopes = [s for s, _ in scope_counter.most_common(10)]

    return {
        "by_category": by_category,
        "top_scopes": top_scopes,
        "total_recurrences": len(recurring),
    }


@router.get("/statistics/relations", response_model=PlanRecordRelationStatisticsResponse)
def get_relation_statistics(db: Session = Depends(get_db)):
    """Plan relation statistics, with unresolved followup cases separated."""
    from sqlalchemy import func
    from app.models.plan_record import PlanRecordRelation

    relation_counts = {
        relation_type: count
        for relation_type, count in db.query(
            PlanRecordRelation.relation_type,
            func.count(PlanRecordRelation.id),
        ).group_by(PlanRecordRelation.relation_type).all()
    }

    unresolved = (
        db.query(PlanRecordRelation)
        .filter(PlanRecordRelation.relation_type == "unresolved_followup")
        .order_by(PlanRecordRelation.updated_at.desc())
        .limit(10)
        .all()
    )

    top_sources = [
        {
            "record_id": record_id,
            "count": count,
        }
        for record_id, count in db.query(
            PlanRecordRelation.source_plan_record_id,
            func.count(PlanRecordRelation.id),
        ).group_by(PlanRecordRelation.source_plan_record_id).order_by(func.count(PlanRecordRelation.id).desc()).limit(10).all()
    ]
    top_targets = [
        {
            "record_id": record_id,
            "count": count,
        }
        for record_id, count in db.query(
            PlanRecordRelation.target_plan_record_id,
            func.count(PlanRecordRelation.id),
        ).group_by(PlanRecordRelation.target_plan_record_id).order_by(func.count(PlanRecordRelation.id).desc()).limit(10).all()
    ]

    return {
        "relation_counts": relation_counts,
        "unresolved_followup_count": relation_counts.get("unresolved_followup", 0),
        "recent_unresolved_followups": [_serialize_relation(row, "outgoing") for row in unresolved],
        "top_sources": top_sources,
        "top_targets": top_targets,
    }


@router.get("/events", response_model=list[PlanEventResponse])
def list_events(
    event_type: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    svc = PlanRecordService(db)
    return svc.list_events(
        event_type=event_type, date_from=date_from,
        date_to=date_to, skip=skip, limit=limit
    )


__all__ = ["router"]
