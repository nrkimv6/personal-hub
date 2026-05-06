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
from app.modules.dev_runner.schemas import (
    PlanRecordResponse, PlanRecordWithEventsResponse,
    PlanEventResponse, MemoUpdateRequest, ImportArchivedResponse,
    PlanRecordsSyncResponse, ArchiveCandidateSummaryResponse,
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


@router.get("/records/by-path", response_model=PlanRecordResponse)
def get_record_by_path(file_path: str, db: Session = Depends(get_db)):
    """file_path로 레코드 get_or_create (메모 편집 시 진입점)"""
    svc = PlanRecordService(db)
    record = svc.get_or_create(file_path)
    db.commit()
    db.refresh(record)
    return record


@router.get("/records/guide-status")
def get_guide_status(include_history: bool = False, db: Session = Depends(get_db)):
    """가이드별 staleness 정보 반환 (pending archive 건수 포함)"""
    svc = PlanRecordService(db)
    return svc.get_guide_status(include_history=include_history)


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
    db: Session = Depends(get_db),
):
    tags_list = [t.strip() for t in tags.split(",")] if tags else None
    svc = PlanRecordService(db)
    return svc.list_records(
        project=project, status=status, category=category, tags=tags_list,
        q=q, date_from=date_from, date_to=date_to,
        skip=skip, limit=limit, deep=deep,
    )


@router.get("/records/archive-candidates", response_model=ArchiveCandidateSummaryResponse)
def list_archive_candidates(
    include_temp: bool = False,
    skip: int = 0,
    limit: int = 200,
    db: Session = Depends(get_db),
):
    """archive 파일과 DB 레코드를 합친 실행/이관 후보 목록."""
    registered = _plan_service.list_registered_paths()
    paths = [{"path": r.path, "type": r.path_type} for r in registered]
    svc = PlanRecordService(db)
    return svc.list_archive_candidates(
        paths,
        include_temp=include_temp,
        skip=skip,
        limit=limit,
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
