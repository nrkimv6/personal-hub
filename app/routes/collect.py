"""수집 관리 API 라우트."""

import json
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.collect_service import CollectService
from app.services.task_schedule_service import TaskScheduleService
from app.schemas.collect import CollectedPostList, CollectedPostBase, CrawlHistoryList
from app.models import TaskSchedule, CrawlRequest
from app.models.google_search import GoogleSearchQueue, GoogleSavedSearch
from app.shared.redis import RedisClient, RedisQueue
from app.shared.redis.queue import GOOGLE_SEARCH_QUEUE

router = APIRouter(prefix="/collect", tags=["collect"])


@router.get("/posts", response_model=CollectedPostList)
async def get_collected_posts(
    source_type: Optional[str] = Query(None, description="소스 타입 (instagram, web)"),
    url_type: Optional[str] = Query(None, description="URL 타입 필터"),
    classification: Optional[str] = Query(None, description="분류 상태 (event, popup, uncategorized, unclassified)"),
    search: Optional[str] = Query(None, description="검색어"),
    date_from: Optional[datetime] = Query(None, description="시작 날짜"),
    date_to: Optional[datetime] = Query(None, description="종료 날짜"),
    is_active: Optional[bool] = Query(None, description="활성 상태 (Instagram 전용)"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    limit: int = Query(20, ge=1, le=100, description="페이지당 개수"),
    db: Session = Depends(get_db),
):
    """통합 게시물 목록 조회.

    Instagram 게시물과 CrawledPages를 통합하여 조회합니다.
    """
    service = CollectService(db)
    posts, total = service.get_posts_paginated(
        page=page,
        limit=limit,
        source_type=source_type,
        url_type=url_type,
        classification=classification,
        search=search,
        date_from=date_from,
        date_to=date_to,
        is_active=is_active,
    )

    total_pages = (total + limit - 1) // limit

    return CollectedPostList(
        items=posts,
        total=total,
        page=page,
        limit=limit,
        total_pages=total_pages,
    )


@router.get("/url-types", response_model=List[str])
async def get_url_types(
    db: Session = Depends(get_db),
):
    """사용 가능한 URL 타입 목록 조회."""
    service = CollectService(db)
    return service.get_url_types()


@router.get("/history", response_model=CrawlHistoryList)
async def get_crawl_history(
    source_type: Optional[str] = Query(None, description="소스 타입 (instagram, web)"),
    status: Optional[str] = Query(None, description="상태 (pending, processing, completed, failed)"),
    period: Optional[str] = Query("week", description="기간 (today, week, month, all)"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    limit: int = Query(20, ge=1, le=100, description="페이지당 개수"),
    db: Session = Depends(get_db),
):
    """통합 크롤링 이력 조회.

    CrawlRequest와 TaskScheduleRun을 통합하여 조회합니다.
    """
    service = CollectService(db)
    items, total, stats = service.get_crawl_history(
        page=page,
        limit=limit,
        source_type=source_type,
        status=status,
        period=period if period != "all" else None,
    )

    total_pages = (total + limit - 1) // limit

    return CrawlHistoryList(
        items=items,
        total=total,
        page=page,
        limit=limit,
        total_pages=total_pages,
    )


# ============= Schedule Endpoints =============

class ScheduleResponse(BaseModel):
    """스케줄 응답 스키마."""
    id: int
    name: str
    display_name: Optional[str] = None
    target_type: str
    schedule_type: str
    enabled: bool
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ScheduleDetailResponse(ScheduleResponse):
    """스케줄 상세 응답 스키마 (수정 모달용)."""
    target_config: Optional[Dict[str, Any]] = None
    schedule_value: Optional[Dict[str, Any]] = None
    saved_search: Optional[Dict[str, Any]] = None  # Google 검색: { query, date_filter, max_pages, search_params }


class CollectScheduleCreate(BaseModel):
    """스케줄 생성 요청 스키마."""
    target_type: str  # instagram_feed, google_search, writing_task
    target_config: Optional[Dict[str, Any]] = None
    display_name: Optional[str] = None
    schedule_type: str = "time_window"
    schedule_value: Optional[Dict[str, Any]] = None


class CollectScheduleUpdate(BaseModel):
    """스케줄 수정 요청 스키마."""
    display_name: Optional[str] = None
    schedule_value: Optional[Dict[str, Any]] = None  # 시간대 설정
    google_search_params: Optional[Dict[str, Any]] = None  # Google 검색 전용: query, date_filter, max_pages, search_params


def _generate_schedule_name(data: CollectScheduleCreate) -> str:
    """스케줄 타입과 설정에 따라 고유한 스케줄 이름 생성."""
    if data.target_type == "instagram_feed":
        account_id = data.target_config.get("service_account_id") if data.target_config else None
        return f"instagram_feed_account_{account_id}"
    elif data.target_type == "google_search":
        saved_id = data.target_config.get("saved_search_id") if data.target_config else None
        return f"google_search_{saved_id}"
    elif data.target_type == "writing_task":
        return "writing_task_default"
    else:
        return f"{data.target_type}_{uuid.uuid4().hex[:8]}"


@router.get("/schedules")
async def get_schedules(
    db: Session = Depends(get_db),
):
    """전체 스케줄 목록 조회."""
    schedules = db.query(TaskSchedule).order_by(TaskSchedule.target_type, TaskSchedule.name).all()
    return [
        ScheduleResponse(
            id=s.id,
            name=s.name,
            display_name=s.display_name,
            target_type=s.target_type,
            schedule_type=s.schedule_type,
            enabled=s.enabled,
            last_run_at=s.last_run_at,
            next_run_at=s.next_run_at,
        )
        for s in schedules
    ]


@router.post("/schedules", response_model=ScheduleResponse)
async def create_schedule(
    data: CollectScheduleCreate,
    db: Session = Depends(get_db),
):
    """통합 스케줄 생성 API.

    지원 타입:
    - instagram_feed: Instagram 피드 수집 (target_config.service_account_id 필요)
    - google_search: Google 검색 수집 (target_config.saved_search_id 필요)
    - writing_task: 글쓰기 태스크
    """
    schedule_service = TaskScheduleService(db)

    # 타입별 검증 및 중복 체크
    if data.target_type == "instagram_feed":
        if not data.target_config or not data.target_config.get("service_account_id"):
            raise HTTPException(
                status_code=400,
                detail="Instagram 스케줄에는 service_account_id가 필요합니다"
            )
        account_id = data.target_config["service_account_id"]
        schedule_name = f"instagram_feed_account_{account_id}"
        existing = schedule_service.get_schedule_by_name(schedule_name)
        if existing:
            raise HTTPException(
                status_code=400,
                detail="이미 해당 계정의 스케줄이 존재합니다"
            )
        # display_name 자동 생성
        if not data.display_name:
            data.display_name = f"Instagram 피드 (계정 {account_id})"

    elif data.target_type == "google_search":
        if not data.target_config:
            raise HTTPException(
                status_code=400,
                detail="Google 검색 스케줄에는 target_config가 필요합니다"
            )

        # 새 검색어로 생성하는 경우
        if data.target_config.get("create_new_search"):
            query = data.target_config.get("query", "").strip()
            if not query:
                raise HTTPException(
                    status_code=400,
                    detail="검색 키워드(query)를 입력해주세요"
                )

            # GoogleSavedSearch 새로 생성
            search_name = data.target_config.get("name") or f"[auto] {query}"
            new_saved = GoogleSavedSearch(
                name=search_name,
                query=query,
                date_filter=data.target_config.get("date_filter"),
                max_pages=data.target_config.get("max_pages", 1),
                is_favorite=False,
            )
            # search_params 처리
            sp = data.target_config.get("search_params")
            if sp:
                new_saved.search_params = json.dumps(sp) if isinstance(sp, dict) else sp
            db.add(new_saved)
            db.flush()  # ID 확보

            saved_id = new_saved.id
            saved_search = new_saved
            # target_config를 정규화 (saved_search_id 기반으로 통일)
            data.target_config = {"saved_search_id": saved_id}
        else:
            # 기존 저장된 검색 선택
            if not data.target_config.get("saved_search_id"):
                raise HTTPException(
                    status_code=400,
                    detail="Google 검색 스케줄에는 saved_search_id 또는 create_new_search가 필요합니다"
                )
            saved_id = data.target_config["saved_search_id"]
            saved_search = db.query(GoogleSavedSearch).filter_by(id=saved_id).first()
            if not saved_search:
                raise HTTPException(
                    status_code=404,
                    detail="저장된 검색을 찾을 수 없습니다"
                )

        schedule_name = f"google_search_{saved_id}"
        existing = schedule_service.get_schedule_by_name(schedule_name)
        if existing:
            raise HTTPException(
                status_code=400,
                detail="이미 해당 검색의 스케줄이 존재합니다"
            )
        # display_name 자동 생성
        if not data.display_name:
            data.display_name = f"Google 검색 ({saved_search.name})"

    elif data.target_type == "writing_task":
        schedule_name = "writing_task_default"
        existing = schedule_service.get_schedule_by_name(schedule_name)
        if existing:
            raise HTTPException(
                status_code=400,
                detail="이미 글쓰기 스케줄이 존재합니다"
            )
        if not data.display_name:
            data.display_name = "글쓰기 태스크"

    else:
        raise HTTPException(
            status_code=400,
            detail=f"지원하지 않는 스케줄 타입입니다: {data.target_type}"
        )

    # 스케줄 생성
    schedule = schedule_service.create_schedule(
        name=schedule_name,
        display_name=data.display_name,
        target_type=data.target_type,
        target_config=data.target_config,
        schedule_type=data.schedule_type,
        schedule_value=json.dumps(data.schedule_value) if data.schedule_value else None,
        enabled=True
    )

    return ScheduleResponse(
        id=schedule.id,
        name=schedule.name,
        display_name=schedule.display_name,
        target_type=schedule.target_type,
        schedule_type=schedule.schedule_type,
        enabled=schedule.enabled,
        last_run_at=schedule.last_run_at,
        next_run_at=schedule.next_run_at,
    )


@router.get("/schedules/{schedule_id}", response_model=ScheduleDetailResponse)
async def get_schedule_detail(
    schedule_id: int,
    db: Session = Depends(get_db),
):
    """스케줄 상세 조회 (수정 모달용)."""
    schedule = db.query(TaskSchedule).filter_by(id=schedule_id).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    target_config = schedule.get_target_config() if schedule.target_config else None
    schedule_value = json.loads(schedule.schedule_value) if schedule.schedule_value else None

    # Google 검색인 경우 SavedSearch 정보 포함
    saved_search_info = None
    if schedule.target_type == "google_search" and target_config:
        saved_id = target_config.get("saved_search_id")
        if saved_id:
            saved = db.query(GoogleSavedSearch).filter_by(id=saved_id).first()
            if saved:
                sp = None
                if saved.search_params:
                    sp = json.loads(saved.search_params) if isinstance(saved.search_params, str) else saved.search_params
                saved_search_info = {
                    "id": saved.id,
                    "name": saved.name,
                    "query": saved.query,
                    "date_filter": saved.date_filter,
                    "max_pages": saved.max_pages,
                    "search_params": sp,
                }

    return ScheduleDetailResponse(
        id=schedule.id,
        name=schedule.name,
        display_name=schedule.display_name,
        target_type=schedule.target_type,
        schedule_type=schedule.schedule_type,
        enabled=schedule.enabled,
        last_run_at=schedule.last_run_at,
        next_run_at=schedule.next_run_at,
        target_config=target_config,
        schedule_value=schedule_value,
        saved_search=saved_search_info,
    )


@router.put("/schedules/{schedule_id}", response_model=ScheduleDetailResponse)
async def update_schedule(
    schedule_id: int,
    data: CollectScheduleUpdate,
    db: Session = Depends(get_db),
):
    """스케줄 수정 API.

    - display_name: 표시 이름 변경
    - schedule_value: 실행 시간대 변경
    - google_search_params: Google 검색 조건 변경 (연결된 SavedSearch 함께 수정)
    """
    schedule = db.query(TaskSchedule).filter_by(id=schedule_id).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    schedule_service = TaskScheduleService(db)

    updates = {}
    if data.display_name is not None:
        updates["display_name"] = data.display_name
    if data.schedule_value is not None:
        updates["schedule_value"] = json.dumps(data.schedule_value)

    if updates:
        schedule_service.update_schedule(schedule_id, **updates)

    # Google 검색 파라미터 수정
    if data.google_search_params and schedule.target_type == "google_search":
        target_config = schedule.get_target_config() if schedule.target_config else {}
        saved_id = target_config.get("saved_search_id")
        if saved_id:
            saved = db.query(GoogleSavedSearch).filter_by(id=saved_id).first()
            if saved:
                gsp = data.google_search_params
                if "query" in gsp and gsp["query"]:
                    saved.query = gsp["query"]
                if "date_filter" in gsp:
                    saved.date_filter = gsp["date_filter"] or None
                if "max_pages" in gsp:
                    saved.max_pages = max(1, min(10, gsp["max_pages"]))
                if "search_params" in gsp:
                    sp = gsp["search_params"]
                    saved.search_params = json.dumps(sp) if isinstance(sp, dict) else sp
                if "name" in gsp and gsp["name"]:
                    saved.name = gsp["name"]
                db.commit()

    # 상세 응답 반환 (get_schedule_detail과 동일)
    schedule = db.query(TaskSchedule).filter_by(id=schedule_id).first()
    target_config = schedule.get_target_config() if schedule.target_config else None
    schedule_value = json.loads(schedule.schedule_value) if schedule.schedule_value else None

    saved_search_info = None
    if schedule.target_type == "google_search" and target_config:
        saved_id = target_config.get("saved_search_id")
        if saved_id:
            saved = db.query(GoogleSavedSearch).filter_by(id=saved_id).first()
            if saved:
                sp = None
                if saved.search_params:
                    sp = json.loads(saved.search_params) if isinstance(saved.search_params, str) else saved.search_params
                saved_search_info = {
                    "id": saved.id,
                    "name": saved.name,
                    "query": saved.query,
                    "date_filter": saved.date_filter,
                    "max_pages": saved.max_pages,
                    "search_params": sp,
                }

    return ScheduleDetailResponse(
        id=schedule.id,
        name=schedule.name,
        display_name=schedule.display_name,
        target_type=schedule.target_type,
        schedule_type=schedule.schedule_type,
        enabled=schedule.enabled,
        last_run_at=schedule.last_run_at,
        next_run_at=schedule.next_run_at,
        target_config=target_config,
        schedule_value=schedule_value,
        saved_search=saved_search_info,
    )


@router.post("/schedules/{schedule_id}/toggle")
async def toggle_schedule(
    schedule_id: int,
    enabled: bool = Query(..., description="활성화 여부"),
    db: Session = Depends(get_db),
):
    """스케줄 활성화/비활성화."""
    service = TaskScheduleService(db)
    schedule = service.toggle_schedule(schedule_id, enabled)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return {"success": True, "enabled": schedule.enabled}


@router.delete("/schedules/{schedule_id}")
async def delete_schedule(
    schedule_id: int,
    delete_runs: bool = Query(False, description="실행 이력도 함께 삭제"),
    db: Session = Depends(get_db),
):
    """스케줄 삭제.

    Args:
        schedule_id: 삭제할 스케줄 ID
        delete_runs: True면 실행 이력도 함께 삭제 (기본: False - 이력 유지)
    """
    service = TaskScheduleService(db)

    # 스케줄 존재 확인
    schedule = service.get_schedule_by_id(schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    # 실행 이력 수 확인 (삭제 전 정보 제공)
    run_count = service.get_run_count(schedule_id)

    # 이력이 있는데 delete_runs=False인 경우 경고
    if run_count > 0 and not delete_runs:
        raise HTTPException(
            status_code=400,
            detail=f"스케줄에 {run_count}개의 실행 이력이 있습니다. "
                   "이력도 삭제하려면 delete_runs=true를 사용하세요."
        )

    success = service.delete_schedule(schedule_id, delete_runs=delete_runs)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete schedule")

    return {
        "success": True,
        "message": f"스케줄이 삭제되었습니다" + (f" (이력 {run_count}개 포함)" if delete_runs and run_count > 0 else ""),
        "deleted_runs": run_count if delete_runs else 0,
    }


@router.post("/schedules/{schedule_id}/run")
async def trigger_schedule_run(
    schedule_id: int,
    db: Session = Depends(get_db),
):
    """스케줄 즉시 실행 요청.

    스케줄에 대응하는 크롤링 요청을 즉시 생성합니다.
    """
    schedule = db.query(TaskSchedule).filter(TaskSchedule.id == schedule_id).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    # 이미 대기 중인 요청이 있는지 확인
    existing = db.query(CrawlRequest).filter(
        CrawlRequest.status.in_(['pending', 'processing']),
        CrawlRequest.url_type.like(f'{schedule.target_type}%')
    ).first()

    if existing:
        return {
            "success": False,
            "message": "이미 대기 중인 요청이 있습니다",
            "request_id": existing.id,
        }

    # Instagram 피드 스케줄의 경우
    if schedule.target_type == 'instagram_feed':
        target_config = schedule.get_target_config() if schedule.target_config else {}
        service_account_id = target_config.get('service_account_id')

        if not service_account_id:
            raise HTTPException(
                status_code=400,
                detail="스케줄에 계정이 설정되지 않았습니다"
            )

        # CrawlRequest (범용 테이블)에 요청 생성 (Redis 큐 푸시 포함)
        from app.services.crawl_request_service import CrawlRequestService
        request_service = CrawlRequestService(db)

        request = await request_service.create_request_async(
            url=f"instagram://feed?account_id={service_account_id}",
            url_type="instagram_feed",
            requested_by="manual",
        )

        return {
            "success": True,
            "message": f"크롤링 요청 #{request.id}이(가) 생성되었습니다",
            "request_id": request.id,
        }

    # Google 검색 스케줄의 경우
    elif schedule.target_type == 'google_search':
        target_config = schedule.get_target_config() if schedule.target_config else {}
        saved_search_id = target_config.get('saved_search_id')

        if not saved_search_id:
            raise HTTPException(
                status_code=400,
                detail="저장된 검색이 설정되지 않았습니다"
            )

        saved_search = db.query(GoogleSavedSearch).filter_by(id=saved_search_id).first()
        if not saved_search:
            raise HTTPException(
                status_code=404,
                detail="저장된 검색을 찾을 수 없습니다"
            )

        # GoogleSearchQueue에 추가
        queue_item = GoogleSearchQueue(
            search_id=str(uuid.uuid4()),
            query=saved_search.query,
            date_filter=saved_search.date_filter,
            max_pages=saved_search.max_pages,
            saved_search_id=saved_search_id,
            schedule_id=schedule.id,  # 스케줄 ID 저장
            status="queued"  # Redis에 푸시할 예정이므로 queued
        )
        db.add(queue_item)
        db.commit()
        db.refresh(queue_item)

        # Redis 큐에 추가 시도
        redis_client = await RedisClient.get_client()
        if redis_client:
            redis_queue = RedisQueue(redis_client, GOOGLE_SEARCH_QUEUE)
            success = await redis_queue.push({
                "id": queue_item.id,
                "search_id": queue_item.search_id,
                "query": queue_item.query,
                "date_filter": queue_item.date_filter,
                "max_pages": queue_item.max_pages,
                "created_at": queue_item.created_at.isoformat() if queue_item.created_at else None,
            })

            if not success:
                # Redis push 실패 → SQLite fallback
                queue_item.status = "pending"
                db.commit()
        else:
            # Redis 미연결 → SQLite fallback
            queue_item.status = "pending"
            db.commit()

        return {
            "success": True,
            "message": "검색이 요청되었습니다",
            "search_id": queue_item.search_id,
        }

    # 글쓰기 태스크 스케줄의 경우
    elif schedule.target_type == 'writing_task':
        # 스케줄 실행 기록 생성
        schedule_service = TaskScheduleService(db)
        run = schedule_service.start_run(
            schedule_id=schedule.id,
            worker_id="manual",
            config_snapshot={"source": "manual"}
        )

        return {
            "success": True,
            "message": "글쓰기 태스크가 예약되었습니다",
            "run_id": run.id,
        }

    # Writing Source 수집 스케줄의 경우
    elif schedule.target_type == 'writing_source_collect':
        schedule_service = TaskScheduleService(db)
        run = schedule_service.start_run(
            schedule_id=schedule.id,
            worker_id="manual",
            config_snapshot={"source": "manual"}
        )

        return {
            "success": True,
            "message": "소스 수집 태스크가 예약되었습니다",
            "run_id": run.id,
        }

    # Keyword Analysis 스케줄의 경우
    elif schedule.target_type == 'keyword_analysis':
        schedule_service = TaskScheduleService(db)
        run = schedule_service.start_run(
            schedule_id=schedule.id,
            worker_id="manual",
            config_snapshot={"source": "manual"}
        )

        return {
            "success": True,
            "message": "키워드 분석 태스크가 예약되었습니다",
            "run_id": run.id,
        }

    # Report 스케줄의 경우
    elif schedule.target_type == 'report':
        from datetime import timedelta
        from app.modules.reports.services.report_service import ReportService

        schedule_service = TaskScheduleService(db)
        target_config = schedule.get_target_config() if schedule.target_config else {}

        # 스케줄 실행 기록 시작
        run = schedule_service.start_run(
            schedule_id=schedule.id,
            worker_id="manual",
            config_snapshot=target_config
        )

        try:
            report_service = ReportService(db)

            # 기간 계산
            period = target_config.get("period", "daily")
            period_end = datetime.now()
            if period == "daily":
                period_start = period_end - timedelta(days=1)
            elif period == "weekly":
                period_start = period_end - timedelta(weeks=1)
            else:
                period_start = period_end - timedelta(days=30)

            # LLM 요청 생성
            llm_request = report_service.request_report(
                report_type=target_config.get("report_type", "daily_summary"),
                period_start=period_start,
                period_end=period_end,
                config=target_config
            )

            # 완료 처리 (LLM Worker가 비동기로 처리)
            schedule_service.complete_run(
                run.id,
                collected_count=1,
                saved_count=1,
                stop_reason=f"report_requested_id_{llm_request.id}"
            )
            schedule_service.update_schedule_after_run(run.schedule_id)

            return {
                "success": True,
                "message": "보고서 생성이 요청되었습니다",
                "run_id": run.id,
                "llm_request_id": llm_request.id,
            }

        except Exception as e:
            schedule_service.fail_run(run.id, str(e))
            raise HTTPException(
                status_code=500,
                detail=f"보고서 생성 요청 실패: {str(e)}"
            )

    # 지원하지 않는 스케줄 타입
    else:
        return {
            "success": False,
            "message": f"스케줄 타입 '{schedule.target_type}'은(는) 즉시 실행을 지원하지 않습니다",
        }
