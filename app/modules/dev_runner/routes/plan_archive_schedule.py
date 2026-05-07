"""Plan Archive schedule and execution routes."""
import logging
from typing import Any, Optional
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
    PlanArchiveCategoryRepairRequest,
    PlanArchiveCategoryRepairResponse,
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



from . import plan_records as _plan_records
from .plan_archive_helpers import (
    _archive_request_error_code,
    _archive_target_fields,
    _latest_profile_assignment,
    _parse_cli_options_text,
)

router = _plan_records.router
router_admin = _plan_records.router_admin
logger = logging.getLogger(__name__)

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
    recent_request_rows: list[ArchiveLLMRequestRow] = []
    for r in recent_reqs:
        cli = _parse_cli_options_text(r.cli_options)
        actual_engine, actual_profile_name = _latest_profile_assignment(db, r.id)
        recent_request_rows.append(
            ArchiveLLMRequestRow(
                id=r.id,
                status=r.status,
                provider=r.provider or "",
                model=r.model or "",
                **_archive_target_fields(
                    cli,
                    provider=r.provider,
                    model=r.model,
                    actual_engine=actual_engine,
                    actual_profile_name=actual_profile_name,
                ),
                record_id=r.caller_id,
                failure_category=r.failure_category,
                error_code=_archive_request_error_code(r.failure_category, r.error_message),
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
    recent_attempt_rows = []
    for a in recent_attempts:
        target_fields = _archive_target_fields(
            _parse_cli_options_text(a.request.cli_options if a.request else None),
            provider=a.provider,
            model=a.model,
            actual_engine=a.engine,
            actual_profile_name=a.profile_name,
        )
        target_fields.pop("engine", None)
        target_fields.pop("profile_name", None)
        recent_attempt_rows.append(
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
                **target_fields,
                error_message=a.error_message,
                requested_at=a.requested_at.isoformat() if a.requested_at else None,
                finished_at=a.finished_at.isoformat() if a.finished_at else None,
            )
        )

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

    rows = []
    for a in items:
        target_fields = _archive_target_fields(
            _parse_cli_options_text(a.request.cli_options if a.request else None),
            provider=a.provider,
            model=a.model,
            actual_engine=a.engine,
            actual_profile_name=a.profile_name,
        )
        target_fields.pop("engine", None)
        target_fields.pop("profile_name", None)
        rows.append(
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
                **target_fields,
                error_message=a.error_message,
                requested_at=a.requested_at.isoformat() if a.requested_at else None,
                finished_at=a.finished_at.isoformat() if a.finished_at else None,
            )
        )

    return ArchiveExecutionAttemptListResponse(
        items=rows,
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

    registered = _plan_records._plan_service.list_registered_paths()
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

__all__ = [
    "get_archive_schedule_dashboard",
    "list_archive_schedule_runs",
    "list_archive_execution_attempts",
    "pause_archive_schedule",
    "resume_archive_schedule",
    "run_archive_executions",
    "sync_archive_executions",
    "list_archive_execution_history",
]
