"""Instagram Worker API Routes."""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from ..models.schemas import WorkerStatusSchema, WorkerHealthSchema
from ..services.worker_status_service import WorkerStatusService

logger = logging.getLogger("instagram.worker_api")

router = APIRouter(prefix="/api/v1/instagram/worker", tags=["instagram-worker"])


@router.get("/status", response_model=WorkerStatusSchema | None)
async def get_worker_status(db: Session = Depends(get_db)):
    """현재 워커 상태 조회.

    Returns:
        워커 상태 정보 (활성 워커가 없으면 None)
    """
    service = WorkerStatusService(db)
    status = service.get_status_with_computed_fields()

    if not status:
        return None

    return WorkerStatusSchema(**status)


@router.get("/health", response_model=WorkerHealthSchema)
async def get_worker_health(db: Session = Depends(get_db)):
    """워커 헬스체크.

    Returns:
        헬스체크 결과 (status: healthy, warning, dead, no_worker)
    """
    service = WorkerStatusService(db)
    health = service.check_health()

    return WorkerHealthSchema(**health)
