"""Activity Crawl/Import API Routes."""

import os
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
from app.modules.activity.services.sync_service import SyncService
from app.core.config import logger

router = APIRouter(prefix="/crawl", tags=["activity-crawl"])

# activity-hub 동기화 설정 (PULL 방식 - 비활성화)
# ACTIVITY_HUB_SYNC_URL = "https://activity-hub.woory.day/api/sync"
ACTIVITY_HUB_SYNC_API_KEY = os.getenv("ACTIVITY_HUB_SYNC_API_KEY", "")


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


# ============================================================
# PULL 방식 (비활성화) - activity-hub가 데이터를 가져가는 방식
# ============================================================
# async def _trigger_activity_hub_sync():
#     """activity-hub D1 동기화 트리거 (백그라운드, PULL 방식)."""
#     if not ACTIVITY_HUB_SYNC_API_KEY:
#         logger.error("ACTIVITY_HUB_SYNC_API_KEY not set in environment variables")
#         return
#
#     try:
#         headers = {"Authorization": f"Bearer {ACTIVITY_HUB_SYNC_API_KEY}"}
#         async with httpx.AsyncClient(timeout=120.0) as client:
#             response = await client.post(ACTIVITY_HUB_SYNC_URL, headers=headers)
#             if response.status_code == 200:
#                 result = response.json()
#                 logger.info(
#                     f"[PULL] activity-hub sync completed: "
#                     f"centers={result.get('centersCount', 0)}, "
#                     f"courses={result.get('coursesCount', 0)}"
#                 )
#             else:
#                 logger.error(
#                     f"[PULL] activity-hub sync failed: {response.status_code}, "
#                     f"response: {response.text}"
#                 )
#     except Exception as e:
#         logger.error(f"[PULL] activity-hub sync error: {e}")


async def _push_all_centers_to_activity_hub():
    """모든 센터의 데이터를 activity-hub로 PUSH (백그라운드)."""
    from app.database import SessionLocal

    logger.info("[PUSH] ===== BACKGROUND TASK STARTED =====")

    db = SessionLocal()
    try:
        sync_service = SyncService()

        # 활성화된 센터 목록 조회
        centers = db.query(ActivityCenter).filter(
            ActivityCenter.is_active == True
        ).all()

        if not centers:
            logger.warning("[PUSH] No active centers found for sync")
            return

        logger.info(f"[PUSH] Starting sync for {len(centers)} centers")

        total_centers = 0
        total_courses = 0
        failed_centers = []

        for center in centers:
            try:
                logger.info(f"[PUSH] Syncing center {center.id}: {center.name}")
                result = await sync_service.push_center_courses(db, center.id)

                if result.get("success"):
                    total_centers += 1
                    courses_count = result.get("coursesCount", 0)
                    total_courses += courses_count
                    logger.info(f"[PUSH] ✓ Center {center.id} ({center.name}) synced: {courses_count} courses")
                else:
                    failed_centers.append(center.id)
                    logger.error(f"[PUSH] ✗ Center {center.id} sync failed: {result.get('error')}")
            except Exception as e:
                failed_centers.append(center.id)
                logger.error(f"[PUSH] ✗ Center {center.id} sync error: {e}", exc_info=True)

        logger.info(
            f"[PUSH] ===== SYNC COMPLETED: {total_centers}/{len(centers)} centers, "
            f"{total_courses} courses, failed: {failed_centers} ====="
        )
    except Exception as e:
        logger.error(f"[PUSH] ===== FATAL ERROR: {e} =====", exc_info=True)
    finally:
        db.close()


@router.post("/sync-hub")
async def trigger_activity_hub_sync(
    background_tasks: BackgroundTasks,
):
    """
    activity-hub D1 동기화 (PUSH 방식).

    monitor-page의 모든 활성 센터 데이터를 activity-hub로 전송합니다.
    백그라운드에서 실행되며, 즉시 응답을 반환합니다.
    """
    logger.info("[PUSH] ===== SYNC REQUEST RECEIVED, ADDING BACKGROUND TASK =====")
    background_tasks.add_task(_push_all_centers_to_activity_hub)
    return {"message": "activity-hub 동기화가 시작되었습니다.", "status": "pending"}


@router.post("/sync-hub/test", include_in_schema=False)
async def test_sync_hub(
    db: Session = Depends(get_db),
):
    """
    activity-hub 동기화 테스트 (즉시 실행, 결과 반환).

    테스트용으로 첫 번째 센터만 동기화하고 결과를 즉시 반환합니다.
    """
    try:
        sync_service = SyncService()

        # 강좌가 있는 센터로 테스트 (ID 81: 신세계 대구신세계 - 483 courses)
        center = db.query(ActivityCenter).filter(
            ActivityCenter.id == 81
        ).first()

        if not center:
            logger.warning("[TEST] No active centers found")
            return {
                "success": False,
                "message": "활성화된 센터가 없습니다."
            }

        logger.info(f"[TEST] Testing sync for center {center.id}: {center.name}")
        result = await sync_service.push_center_courses(db, center.id)

        logger.info(f"[TEST] Result: {result}")

        return {
            "success": result.get("success"),
            "center_id": center.id,
            "center_name": center.name,
            "result": result
        }
    except Exception as e:
        logger.error(f"[TEST] Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sync-hub/status")
async def get_activity_hub_sync_status():
    """
    activity-hub 동기화 상태 확인.
    """
    # PUSH 방식에서는 상태 확인 불필요
    return {"message": "PUSH 방식으로 변경됨. 개별 센터 동기화 로그를 확인하세요."}
