"""
Google 검색 API 라우트

검색 수행, 결과 조회, 히스토리 관리, 저장된 검색 조건 CRUD API를 제공합니다.
"""

import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.shared.browser import ContextManager
from app.models.google_search import (
    GoogleSavedSearch,
    GoogleSearchHistory,
    GoogleSearchResult,
)
from app.modules.google_search.models.schemas import (
    SearchRequest,
    SearchResult,
    SearchResponse,
    SearchHistoryItem,
    SavedSearchCreate,
    SavedSearchUpdate,
    SavedSearchResponse,
)
from app.modules.google_search.services.crawler import (
    GoogleSearchService,
    CaptchaDetectedError,
)

logger = logging.getLogger("google_search.routes")

router = APIRouter(prefix="/api/google", tags=["google-search"])

# 전역 ContextManager (다른 모듈과 공유)
_context_manager: Optional[ContextManager] = None


async def get_context_manager() -> ContextManager:
    """ContextManager 인스턴스 반환."""
    global _context_manager
    if _context_manager is None:
        _context_manager = ContextManager()
    return _context_manager


def set_context_manager(cm: ContextManager) -> None:
    """외부에서 ContextManager 설정 (다른 모듈과 공유 시)."""
    global _context_manager
    _context_manager = cm


# ============================================================
# 검색 API
# ============================================================


@router.post("/search", response_model=SearchResponse)
async def search(
    request: SearchRequest,
    db: Session = Depends(get_db),
    cm: ContextManager = Depends(get_context_manager),
):
    """구글 검색 수행.

    Args:
        request: 검색 요청 (query, date_filter, max_pages, service_account_id)

    Returns:
        SearchResponse: 검색 결과
    """
    try:
        service = GoogleSearchService(cm, db)
        result = await service.search(
            query=request.query,
            date_filter=request.date_filter,
            max_pages=min(request.max_pages, 10),  # 최대 10페이지
            service_account_id=request.service_account_id,
        )

        return SearchResponse(
            search_id=result.search_id,
            query=result.query,
            status=result.status,
            total_results=result.total_results,
            results=[
                SearchResult(
                    rank=r.rank,
                    title=r.title,
                    url=r.url,
                    display_url=r.display_url,
                    snippet=r.snippet,
                    publish_date=r.publish_date,
                )
                for r in result.results
            ],
            created_at=result.started_at or datetime.now(),
        )

    except CaptchaDetectedError as e:
        logger.warning(f"CAPTCHA detected for query: {request.query}")
        raise HTTPException(
            status_code=503,
            detail="CAPTCHA 감지됨. 수동 해결이 필요합니다."
        )

    except Exception as e:
        logger.error(f"Search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
    saved = GoogleSavedSearch(
        name=data.name,
        query=data.query,
        date_filter=data.date_filter,
        max_pages=data.max_pages,
        service_account_id=data.service_account_id,
        is_favorite=data.is_favorite,
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
    for field, value in update_data.items():
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


@router.post("/saved/{saved_id}/run", response_model=SearchResponse)
async def run_saved_search(
    saved_id: int,
    db: Session = Depends(get_db),
    cm: ContextManager = Depends(get_context_manager),
):
    """저장된 검색 조건으로 검색 실행.

    Args:
        saved_id: 저장된 검색 ID

    Returns:
        SearchResponse: 검색 결과
    """
    saved = db.query(GoogleSavedSearch).filter_by(id=saved_id).first()
    if not saved:
        raise HTTPException(status_code=404, detail="Saved search not found")

    try:
        service = GoogleSearchService(cm, db)
        result = await service.run_saved_search(saved_id)

        return SearchResponse(
            search_id=result.search_id,
            query=result.query,
            status=result.status,
            total_results=result.total_results,
            results=[
                SearchResult(
                    rank=r.rank,
                    title=r.title,
                    url=r.url,
                    display_url=r.display_url,
                    snippet=r.snippet,
                    publish_date=r.publish_date,
                )
                for r in result.results
            ],
            created_at=result.started_at or datetime.now(),
        )

    except CaptchaDetectedError:
        logger.warning(f"CAPTCHA detected for saved search: {saved.name}")
        raise HTTPException(
            status_code=503,
            detail="CAPTCHA 감지됨. 수동 해결이 필요합니다."
        )

    except Exception as e:
        logger.error(f"Run saved search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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


# ============================================================
# Helper Functions
# ============================================================


def _saved_to_response(saved: GoogleSavedSearch) -> SavedSearchResponse:
    """SQLAlchemy 모델을 Pydantic 응답으로 변환."""
    return SavedSearchResponse(
        id=saved.id,
        name=saved.name,
        query=saved.query,
        date_filter=saved.date_filter,
        max_pages=saved.max_pages,
        service_account_id=saved.service_account_id,
        is_favorite=saved.is_favorite,
        last_search_id=saved.last_search_id,
        last_run_at=saved.last_run_at,
        last_result_count=saved.last_result_count,
        created_at=saved.created_at,
        updated_at=saved.updated_at,
    )
