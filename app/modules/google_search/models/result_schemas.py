"""
검색결과 관리 Pydantic 스키마 정의
"""
from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, Field


class RankHistoryItem(BaseModel):
    """동일 URL의 런별 순위 히스토리"""
    search_id: str
    rank: int
    created_at: datetime


class SearchResultListItem(BaseModel):
    """결과 목록 아이템"""
    id: int
    search_id: str
    query: str
    rank: int
    title: str
    url: str
    display_url: Optional[str] = None
    snippet: Optional[str] = None
    publish_date: Optional[str] = None
    page_number: int
    is_new: bool = False
    rank_change: Optional[int] = None
    prev_rank: Optional[int] = None
    is_read: bool = False
    is_bookmarked: bool = False
    memo: Optional[str] = None
    created_at: datetime
    # 조인 필드
    saved_search_name: Optional[str] = None
    schedule_name: Optional[str] = None

    class Config:
        from_attributes = True


class SearchResultDetail(SearchResultListItem):
    """결과 상세 (글 정보)"""
    search_date_filter: Optional[str] = None
    search_status: str = ""
    search_total_results: int = 0
    search_created_at: Optional[datetime] = None
    # 동일 URL의 히스토리 (순위 변화 추적)
    rank_history: List[RankHistoryItem] = Field(default_factory=list)
    # 사라진 적 있는지
    disappeared_count: int = 0


class DisappearedResultItem(BaseModel):
    """사라진 결과 아이템 (쿼리 시점 비교, 별도 테이블 없음)"""
    search_id: str           # 이전 런의 search_id
    query: str
    url: str
    title: Optional[str] = None
    rank: int                # 이전 런에서의 순위
    snippet: Optional[str] = None
    created_at: datetime     # 이전 런의 수집 시각


class SearchResultsListResponse(BaseModel):
    """페이지네이션 응답"""
    items: List[SearchResultListItem]
    total: int
    page: int
    page_size: int


class DisappearedResultsResponse(BaseModel):
    """사라진 결과 목록 응답"""
    items: List[DisappearedResultItem]
    total: int
    page: int
    page_size: int


class QueryStatsItem(BaseModel):
    """쿼리별 통계 아이템"""
    query: str
    total: int
    new_count: int
    latest_search_at: Optional[datetime] = None


class ResultStatsResponse(BaseModel):
    """통계 응답"""
    total_results: int
    new_results: int
    new_rate: float
    by_query: List[QueryStatsItem] = Field(default_factory=list)


class ToggleReadResponse(BaseModel):
    """읽음 토글 응답"""
    is_read: bool


class ToggleBookmarkResponse(BaseModel):
    """북마크 토글 응답"""
    is_bookmarked: bool


class UpdateMemoRequest(BaseModel):
    """메모 수정 요청"""
    memo: Optional[str] = None


class UpdateMemoResponse(BaseModel):
    """메모 수정 응답"""
    memo: Optional[str] = None


class SearchResultListParams(BaseModel):
    """검색 결과 목록 요청 파라미터"""
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)
    query: Optional[str] = None
    search: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    is_new: Optional[bool] = None
    is_bookmarked: Optional[bool] = None
    is_read: Optional[bool] = None
    saved_search_id: Optional[int] = None
    schedule_id: Optional[int] = None
    sort_by: str = Field("created_at", pattern="^(created_at|rank|rank_change|query|publish_date)$")
    sort_order: str = Field("desc", pattern="^(asc|desc)$")
