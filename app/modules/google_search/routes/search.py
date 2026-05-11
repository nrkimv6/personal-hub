"""
Google 검색 API 라우트

검색 수행, 결과 조회, 히스토리 관리, 저장된 검색 조건 CRUD API를 제공합니다.

Note:
    검색 요청은 큐에 저장되고 워커에서 처리됩니다.
    API 서버는 Session 0 (NSSM 서비스)에서 실행되어 브라우저 사용이 불가합니다.

Redis 큐 지원:
    - Redis 연결 시: Redis 큐에 추가 (status=queued)
    - Redis 미연결 시: SQLite 폴링 (status=pending)
"""

import json
import logging
import uuid
from datetime import datetime
from typing import List, Optional
from urllib.parse import parse_qs, urlparse

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.google_search import (
    GoogleSavedSearch,
    GoogleSearchHistory,
    GoogleSearchResult,
    GoogleSearchQueue,
)
from app.modules.google_search.services.queue_service import (
    enqueue_google_search,
    recover_pending_google_searches,
)
from app.modules.google_search.models.schemas import (
    SearchRequest,
    SearchResult,
    SearchResponse,
    SearchQueueResponse,
    SearchStatusResponse,
    SearchHistoryItem,
    SavedSearchCreate,
    SavedSearchUpdate,
    SavedSearchResponse,
)

logger = logging.getLogger("google_search.routes")

router = APIRouter(prefix="/api/v1/google", tags=["google-search"])

GOOGLE_TBS_TO_DATE_FILTER = {
    "qdr:h": "1h",
    "qdr:d": "24h",
    "qdr:w": "1w",
    "qdr:m": "1m",
    "qdr:y": "1y",
}


def _normalize_google_search_input(
    query: str,
    date_filter: Optional[str] = None,
) -> tuple[str, Optional[str]]:
    """Google 검색 URL 입력을 저장 검색 모델 값으로 정규화."""
    raw_query = (query or "").strip()
    parsed = urlparse(raw_query)
    if not parsed.scheme or "google." not in parsed.netloc or not parsed.path.startswith("/search"):
        return raw_query, date_filter

    params = parse_qs(parsed.query)
    normalized_query = (params.get("q") or [raw_query])[0].strip() or raw_query
    normalized_date_filter = date_filter

    if not normalized_date_filter:
        tbs = (params.get("tbs") or [None])[0]
        normalized_date_filter = GOOGLE_TBS_TO_DATE_FILTER.get(tbs)

    return normalized_query, normalized_date_filter


# ============================================================
# 검색 API (큐 기반)
# ============================================================


@router.post("/search", response_model=SearchQueueResponse, status_code=202)
async def search(
    request: SearchRequest,
    db: Session = Depends(get_db),
):
    """구글 검색 요청을 큐에 추가.

    검색 요청은 워커에서 비동기로 처리됩니다.
    결과는 GET /api/v1/google/search/{search_id}/status 에서 조회할 수 있습니다.

    Redis 연결 시 Redis 큐에 추가하고, 미연결 시 SQLite 폴링으로 처리됩니다.

    Args:
        request: 검색 요청 (query, date_filter, max_pages, service_account_id)

    Returns:
        SearchQueueResponse: 검색 요청 ID와 상태
    """
    search_id = str(uuid.uuid4())

    # DB에 큐 아이템 저장
    # search_params JSON 직렬화
    search_params_json = None
    if request.search_params:
        search_params_json = json.dumps(request.search_params)

    queue_item = GoogleSearchQueue(
        search_id=search_id,
        query=request.query,
        date_filter=request.date_filter,
        max_pages=min(request.max_pages, 10),
        service_account_id=request.service_account_id,
        search_params=search_params_json,
        status=GoogleSearchQueue.STATUS_QUEUED,  # 일단 queued로 설정
    )
    db.add(queue_item)
    db.commit()
    db.refresh(queue_item)

    status = await enqueue_google_search(queue_item, db)

    logger.info(
        "Search request queued: search_id=%s, query=%s, mode=%s, status=%s",
        search_id,
        request.query,
        "redis" if status == GoogleSearchQueue.STATUS_QUEUED else "sqlite",
        status,
    )

    return SearchQueueResponse(
        search_id=search_id,
        status=status,
        message="검색 요청이 큐에 추가되었습니다. 상태를 폴링하여 결과를 확인하세요.",
    )


