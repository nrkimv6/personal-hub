"""Activity Crawl/Import API Routes."""

import logging
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.activity import ActivityCrawlRun, ActivityCenter
from app.modules.activity.models.schemas import (
    CourseImportRequest,
    CourseImportResponse,
    CrawlRunResponse,
    CrawlRunListResponse,
)
from app.modules.activity.services.import_service import ImportService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/crawl", tags=["activity-crawl"])

# activity-hub 동기화 URL
ACTIVITY_HUB_SYNC_URL = "https://activity-hub.woory.day/api/sync"


@router.post("/import", response_model=CourseImportResponse)
def import_courses(
    request: CourseImportRequest,
    center_id: Optional[int] = Query(None, description="센터 ID (크롤링 기록용)"),
    db: Session = Depends(get_db),
):
    """
    외부 데이터 임포트.

    외부 크롤러에서 수집한 강좌 데이터를 이 API를 통해 저장합니다.
    센터가 존재하지 않으면 자동 생성됩니다.
    """
    service = ImportService(db)

    # 크롤링 실행 기록 생성
    crawl_run = service.create_crawl_run(center_id)

    try:
        result = service.import_courses(request, crawl_run.id)
        return result
    except Exception as e:
        service.fail_crawl_run(crawl_run.id, str(e))
        raise HTTPException(status_code=500, detail=f"임포트 실패: {str(e)}")


@router.get("/runs", response_model=CrawlRunListResponse)
def list_crawl_runs(
    center_id: Optional[int] = Query(None, description="센터 ID"),
    status: Optional[str] = Query(None, description="상태"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """크롤링 실행 기록 목록."""
    query = db.query(ActivityCrawlRun)

    if center_id:
        query = query.filter(ActivityCrawlRun.center_id == center_id)
    if status:
        query = query.filter(ActivityCrawlRun.status == status)

    total = query.count()

    offset = (page - 1) * page_size
    runs = query.order_by(
        ActivityCrawlRun.started_at.desc()
    ).offset(offset).limit(page_size).all()

    items = []
    for run in runs:
        center_name = None
        if run.center_id:
            center = db.query(ActivityCenter).filter(
                ActivityCenter.id == run.center_id
            ).first()
            center_name = center.name if center else None

        items.append(CrawlRunResponse(
            id=run.id,
            center_id=run.center_id,
            started_at=run.started_at,
            completed_at=run.completed_at,
            status=run.status,
            courses_found=run.courses_found,
            courses_new=run.courses_new,
            courses_updated=run.courses_updated,
            error_message=run.error_message,
            center_name=center_name,
        ))

    return CrawlRunListResponse(items=items, total=total)


@router.get("/runs/{run_id}", response_model=CrawlRunResponse)
def get_crawl_run(
    run_id: int,
    db: Session = Depends(get_db),
):
    """크롤링 실행 기록 상세."""
    run = db.query(ActivityCrawlRun).filter(ActivityCrawlRun.id == run_id).first()

    if not run:
        raise HTTPException(status_code=404, detail="크롤링 기록을 찾을 수 없습니다.")

    center_name = None
    if run.center_id:
        center = db.query(ActivityCenter).filter(
            ActivityCenter.id == run.center_id
        ).first()
        center_name = center.name if center else None

    return CrawlRunResponse(
        id=run.id,
        center_id=run.center_id,
        started_at=run.started_at,
        completed_at=run.completed_at,
        status=run.status,
        courses_found=run.courses_found,
        courses_new=run.courses_new,
        courses_updated=run.courses_updated,
        error_message=run.error_message,
        center_name=center_name,
    )


async def _trigger_activity_hub_sync():
    """activity-hub D1 동기화 트리거 (백그라운드)."""
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(ACTIVITY_HUB_SYNC_URL)
            if response.status_code == 200:
                result = response.json()
                logger.info(
                    f"activity-hub sync completed: "
                    f"centers={result.get('centersCount', 0)}, "
                    f"courses={result.get('coursesCount', 0)}"
                )
            else:
                logger.error(f"activity-hub sync failed: {response.status_code}")
    except Exception as e:
        logger.error(f"activity-hub sync error: {e}")


@router.post("/sync-hub")
async def trigger_activity_hub_sync(
    background_tasks: BackgroundTasks,
):
    """
    activity-hub D1 동기화 트리거.

    monitor-page의 강좌 데이터를 activity-hub D1에 동기화합니다.
    백그라운드에서 실행되며, 즉시 응답을 반환합니다.
    """
    background_tasks.add_task(_trigger_activity_hub_sync)
    return {"message": "activity-hub 동기화가 시작되었습니다.", "status": "pending"}


@router.get("/sync-hub/status")
async def get_activity_hub_sync_status():
    """
    activity-hub 동기화 상태 확인.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(ACTIVITY_HUB_SYNC_URL)
            if response.status_code == 200:
                return response.json()
            else:
                return {"error": f"status check failed: {response.status_code}"}
    except Exception as e:
        return {"error": str(e)}
