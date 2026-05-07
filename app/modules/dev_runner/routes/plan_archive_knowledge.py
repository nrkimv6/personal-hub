"""Plan Archive knowledge routes."""
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


@router_admin.post("/records/archive-category-repair", response_model=PlanArchiveCategoryRepairResponse)
def repair_archive_category_pollution(
    req: PlanArchiveCategoryRepairRequest,
    db: Session = Depends(get_db),
):
    """Audit or repair filename/path-like Plan Archive categories. Admin only."""
    result = PlanRecordService(db).repair_plan_archive_category_pollution(
        apply=req.apply,
        limit=req.limit,
    )
    if req.apply:
        db.commit()
    return result


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

__all__ = [
    "get_guide_status",
    "get_archive_health",
    "repair_archive_category_pollution",
    "search_archive",
    "build_archive_context",
    "get_archive_metrics",
    "queue_archive_insight_batch",
    "list_archive_insight_reports",
    "get_archive_insight_report",
    "get_archive_insight_evidence",
    "update_archive_insight_review",
    "promote_archive_insight_plan",
    "preview_archive_doc_patch",
    "apply_archive_doc_patch",
    "reject_archive_doc_patch",
    "index_archive_records",
    "index_cross_repo_archive",
    "index_archive_embeddings",
]
