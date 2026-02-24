"""
Plan Records API Routes
GET    /api/v1/plans/records         - 레코드 목록 (project, status 필터, skip/limit)
GET    /api/v1/plans/records/{id}    - 레코드 상세 (events 포함)
PATCH  /api/v1/plans/records/{id}/memo - 메모 업데이트 (draft/confirm/rollback)
POST   /api/v1/plans/records/sync   - 수동 동기화 (등록된 경로 전체 스캔)
GET    /api/v1/plans/events         - 이벤트 목록 (타임라인용)
GET    /api/v1/plans/records/by-path - file_path로 get_or_create
"""
import logging
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.dev_runner.services.plan_record_service import PlanRecordService
from app.modules.dev_runner.services.plan_service import plan_service as _plan_service
from app.modules.dev_runner.schemas import (
    PlanRecordResponse, PlanRecordWithEventsResponse,
    PlanEventResponse, MemoUpdateRequest
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/plans", tags=["plan-records"])


@router.get("/records/by-path", response_model=PlanRecordResponse)
def get_record_by_path(file_path: str, db: Session = Depends(get_db)):
    """file_path로 레코드 get_or_create (메모 편집 시 진입점)"""
    svc = PlanRecordService(db)
    record = svc.get_or_create(file_path)
    db.commit()
    db.refresh(record)
    return record


@router.get("/records", response_model=list[PlanRecordResponse])
def list_records(
    project: Optional[str] = None,
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    svc = PlanRecordService(db)
    return svc.list_records(project=project, status=status, skip=skip, limit=limit)


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


@router.post("/records/sync")
def sync_records(db: Session = Depends(get_db)):
    registered = _plan_service.list_registered_paths()
    paths = [{"path": r.path, "type": r.path_type} for r in registered]
    svc = PlanRecordService(db)
    return svc.sync_all(paths)


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
