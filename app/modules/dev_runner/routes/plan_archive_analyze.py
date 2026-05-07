"""Plan Archive analyze and candidate routes."""
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

class ReanalyzeRequest(BaseModel):
    """archive record LLM 재분석 요청."""
    provider: str
    model: str = ""
    profile_key: Optional[str] = None


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

    rows: list[ArchiveLLMRequestRow] = []
    for r in items:
        cli = _parse_cli_options_text(r.cli_options)
        actual_engine, actual_profile_name = _latest_profile_assignment(db, r.id)
        rows.append(
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
                candidate_key=cli.get("candidate_key"),
                source_schedule_run_id=cli.get("source_schedule_run_id"),
                failure_category=r.failure_category,
                error_code=_archive_request_error_code(r.failure_category, r.error_message),
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

    cli = _parse_cli_options_text(r.cli_options)
    actual_engine, actual_profile_name = _latest_profile_assignment(db, r.id)

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
        prompt=r.prompt,
        result=r.result,
        raw_response=r.raw_response,
        cli_options=r.cli_options,
        applied_request_id=applied_request_id,
        is_applied_to_record=is_applied,
        related_record=related_record,
        audit_snapshots=audit_snapshots,
    )


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

    registered = _plan_records._plan_service.list_registered_paths()
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
    registered = _plan_records._plan_service.list_registered_paths()
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

    registered = _plan_records._plan_service.list_registered_paths()
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

__all__ = [
    "ReanalyzeRequest",
    "list_archive_llm_requests",
    "get_archive_llm_request_detail",
    "list_archive_candidates",
    "queue_archive_candidates",
    "preview_archive_candidate",
    "queue_archive_analyze",
    "analyze_record",
    "analyze_record_dry_run",
    "reanalyze_record",
]
