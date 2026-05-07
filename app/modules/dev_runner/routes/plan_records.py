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


class IngestSingleRequest(BaseModel):
    """단건 ingest 요청 (wtools PS1 → HTTP 호출용)"""
    file_path: str
    project: Optional[str] = None
    raw_content: Optional[str] = None
    title: Optional[str] = None
    status: Optional[str] = None



logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/plans", tags=["plan-records"])
router_admin = APIRouter(prefix="/api/v1/plans", tags=["plan-records-admin"])
_DEFAULT_PLANS_ARCHIVE_DIR = PROJECT_ROOT / ".worktrees" / "plans" / "docs" / "archive"














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








# ── Phase 4-A: dashboard + list endpoints ────────────────────────────────────























































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


















# Import split modules before /records/{record_id} so fixed GET paths keep precedence.
from . import plan_archive_schedule as _plan_archive_schedule  # noqa: F401,E402
from . import plan_archive_analyze as _plan_archive_analyze  # noqa: F401,E402
from . import plan_archive_knowledge as _plan_archive_knowledge  # noqa: F401,E402
from .plan_archive_helpers import (  # noqa: F401,E402
    _archive_request_error_code,
    _extract_profile_fields,
    _parse_cli_options_text,
    _dict_or_empty,
    _archive_target_fields,
    _latest_profile_assignment,
)
from .plan_archive_schedule import (  # noqa: F401,E402
    get_archive_schedule_dashboard,
    list_archive_schedule_runs,
    list_archive_execution_attempts,
    pause_archive_schedule,
    resume_archive_schedule,
    run_archive_executions,
    sync_archive_executions,
    list_archive_execution_history,
)
from .plan_archive_analyze import (  # noqa: F401,E402
    ReanalyzeRequest,
    list_archive_llm_requests,
    get_archive_llm_request_detail,
    list_archive_candidates,
    queue_archive_candidates,
    preview_archive_candidate,
    queue_archive_analyze,
    analyze_record,
    analyze_record_dry_run,
    reanalyze_record,
)
from .plan_archive_knowledge import (  # noqa: F401,E402
    get_guide_status,
    get_archive_health,
    repair_archive_category_pollution,
    search_archive,
    build_archive_context,
    get_archive_metrics,
    queue_archive_insight_batch,
    list_archive_insight_reports,
    get_archive_insight_report,
    get_archive_insight_evidence,
    update_archive_insight_review,
    promote_archive_insight_plan,
    preview_archive_doc_patch,
    apply_archive_doc_patch,
    reject_archive_doc_patch,
    index_archive_records,
    index_cross_repo_archive,
    index_archive_embeddings,
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


__all__ = ["router", "router_admin"]
