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
from app.modules.dev_runner.services.plan_archive_retrieval_service import (
    PlanArchiveRetrievalService,
    RetrievalQuery,
)
from app.modules.dev_runner.services.plan_archive_retrieval_readiness import (
    get_plan_archive_retrieval_readiness,
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
    result = svc.enqueue_records(
        records,
        trigger_source="manual:plan_archive_analyze",
        selected_profiles=[item.model_dump() for item in req.selected_profiles],
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


@router.post("/records/sync")
def sync_records(db: Session = Depends(get_db)):
    registered = _plan_service.list_registered_paths()
    paths = [{"path": r.path, "type": r.path_type} for r in registered]
    svc = PlanRecordService(db)
    return svc.sync_all(paths)


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