@router.get("/search/{search_id}/status", response_model=SearchStatusResponse)
async def get_search_status(
    search_id: str,
    db: Session = Depends(get_db),
):
    """검색 요청 상태 및 결과 조회.

    Args:
        search_id: 검색 세션 ID

    Returns:
        SearchStatusResponse: 검색 상태 및 결과 (완료 시)
    """
    # 먼저 큐에서 확인
    queue_item = db.query(GoogleSearchQueue).filter_by(search_id=search_id).first()

    if queue_item:
        # 큐에 있는 경우 (pending 또는 processing)
        results = []

        # 완료된 경우 결과도 함께 조회
        if queue_item.status == "completed":
            db_results = (
                db.query(GoogleSearchResult)
                .filter_by(search_id=search_id)
                .order_by(GoogleSearchResult.rank)
                .all()
            )
            results = [
                SearchResult(
                    rank=r.rank,
                    title=r.title,
                    url=r.url,
                    display_url=r.display_url,
                    snippet=r.snippet,
                    publish_date=r.publish_date,
                )
                for r in db_results
            ]

        # 히스토리에서 total_results 조회
        history = db.query(GoogleSearchHistory).filter_by(search_id=search_id).first()
        total_results = history.total_results if history else 0

        return SearchStatusResponse(
            search_id=search_id,
            query=queue_item.query,
            status=queue_item.status,
            total_results=total_results,
            error_message=queue_item.error_message,
            created_at=queue_item.created_at,
            started_at=queue_item.started_at,
            completed_at=queue_item.completed_at,
            results=results,
        )

    # 큐에 없으면 히스토리에서 확인 (과거 완료된 검색)
    history = db.query(GoogleSearchHistory).filter_by(search_id=search_id).first()
    if not history:
        raise HTTPException(status_code=404, detail="Search not found")

    results = []
    if history.status == "completed":
        db_results = (
            db.query(GoogleSearchResult)
            .filter_by(search_id=search_id)
            .order_by(GoogleSearchResult.rank)
            .all()
        )
        results = [
            SearchResult(
                rank=r.rank,
                title=r.title,
                url=r.url,
                display_url=r.display_url,
                snippet=r.snippet,
                publish_date=r.publish_date,
            )
            for r in db_results
        ]

    return SearchStatusResponse(
        search_id=search_id,
        query=history.query,
        status=history.status,
        total_results=history.total_results,
        error_message=history.error_message,
        created_at=history.created_at,
        started_at=history.started_at,
        completed_at=history.completed_at,
        results=results,
    )


@router.get("/results/{search_id}", response_model=SearchResponse)
async def get_results(
    search_id: str,
    db: Session = Depends(get_db),
):
    """검색 결과 조회.

    Args:
        search_id: 검색 세션 ID

    Returns:
        SearchResponse: 검색 결과
    """
    history = db.query(GoogleSearchHistory).filter_by(search_id=search_id).first()
    if not history:
        raise HTTPException(status_code=404, detail="Search not found")

    results = (
        db.query(GoogleSearchResult)
        .filter_by(search_id=search_id)
        .order_by(GoogleSearchResult.rank)
        .all()
    )

    return SearchResponse(
        search_id=search_id,
        query=history.query,
        status=history.status,
        total_results=history.total_results,
        results=[
            SearchResult(
                rank=r.rank,
                title=r.title,
                url=r.url,
                display_url=r.display_url,
                snippet=r.snippet,
                publish_date=r.publish_date,
            )
            for r in results
        ],
        created_at=history.created_at,
    )


@router.get("/history", response_model=List[SearchHistoryItem])
async def get_history(
    limit: int = Query(20, ge=1, le=100, description="조회할 개수"),
    db: Session = Depends(get_db),
):
    """검색 히스토리 조회.

    Args:
        limit: 조회할 개수 (기본 20개)

    Returns:
        List[SearchHistoryItem]: 검색 히스토리 목록
    """
    histories = (
        db.query(GoogleSearchHistory)
        .order_by(GoogleSearchHistory.created_at.desc())
        .limit(limit)
        .all()
    )

    return [
        SearchHistoryItem(
            search_id=h.search_id,
            query=h.query,
            date_filter=h.date_filter,
            status=h.status,
            total_results=h.total_results,
            created_at=h.created_at,
        )
        for h in histories
    ]


