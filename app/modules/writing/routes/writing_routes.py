"""Writing API Routes - 글 생성 관리 API."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.writing.services.writing_service import WritingService

router = APIRouter(prefix="/api/writing", tags=["writing"])


# ========== Pydantic 스키마 ==========


class WritingUpdateRequest(BaseModel):
    """글 수정 요청."""

    content: Optional[str] = None


class RatingRequest(BaseModel):
    """평가 요청."""

    rating: Optional[int] = None  # 1: 추천, -1: 비추천, None: 취소


class SourceCreateRequest(BaseModel):
    """소스 생성 요청."""

    content: str
    category: Optional[str] = None
    source_info: Optional[str] = None


class BulkSourceRequest(BaseModel):
    """소스 일괄 생성 요청."""

    sources: list[dict]


class FeedCreateRequest(BaseModel):
    """RSS 피드 생성 요청."""

    name: str
    url: str
    source_type: str = "tistory"


class FeedUpdateRequest(BaseModel):
    """RSS 피드 수정 요청."""

    name: Optional[str] = None
    url: Optional[str] = None
    enabled: Optional[bool] = None


class SearchQueryCreateRequest(BaseModel):
    """검색 쿼리 생성 요청."""

    query: str
    source_type: str = "naver"  # 'naver', 'kakao', 'google'
    search_target: str = "blog"  # 'blog', 'cafe', 'news'
    priority: int = 0


class SearchQueryUpdateRequest(BaseModel):
    """검색 쿼리 수정 요청."""

    query: Optional[str] = None
    source_type: Optional[str] = None
    search_target: Optional[str] = None
    enabled: Optional[bool] = None
    priority: Optional[int] = None


# ========== 생성된 글 조회 ==========


@router.get("/generated")
def list_generated_writings(
    task_type: Optional[str] = None,
    rating: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """생성된 글 목록 조회."""
    service = WritingService(db)

    # rating 파라미터 파싱
    rating_value = None
    if rating is not None:
        if rating == "null":
            rating_value = 0  # 미평가
        elif rating in ("1", "-1"):
            rating_value = int(rating)

    result = service.list_generated_writings(
        task_type=task_type,
        rating=rating_value,
        page=page,
        page_size=page_size,
    )

    return {
        "items": [_writing_to_dict(w) for w in result["items"]],
        "total": result["total"],
        "page": result["page"],
        "page_size": result["page_size"],
        "pages": result["pages"],
    }


@router.get("/generated/{writing_id}")
def get_generated_writing(
    writing_id: int,
    db: Session = Depends(get_db),
):
    """생성된 글 상세 조회."""
    service = WritingService(db)
    writing = service.get_generated_writing(writing_id)
    if not writing:
        raise HTTPException(404, "Writing not found")
    return _writing_to_dict(writing, include_full=True)


# ========== 글 관리 ==========


@router.put("/generated/{writing_id}")
def update_generated_writing(
    writing_id: int,
    data: WritingUpdateRequest,
    db: Session = Depends(get_db),
):
    """생성된 글 수정."""
    service = WritingService(db)
    writing = service.update_generated_writing(
        writing_id=writing_id,
        content=data.content,
    )
    if not writing:
        raise HTTPException(404, "Writing not found")
    return _writing_to_dict(writing, include_full=True)


@router.delete("/generated/{writing_id}")
def delete_generated_writing(
    writing_id: int,
    hard: bool = False,
    db: Session = Depends(get_db),
):
    """생성된 글 삭제 (기본: soft delete)."""
    service = WritingService(db)
    success = service.delete_generated_writing(writing_id, hard_delete=hard)
    if not success:
        raise HTTPException(404, "Writing not found")
    return {"deleted": True}


@router.post("/generated/{writing_id}/rate")
def rate_generated_writing(
    writing_id: int,
    data: RatingRequest,
    db: Session = Depends(get_db),
):
    """생성된 글 평가 (추천/비추천)."""
    if data.rating is not None and data.rating not in (1, -1):
        raise HTTPException(400, "rating must be 1, -1, or null")

    service = WritingService(db)
    writing = service.rate_generated_writing(writing_id, data.rating)
    if not writing:
        raise HTTPException(404, "Writing not found")

    return {"id": writing_id, "rating": data.rating}


# ========== 소스 관리 ==========


@router.get("/sources")
def list_sources(
    category: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """글 소스 목록 조회."""
    service = WritingService(db)
    result = service.list_sources(
        category=category,
        page=page,
        page_size=page_size,
    )

    return {
        "items": [
            {
                "id": s.id,
                "category": s.category,
                "source_info": s.source_info,
                "preview": s.content[:100] if s.content else "",
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in result["items"]
        ],
        "total": result["total"],
        "page": result["page"],
        "page_size": result["page_size"],
        "pages": result["pages"],
    }


@router.get("/sources/{source_id}")
def get_source(
    source_id: int,
    db: Session = Depends(get_db),
):
    """글 소스 상세 조회."""
    from app.models.writing import WritingSource

    source = db.query(WritingSource).filter(WritingSource.id == source_id).first()
    if not source:
        raise HTTPException(404, "Source not found")

    return {
        "id": source.id,
        "content": source.content,
        "category": source.category,
        "source_info": source.source_info,
        "created_at": source.created_at.isoformat() if source.created_at else None,
    }


@router.post("/sources")
def add_source(
    data: SourceCreateRequest,
    db: Session = Depends(get_db),
):
    """글 소스 추가."""
    service = WritingService(db)
    source = service.add_source(
        content=data.content,
        category=data.category,
        source_info=data.source_info,
    )
    return {
        "id": source.id,
        "category": source.category,
        "created_at": source.created_at.isoformat() if source.created_at else None,
    }


@router.post("/sources/bulk")
def bulk_add_sources(
    data: BulkSourceRequest,
    db: Session = Depends(get_db),
):
    """소스 일괄 추가."""
    service = WritingService(db)
    added = service.bulk_add_sources(data.sources)
    return {"added": added}


@router.delete("/sources/{source_id}")
def delete_source(
    source_id: int,
    db: Session = Depends(get_db),
):
    """글 소스 삭제."""
    service = WritingService(db)
    success = service.delete_source(source_id)
    if not success:
        raise HTTPException(404, "Source not found")
    return {"deleted": True}


# ========== 통계 ==========


@router.get("/stats")
def get_stats(db: Session = Depends(get_db)):
    """통계 조회."""
    service = WritingService(db)
    return service.get_stats()


# ========== 실행 ==========


@router.post("/run")
def run_writing_task(db: Session = Depends(get_db)):
    """작문 태스크 수동 실행."""
    service = WritingService(db)
    try:
        result = service.run_writing_task()
        return result
    except Exception as e:
        raise HTTPException(500, str(e))


# ========== 헬퍼 함수 ==========


def _writing_to_dict(writing, include_full: bool = False) -> dict:
    """GeneratedWriting을 dict로 변환."""
    result = {
        "id": writing.id,
        "task_type": writing.task_type,
        "source_ids": writing.get_source_id_list(),
        "rating": writing.rating,
        "created_at": writing.created_at.isoformat() if writing.created_at else None,
        "preview": writing.content[:200] if writing.content else "",
    }

    if include_full:
        result["content"] = writing.content
        result["raw_response"] = writing.raw_response
        result["prompt_used"] = writing.prompt_used
        result["schedule_run_id"] = writing.schedule_run_id
        result["updated_at"] = (
            writing.updated_at.isoformat() if writing.updated_at else None
        )

    return result


def _feed_to_dict(feed) -> dict:
    """WritingRssFeed를 dict로 변환."""
    return {
        "id": feed.id,
        "name": feed.name,
        "url": feed.url,
        "source_type": feed.source_type,
        "enabled": bool(feed.enabled),
        "last_fetched_at": feed.last_fetched_at.isoformat() if feed.last_fetched_at else None,
        "fetch_count": feed.fetch_count,
        "error_count": feed.error_count,
        "last_error": feed.last_error,
        "created_at": feed.created_at.isoformat() if feed.created_at else None,
    }


# ========== RSS 피드 관리 ==========


@router.get("/feeds")
def list_feeds(
    source_type: Optional[str] = None,
    include_disabled: bool = False,
    db: Session = Depends(get_db),
):
    """RSS 피드 목록 조회."""
    service = WritingService(db)
    feeds = service.list_feeds(
        source_type=source_type,
        enabled_only=not include_disabled,
    )
    return {"items": [_feed_to_dict(f) for f in feeds], "total": len(feeds)}


@router.get("/feeds/{feed_id}")
def get_feed(
    feed_id: int,
    db: Session = Depends(get_db),
):
    """RSS 피드 상세 조회."""
    service = WritingService(db)
    feed = service.get_feed(feed_id)
    if not feed:
        raise HTTPException(404, "Feed not found")
    return _feed_to_dict(feed)


@router.post("/feeds")
def add_feed(
    data: FeedCreateRequest,
    db: Session = Depends(get_db),
):
    """RSS 피드 추가."""
    service = WritingService(db)
    try:
        feed = service.add_feed(
            name=data.name,
            url=data.url,
            source_type=data.source_type,
        )
        return _feed_to_dict(feed)
    except Exception as e:
        raise HTTPException(400, f"Failed to add feed: {e}")


@router.put("/feeds/{feed_id}")
def update_feed(
    feed_id: int,
    data: FeedUpdateRequest,
    db: Session = Depends(get_db),
):
    """RSS 피드 수정."""
    service = WritingService(db)
    feed = service.update_feed(
        feed_id=feed_id,
        name=data.name,
        url=data.url,
        enabled=data.enabled,
    )
    if not feed:
        raise HTTPException(404, "Feed not found")
    return _feed_to_dict(feed)


@router.delete("/feeds/{feed_id}")
def delete_feed(
    feed_id: int,
    db: Session = Depends(get_db),
):
    """RSS 피드 삭제."""
    service = WritingService(db)
    success = service.delete_feed(feed_id)
    if not success:
        raise HTTPException(404, "Feed not found")
    return {"deleted": True}


@router.post("/feeds/collect")
async def collect_from_feeds(
    min_length: int = Query(300, ge=100, le=1000),
    max_length: int = Query(3000, ge=500, le=10000),
    db: Session = Depends(get_db),
):
    """모든 활성 RSS 피드에서 글 수집."""
    service = WritingService(db)
    try:
        result = await service.collect_from_feeds(
            min_length=min_length,
            max_length=max_length,
        )
        return result
    except Exception as e:
        raise HTTPException(500, f"Collection failed: {e}")


# ========== 검색 쿼리 관리 ==========


def _query_to_dict(query) -> dict:
    """WritingSearchQuery를 dict로 변환."""
    return {
        "id": query.id,
        "query": query.query,
        "source_type": query.source_type,
        "search_target": query.search_target,
        "enabled": bool(query.enabled),
        "priority": query.priority,
        "last_searched_at": (
            query.last_searched_at.isoformat() if query.last_searched_at else None
        ),
        "result_count": query.result_count,
        "success_count": query.success_count,
        "error_count": query.error_count,
        "last_error": query.last_error,
        "created_at": query.created_at.isoformat() if query.created_at else None,
    }


@router.get("/search-queries")
def list_search_queries(
    source_type: Optional[str] = None,
    include_disabled: bool = False,
    db: Session = Depends(get_db),
):
    """검색 쿼리 목록 조회."""
    service = WritingService(db)
    queries = service.list_search_queries(
        source_type=source_type,
        enabled_only=not include_disabled,
    )
    return {"items": [_query_to_dict(q) for q in queries], "total": len(queries)}


@router.get("/search-queries/{query_id}")
def get_search_query(
    query_id: int,
    db: Session = Depends(get_db),
):
    """검색 쿼리 상세 조회."""
    service = WritingService(db)
    query = service.get_search_query(query_id)
    if not query:
        raise HTTPException(404, "Query not found")
    return _query_to_dict(query)


@router.post("/search-queries")
def add_search_query(
    data: SearchQueryCreateRequest,
    db: Session = Depends(get_db),
):
    """검색 쿼리 추가."""
    service = WritingService(db)
    query = service.add_search_query(
        query=data.query,
        source_type=data.source_type,
        search_target=data.search_target,
        priority=data.priority,
    )
    return _query_to_dict(query)


@router.put("/search-queries/{query_id}")
def update_search_query(
    query_id: int,
    data: SearchQueryUpdateRequest,
    db: Session = Depends(get_db),
):
    """검색 쿼리 수정."""
    service = WritingService(db)
    query = service.update_search_query(
        query_id=query_id,
        query=data.query,
        source_type=data.source_type,
        search_target=data.search_target,
        enabled=data.enabled,
        priority=data.priority,
    )
    if not query:
        raise HTTPException(404, "Query not found")
    return _query_to_dict(query)


@router.delete("/search-queries/{query_id}")
def delete_search_query(
    query_id: int,
    db: Session = Depends(get_db),
):
    """검색 쿼리 삭제."""
    service = WritingService(db)
    success = service.delete_search_query(query_id)
    if not success:
        raise HTTPException(404, "Query not found")
    return {"deleted": True}


@router.post("/search-queries/collect")
async def collect_from_searches(
    source_type: Optional[str] = None,
    min_length: int = Query(100, ge=50, le=1000),
    max_length: int = Query(5000, ge=500, le=10000),
    max_queries: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    """검색 API에서 글 수집."""
    service = WritingService(db)
    try:
        result = await service.collect_from_searches(
            source_type=source_type,
            min_length=min_length,
            max_length=max_length,
            max_queries=max_queries,
        )
        return result
    except Exception as e:
        raise HTTPException(500, f"Collection failed: {e}")
