"""
검색결과 관리 API 라우트
"""
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, or_, desc, asc

from app.database import get_db
from app.models.google_search import (
    GoogleSearchResult,
    GoogleSearchHistory,
    GoogleSavedSearch,
    GoogleSearchQueue,
)
from app.models.task_schedule import TaskSchedule
from app.modules.google_search.models.result_schemas import (
    SearchResultListItem,
    SearchResultDetail,
    SearchResultsListResponse,
    DisappearedResultItem,
    DisappearedResultsResponse,
    ResultStatsResponse,
    QueryStatsItem,
    RankHistoryItem,
    ToggleReadResponse,
    ToggleBookmarkResponse,
    UpdateMemoRequest,
    UpdateMemoResponse,
)

router = APIRouter(
    prefix="/api/v1/google/results",
    tags=["google-results"],
)


@router.get("/all", response_model=SearchResultsListResponse)
def get_all_results(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    query: Optional[str] = Query(None, description="검색 키워드 필터"),
    search: Optional[str] = Query(None, description="제목/URL/스니펫 전체 검색"),
    date_from: Optional[str] = Query(None, description="수집 시작일 (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="수집 종료일 (YYYY-MM-DD)"),
    is_new: Optional[bool] = Query(None, description="신규 여부 필터"),
    is_bookmarked: Optional[bool] = Query(None, description="북마크 필터"),
    is_read: Optional[bool] = Query(None, description="읽음 필터"),
    saved_search_id: Optional[int] = Query(None, description="저장된 검색 필터"),
    schedule_id: Optional[int] = Query(None, description="스케줄 필터"),
    sort_by: str = Query("created_at", description="정렬 기준"),
    sort_order: str = Query("desc", description="정렬 순서"),
    db: Session = Depends(get_db),
):
    """통합 검색결과 목록 조회"""
    # 기본 쿼리 - GoogleSearchQueue와 조인하여 saved_search_name, schedule_name 가져오기
    base_query = db.query(GoogleSearchResult)

    # 필터 적용
    if query:
        base_query = base_query.filter(GoogleSearchResult.query.ilike(f"%{query}%"))

    if search:
        base_query = base_query.filter(
            or_(
                GoogleSearchResult.title.ilike(f"%{search}%"),
                GoogleSearchResult.url.ilike(f"%{search}%"),
                GoogleSearchResult.snippet.ilike(f"%{search}%"),
            )
        )

    if date_from:
        try:
            from_date = datetime.strptime(date_from, "%Y-%m-%d")
            base_query = base_query.filter(GoogleSearchResult.created_at >= from_date)
        except ValueError:
            pass

    if date_to:
        try:
            to_date = datetime.strptime(date_to, "%Y-%m-%d")
            # 해당 일자 끝까지 포함
            to_date = to_date.replace(hour=23, minute=59, second=59)
            base_query = base_query.filter(GoogleSearchResult.created_at <= to_date)
        except ValueError:
            pass

    if is_new is not None:
        base_query = base_query.filter(GoogleSearchResult.is_new == is_new)

    if is_bookmarked is not None:
        base_query = base_query.filter(GoogleSearchResult.is_bookmarked == is_bookmarked)

    if is_read is not None:
        base_query = base_query.filter(GoogleSearchResult.is_read == is_read)

    if saved_search_id:
        # GoogleSearchQueue를 통해 saved_search_id로 필터링
        queue_search_ids = db.query(GoogleSearchQueue.search_id).filter(
            GoogleSearchQueue.saved_search_id == saved_search_id
        ).subquery()
        base_query = base_query.filter(GoogleSearchResult.search_id.in_(queue_search_ids))

    if schedule_id:
        # GoogleSearchQueue를 통해 schedule_id로 필터링
        queue_search_ids = db.query(GoogleSearchQueue.search_id).filter(
            GoogleSearchQueue.schedule_id == schedule_id
        ).subquery()
        base_query = base_query.filter(GoogleSearchResult.search_id.in_(queue_search_ids))

    # 총 개수
    total = base_query.count()

    # 정렬
    sort_column = getattr(GoogleSearchResult, sort_by, GoogleSearchResult.created_at)
    if sort_order == "desc":
        base_query = base_query.order_by(desc(sort_column))
    else:
        base_query = base_query.order_by(asc(sort_column))

    # 페이지네이션
    offset = (page - 1) * page_size
    results = base_query.offset(offset).limit(page_size).all()

    # search_id -> (saved_search_name, schedule_name) 매핑 구축
    search_ids = [r.search_id for r in results]
    queue_map = {}
    if search_ids:
        queue_items = db.query(
            GoogleSearchQueue.search_id,
            GoogleSavedSearch.name.label("saved_search_name"),
            TaskSchedule.name.label("schedule_name"),
        ).outerjoin(
            GoogleSavedSearch, GoogleSearchQueue.saved_search_id == GoogleSavedSearch.id
        ).outerjoin(
            TaskSchedule, GoogleSearchQueue.schedule_id == TaskSchedule.id
        ).filter(
            GoogleSearchQueue.search_id.in_(search_ids)
        ).all()

        for item in queue_items:
            queue_map[item.search_id] = {
                "saved_search_name": item.saved_search_name,
                "schedule_name": item.schedule_name,
            }

    # 응답 생성
    items = []
    for r in results:
        queue_info = queue_map.get(r.search_id, {})
        items.append(SearchResultListItem(
            id=r.id,
            search_id=r.search_id,
            query=r.query,
            rank=r.rank,
            title=r.title,
            url=r.url,
            display_url=r.display_url,
            snippet=r.snippet,
            publish_date=r.publish_date,
            page_number=r.page_number,
            is_new=r.is_new or False,
            rank_change=r.rank_change,
            prev_rank=r.prev_rank,
            is_read=r.is_read or False,
            is_bookmarked=r.is_bookmarked or False,
            memo=r.memo,
            created_at=r.created_at,
            saved_search_name=queue_info.get("saved_search_name"),
            schedule_name=queue_info.get("schedule_name"),
        ))

    return SearchResultsListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/stats", response_model=ResultStatsResponse)
def get_result_stats(db: Session = Depends(get_db)):
    """검색결과 통계 조회"""
    # 전체 결과 수
    total_results = db.query(func.count(GoogleSearchResult.id)).scalar() or 0

    # 신규 결과 수
    new_results = db.query(func.count(GoogleSearchResult.id)).filter(
        GoogleSearchResult.is_new == True
    ).scalar() or 0

    # 신규 비율
    new_rate = (new_results / total_results * 100) if total_results > 0 else 0

    # 쿼리별 통계
    by_query_raw = db.query(
        GoogleSearchResult.query,
        func.count(GoogleSearchResult.id).label("total"),
        func.sum(func.cast(GoogleSearchResult.is_new, type_=db.bind.dialect.type_descriptor(type(1)))).label("new_count"),
        func.max(GoogleSearchResult.created_at).label("latest_search_at"),
    ).group_by(GoogleSearchResult.query).order_by(desc("total")).limit(20).all()

    by_query = [
        QueryStatsItem(
            query=row.query,
            total=row.total,
            new_count=row.new_count or 0,
            latest_search_at=row.latest_search_at,
        )
        for row in by_query_raw
    ]

    return ResultStatsResponse(
        total_results=total_results,
        new_results=new_results,
        new_rate=round(new_rate, 2),
        by_query=by_query,
    )


@router.get("/disappeared", response_model=DisappearedResultsResponse)
def get_disappeared_results(
    saved_search_id: Optional[int] = Query(None, description="저장된 검색 ID"),
    query: Optional[str] = Query(None, description="검색어 필터"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """사라진 결과 목록 조회 (직전 런과 현재 런 비교)"""
    # 저장된 검색의 최근 2개 런 조회
    base_query = db.query(GoogleSearchQueue.search_id).filter(
        GoogleSearchQueue.status == "completed"
    )

    if saved_search_id:
        base_query = base_query.filter(GoogleSearchQueue.saved_search_id == saved_search_id)
    elif query:
        base_query = base_query.filter(GoogleSearchQueue.query.ilike(f"%{query}%"))

    recent_runs = base_query.order_by(desc(GoogleSearchQueue.completed_at)).limit(2).all()

    if len(recent_runs) < 2:
        return DisappearedResultsResponse(items=[], total=0, page=page, page_size=page_size)

    current_search_id = recent_runs[0].search_id
    prev_search_id = recent_runs[1].search_id

    # 현재 런의 URL 집합
    current_urls = set(
        r.url for r in db.query(GoogleSearchResult.url).filter(
            GoogleSearchResult.search_id == current_search_id
        ).all()
    )

    # 이전 런에서 현재 런에 없는 결과 조회
    prev_results_query = db.query(GoogleSearchResult).filter(
        GoogleSearchResult.search_id == prev_search_id
    )

    prev_results = prev_results_query.all()
    disappeared = [r for r in prev_results if r.url not in current_urls]

    total = len(disappeared)

    # 페이지네이션
    start = (page - 1) * page_size
    end = start + page_size
    paginated = disappeared[start:end]

    items = [
        DisappearedResultItem(
            search_id=r.search_id,
            query=r.query,
            url=r.url,
            title=r.title,
            rank=r.rank,
            snippet=r.snippet,
            created_at=r.created_at,
        )
        for r in paginated
    ]

    return DisappearedResultsResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{result_id}", response_model=SearchResultDetail)
def get_result_detail(result_id: int, db: Session = Depends(get_db)):
    """검색결과 상세 조회"""
    result = db.query(GoogleSearchResult).filter(GoogleSearchResult.id == result_id).first()

    if not result:
        raise HTTPException(status_code=404, detail="검색결과를 찾을 수 없습니다.")

    # 검색 히스토리 정보
    history = db.query(GoogleSearchHistory).filter(
        GoogleSearchHistory.search_id == result.search_id
    ).first()

    # 동일 URL의 순위 히스토리
    rank_history_raw = db.query(GoogleSearchResult).filter(
        GoogleSearchResult.url == result.url,
        GoogleSearchResult.query == result.query,
    ).order_by(desc(GoogleSearchResult.created_at)).limit(10).all()

    rank_history = [
        RankHistoryItem(
            search_id=r.search_id,
            rank=r.rank,
            created_at=r.created_at,
        )
        for r in rank_history_raw
    ]

    # Queue 정보에서 saved_search_name, schedule_name 가져오기
    queue_info = db.query(
        GoogleSavedSearch.name.label("saved_search_name"),
        TaskSchedule.name.label("schedule_name"),
    ).select_from(GoogleSearchQueue).outerjoin(
        GoogleSavedSearch, GoogleSearchQueue.saved_search_id == GoogleSavedSearch.id
    ).outerjoin(
        TaskSchedule, GoogleSearchQueue.schedule_id == TaskSchedule.id
    ).filter(
        GoogleSearchQueue.search_id == result.search_id
    ).first()

    # 사라진 횟수 계산 (이 URL이 이전에 존재했다가 사라진 런 수)
    # 간단히 구현: 이 URL이 포함된 런 수와 전체 런 수의 차이
    disappeared_count = 0  # TODO: 필요시 구현

    return SearchResultDetail(
        id=result.id,
        search_id=result.search_id,
        query=result.query,
        rank=result.rank,
        title=result.title,
        url=result.url,
        display_url=result.display_url,
        snippet=result.snippet,
        publish_date=result.publish_date,
        page_number=result.page_number,
        is_new=result.is_new or False,
        rank_change=result.rank_change,
        prev_rank=result.prev_rank,
        is_read=result.is_read or False,
        is_bookmarked=result.is_bookmarked or False,
        memo=result.memo,
        created_at=result.created_at,
        saved_search_name=queue_info.saved_search_name if queue_info else None,
        schedule_name=queue_info.schedule_name if queue_info else None,
        search_date_filter=history.date_filter if history else None,
        search_status=history.status if history else "",
        search_total_results=history.total_results if history else 0,
        search_created_at=history.created_at if history else None,
        rank_history=rank_history,
        disappeared_count=disappeared_count,
    )


@router.post("/{result_id}/toggle-read", response_model=ToggleReadResponse)
def toggle_read(result_id: int, db: Session = Depends(get_db)):
    """읽음 상태 토글"""
    result = db.query(GoogleSearchResult).filter(GoogleSearchResult.id == result_id).first()

    if not result:
        raise HTTPException(status_code=404, detail="검색결과를 찾을 수 없습니다.")

    result.is_read = not (result.is_read or False)
    db.commit()

    return ToggleReadResponse(is_read=result.is_read)


@router.post("/{result_id}/toggle-bookmark", response_model=ToggleBookmarkResponse)
def toggle_bookmark(result_id: int, db: Session = Depends(get_db)):
    """북마크 상태 토글"""
    result = db.query(GoogleSearchResult).filter(GoogleSearchResult.id == result_id).first()

    if not result:
        raise HTTPException(status_code=404, detail="검색결과를 찾을 수 없습니다.")

    result.is_bookmarked = not (result.is_bookmarked or False)
    db.commit()

    return ToggleBookmarkResponse(is_bookmarked=result.is_bookmarked)


@router.put("/{result_id}/memo", response_model=UpdateMemoResponse)
def update_memo(
    result_id: int,
    request: UpdateMemoRequest,
    db: Session = Depends(get_db),
):
    """메모 수정"""
    result = db.query(GoogleSearchResult).filter(GoogleSearchResult.id == result_id).first()

    if not result:
        raise HTTPException(status_code=404, detail="검색결과를 찾을 수 없습니다.")

    result.memo = request.memo
    db.commit()

    return UpdateMemoResponse(memo=result.memo)