@router.delete("/history/{search_id}")
async def delete_search(
    search_id: str,
    db: Session = Depends(get_db),
):
    """검색 결과 삭제.

    Args:
        search_id: 검색 세션 ID

    Returns:
        삭제 성공 메시지
    """
    # 결과 삭제 (CASCADE로 자동 삭제되지만 명시적으로)
    db.query(GoogleSearchResult).filter_by(search_id=search_id).delete()
    deleted = db.query(GoogleSearchHistory).filter_by(search_id=search_id).delete()

    if not deleted:
        raise HTTPException(status_code=404, detail="Search not found")

    db.commit()
    return {"message": "Search deleted successfully"}


# ============================================================
# 저장된 검색 조건 API
# ============================================================


@router.get("/saved", response_model=List[SavedSearchResponse])
async def list_saved_searches(
    favorite_only: bool = Query(False, description="즐겨찾기만 조회"),
    db: Session = Depends(get_db),
):
    """저장된 검색 조건 목록 조회.

    Args:
        favorite_only: True면 즐겨찾기만 조회

    Returns:
        List[SavedSearchResponse]: 저장된 검색 조건 목록
    """
    query = db.query(GoogleSavedSearch)

    if favorite_only:
        query = query.filter(GoogleSavedSearch.is_favorite == True)

    saved_searches = query.order_by(
        GoogleSavedSearch.is_favorite.desc(),
        GoogleSavedSearch.updated_at.desc(),
    ).all()

    return [_saved_to_response(s) for s in saved_searches]


@router.post("/saved", response_model=SavedSearchResponse)
async def create_saved_search(
    data: SavedSearchCreate,
    db: Session = Depends(get_db),
):
    """검색 조건 저장.

    Args:
        data: 저장할 검색 조건

    Returns:
        SavedSearchResponse: 저장된 검색 조건
    """
    # search_params JSON 직렬화
    search_params_json = None
    if data.search_params:
        search_params_json = json.dumps(data.search_params)

    normalized_query, normalized_date_filter = _normalize_google_search_input(
        data.query,
        data.date_filter,
    )

    saved = GoogleSavedSearch(
        name=data.name,
        query=normalized_query,
        date_filter=normalized_date_filter,
        max_pages=data.max_pages,
        service_account_id=data.service_account_id,
        is_favorite=data.is_favorite,
        notify_on_new=data.notify_on_new,
        search_params=search_params_json,
    )
    db.add(saved)
    db.commit()
    db.refresh(saved)

    logger.info(f"Created saved search: {saved.name} (id={saved.id})")
    return _saved_to_response(saved)


@router.get("/saved/{saved_id}", response_model=SavedSearchResponse)
async def get_saved_search(
    saved_id: int,
    db: Session = Depends(get_db),
):
    """저장된 검색 조건 조회.

    Args:
        saved_id: 저장된 검색 ID

    Returns:
        SavedSearchResponse: 저장된 검색 조건
    """
    saved = db.query(GoogleSavedSearch).filter_by(id=saved_id).first()
    if not saved:
        raise HTTPException(status_code=404, detail="Saved search not found")

    return _saved_to_response(saved)


@router.put("/saved/{saved_id}", response_model=SavedSearchResponse)
async def update_saved_search(
    saved_id: int,
    data: SavedSearchUpdate,
    db: Session = Depends(get_db),
):
    """저장된 검색 조건 수정.

    Args:
        saved_id: 저장된 검색 ID
        data: 수정할 내용

    Returns:
        SavedSearchResponse: 수정된 검색 조건
    """
    saved = db.query(GoogleSavedSearch).filter_by(id=saved_id).first()
    if not saved:
        raise HTTPException(status_code=404, detail="Saved search not found")

    # 부분 업데이트
    update_data = data.model_dump(exclude_unset=True)
    if "query" in update_data:
        normalized_query, normalized_date_filter = _normalize_google_search_input(
            update_data["query"],
            update_data.get("date_filter"),
        )
        update_data["query"] = normalized_query
        if normalized_date_filter is not None:
            update_data["date_filter"] = normalized_date_filter

    for field, value in update_data.items():
        if field == "search_params" and value is not None:
            value = json.dumps(value)
        setattr(saved, field, value)

    saved.updated_at = datetime.now()
    db.commit()
    db.refresh(saved)

    logger.info(f"Updated saved search: {saved.name} (id={saved.id})")
    return _saved_to_response(saved)


