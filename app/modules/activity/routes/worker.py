"""Activity Worker API Routes."""

from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.activity import ActivityCrawlRun
from app.models.crawl_request import CrawlRequest

router = APIRouter(prefix="/worker", tags=["activity-worker"])


class WorkerStatusResponse(BaseModel):
    """워커 상태 응답."""
    is_running: bool
    last_activity: Optional[datetime] = None
    pending_requests: int
    processing_requests: int
    recent_runs: int  # 최근 24시간 크롤링 횟수


class CrawlRequestCreate(BaseModel):
    """크롤링 요청 생성."""
    center_id: int


class CrawlRequestResponse(BaseModel):
    """크롤링 요청 응답."""
    id: int
    url: str
    status: str
    requested_at: datetime

    class Config:
        from_attributes = True


@router.get("/status", response_model=WorkerStatusResponse)
def get_worker_status(db: Session = Depends(get_db)):
    """Activity 워커 상태 조회."""
    from datetime import timedelta

    now = datetime.now()
    day_ago = now - timedelta(days=1)

    # pending 요청 수
    pending = db.query(CrawlRequest).filter(
        CrawlRequest.url_type == CrawlRequest.URL_TYPE_ACTIVITY,
        CrawlRequest.status == CrawlRequest.STATUS_PENDING,
    ).count()

    # processing 요청 수
    processing = db.query(CrawlRequest).filter(
        CrawlRequest.url_type == CrawlRequest.URL_TYPE_ACTIVITY,
        CrawlRequest.status.in_([
            CrawlRequest.STATUS_PICKED,
            CrawlRequest.STATUS_PROCESSING
        ]),
    ).count()

    # 최근 24시간 크롤링 실행 수
    recent_runs = db.query(ActivityCrawlRun).filter(
        ActivityCrawlRun.started_at >= day_ago
    ).count()

    # 마지막 활동 시간 (가장 최근 크롤링 실행)
    last_run = db.query(ActivityCrawlRun).order_by(
        ActivityCrawlRun.started_at.desc()
    ).first()

    return WorkerStatusResponse(
        is_running=processing > 0,
        last_activity=last_run.started_at if last_run else None,
        pending_requests=pending,
        processing_requests=processing,
        recent_runs=recent_runs,
    )


@router.post("/request", response_model=CrawlRequestResponse, status_code=201)
async def create_crawl_request(
    data: CrawlRequestCreate,
    db: Session = Depends(get_db),
):
    """센터 크롤링 요청 생성."""
    from app.models.activity import ActivityCenter

    center = db.query(ActivityCenter).filter(
        ActivityCenter.id == data.center_id
    ).first()

    if not center:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="센터를 찾을 수 없습니다.")

    # URL 형식: activity://center/{id}
    url = f"activity://center/{center.id}"

    # Activity 요청은 Redis 큐 없이 pending 상태로만 생성
    # (ActivityWorker가 DB를 직접 폴링)
    from app.services.crawl_request_service import CrawlRequestService
    request_service = CrawlRequestService(db)

    request = request_service.create_request(
        url=url,
        url_type=CrawlRequest.URL_TYPE_ACTIVITY,
        requested_by="manual",
    )

    return request


@router.get("/requests")
def list_requests(
    status: Optional[str] = None,
    limit: int = 20,
    db: Session = Depends(get_db),
):
    """크롤링 요청 목록 조회."""
    query = db.query(CrawlRequest).filter(
        CrawlRequest.url_type == CrawlRequest.URL_TYPE_ACTIVITY
    )

    if status:
        query = query.filter(CrawlRequest.status == status)

    requests = query.order_by(
        CrawlRequest.requested_at.desc()
    ).limit(limit).all()

    return [
        {
            "id": r.id,
            "url": r.url,
            "status": r.status,
            "requested_at": r.requested_at,
            "processed_at": r.processed_at,
            "error_message": r.error_message,
        }
        for r in requests
    ]