@router.delete("/saved/{saved_id}")
async def delete_saved_search(
    saved_id: int,
    db: Session = Depends(get_db),
):
    """저장된 검색 조건 삭제.

    Args:
        saved_id: 저장된 검색 ID

    Returns:
        삭제 성공 메시지
    """
    deleted = db.query(GoogleSavedSearch).filter_by(id=saved_id).delete()
    if not deleted:
        raise HTTPException(status_code=404, detail="Saved search not found")

    db.commit()
    logger.info(f"Deleted saved search: id={saved_id}")
    return {"message": "Saved search deleted successfully"}


@router.post("/saved/{saved_id}/run", response_model=SearchQueueResponse, status_code=202)
async def run_saved_search(
    saved_id: int,
    db: Session = Depends(get_db),
):
    """저장된 검색 조건으로 검색 요청을 큐에 추가.

    검색 요청은 워커에서 비동기로 처리됩니다.
    결과는 GET /api/v1/google/search/{search_id}/status 에서 조회할 수 있습니다.

    Redis 연결 시 Redis 큐에 추가하고, 미연결 시 SQLite 폴링으로 처리됩니다.

    Args:
        saved_id: 저장된 검색 ID

    Returns:
        SearchQueueResponse: 검색 요청 ID와 상태
    """
    saved = db.query(GoogleSavedSearch).filter_by(id=saved_id).first()
    if not saved:
        raise HTTPException(status_code=404, detail="Saved search not found")

    search_id = str(uuid.uuid4())

    queue_item = GoogleSearchQueue(
        search_id=search_id,
        query=saved.query,
        date_filter=saved.date_filter,
        max_pages=saved.max_pages,
        service_account_id=saved.service_account_id,
        search_params=saved.search_params,
        saved_search_id=saved_id,
        status=GoogleSearchQueue.STATUS_QUEUED,
    )
    db.add(queue_item)
    db.commit()
    db.refresh(queue_item)

    status = await enqueue_google_search(queue_item, db)

    logger.info(
        "Saved search queued: search_id=%s, saved_id=%s, query=%s, mode=%s, status=%s",
        search_id,
        saved_id,
        saved.query,
        "redis" if status == GoogleSearchQueue.STATUS_QUEUED else "sqlite",
        status,
    )

    return SearchQueueResponse(
        search_id=search_id,
        status=status,
        message="저장된 검색이 큐에 추가되었습니다. 상태를 폴링하여 결과를 확인하세요.",
    )


@router.post("/saved/{saved_id}/toggle-favorite", response_model=SavedSearchResponse)
async def toggle_favorite(
    saved_id: int,
    db: Session = Depends(get_db),
):
    """즐겨찾기 토글.

    Args:
        saved_id: 저장된 검색 ID

    Returns:
        SavedSearchResponse: 토글된 검색 조건
    """
    saved = db.query(GoogleSavedSearch).filter_by(id=saved_id).first()
    if not saved:
        raise HTTPException(status_code=404, detail="Saved search not found")

    saved.is_favorite = not saved.is_favorite
    saved.updated_at = datetime.now()
    db.commit()
    db.refresh(saved)

    logger.debug(f"Toggled favorite for saved search: {saved.name} -> {saved.is_favorite}")
    return _saved_to_response(saved)


@router.post("/admin/recover-pending")
async def recover_pending_searches(
    db: Session = Depends(get_db),
):
    """누락된 pending Google 검색 요청을 Redis 큐로 복구."""
    result = await recover_pending_google_searches(db)
    logger.info(
        "Recovered pending google searches: pending_found=%s, recovered=%s, failed_push=%s",
        result["pending_found"],
        result["recovered"],
        result["failed_push"],
    )
    return JSONResponse(result)


# ============================================================
# Helper Functions
# ============================================================


def _saved_to_response(saved: GoogleSavedSearch) -> SavedSearchResponse:
    """SQLAlchemy 모델을 Pydantic 응답으로 변환."""
    # search_params JSON 역직렬화
    search_params = None
    if saved.search_params:
        try:
            search_params = json.loads(saved.search_params)
        except (json.JSONDecodeError, TypeError):
            search_params = None

    return SavedSearchResponse(
        id=saved.id,
        name=saved.name,
        query=saved.query,
        date_filter=saved.date_filter,
        max_pages=saved.max_pages,
        service_account_id=saved.service_account_id,
        is_favorite=saved.is_favorite,
        notify_on_new=bool(saved.notify_on_new),
        search_params=search_params,
        last_search_id=saved.last_search_id,
        last_run_at=saved.last_run_at,
        last_result_count=saved.last_result_count,
        created_at=saved.created_at,
        updated_at=saved.updated_at,
    )

