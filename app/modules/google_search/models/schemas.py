"""
Google 검색 Pydantic 스키마 정의
"""
from datetime import datetime
from typing import Optional, List, Dict, Any

from pydantic import BaseModel, Field


# === 검색 요청/응답 스키마 ===


class SearchRequest(BaseModel):
    """검색 요청 스키마."""

    query: str = Field(..., min_length=1, max_length=500, description="검색 키워드")
    date_filter: Optional[str] = Field(
        None,
        pattern="^(1h|24h|1w|1m|1y)$",
        description="날짜 필터 (1h, 24h, 1w, 1m, 1y)",
    )
    max_pages: int = Field(1, ge=1, le=10, description="수집할 페이지 수 (1-10)")
    service_account_id: Optional[int] = Field(None, description="브라우저 프로필 ID")
    search_params: Optional[Dict[str, Any]] = Field(None, description="추가 검색 파라미터 (lr, cr, as_sitesearch, num)")


class SearchParams(BaseModel):
    """추가 검색 파라미터."""

    lr: Optional[str] = Field(None, description="언어 제한 (lang_ko 등)")
    cr: Optional[str] = Field(None, description="국가 제한 (countryKR 등)")
    as_sitesearch: Optional[str] = Field(None, description="사이트 내 검색")
    num: Optional[int] = Field(None, ge=10, le=100, description="페이지당 결과 수")


class SearchResult(BaseModel):
    """개별 검색 결과 스키마."""

    rank: int = Field(..., description="검색 순위")
    title: str = Field(..., description="결과 제목")
    url: str = Field(..., description="결과 URL")
    display_url: Optional[str] = Field(None, description="표시 URL")
    snippet: Optional[str] = Field(None, description="결과 설명/요약")
    publish_date: Optional[str] = Field(None, description="게시일")


class SearchResponse(BaseModel):
    """검색 응답 스키마."""

    search_id: str = Field(..., description="검색 세션 ID")
    query: str = Field(..., description="검색 키워드")
    status: str = Field(..., description="검색 상태")
    total_results: int = Field(..., description="총 결과 수")
    results: List[SearchResult] = Field(default_factory=list, description="검색 결과 목록")
    created_at: datetime = Field(..., description="생성 시간")

    class Config:
        from_attributes = True


class SearchQueueResponse(BaseModel):
    """검색 큐 응답 스키마 (비동기 검색 요청 시 반환)."""

    search_id: str = Field(..., description="검색 세션 ID")
    status: str = Field(..., description="검색 상태 (pending)")
    message: str = Field(default="검색 요청이 큐에 추가되었습니다.", description="안내 메시지")

    class Config:
        from_attributes = True


class SearchStatusResponse(BaseModel):
    """검색 상태 조회 응답 스키마."""

    search_id: str = Field(..., description="검색 세션 ID")
    query: str = Field(..., description="검색 키워드")
    status: str = Field(..., description="검색 상태 (pending, processing, completed, failed)")
    total_results: int = Field(default=0, description="총 결과 수")
    error_message: Optional[str] = Field(None, description="오류 메시지")
    created_at: datetime = Field(..., description="생성 시간")
    started_at: Optional[datetime] = Field(None, description="처리 시작 시간")
    completed_at: Optional[datetime] = Field(None, description="완료 시간")
    results: List[SearchResult] = Field(default_factory=list, description="검색 결과 목록 (완료 시)")

    class Config:
        from_attributes = True


class SearchHistoryItem(BaseModel):
    """검색 히스토리 항목 스키마."""

    search_id: str
    query: str
    date_filter: Optional[str]
    status: str
    total_results: int
    created_at: datetime

    class Config:
        from_attributes = True


# === 저장된 검색 스키마 ===


class SavedSearchCreate(BaseModel):
    """저장된 검색 생성 스키마."""

    name: str = Field(..., min_length=1, max_length=255, description="저장 이름")
    query: str = Field(..., min_length=1, max_length=500, description="검색 키워드")
    date_filter: Optional[str] = Field(
        None,
        pattern="^(1h|24h|1w|1m|1y)$",
        description="날짜 필터",
    )
    max_pages: int = Field(1, ge=1, le=10, description="페이지 수")
    service_account_id: Optional[int] = Field(None, description="브라우저 프로필 ID")
    is_favorite: bool = Field(False, description="즐겨찾기 여부")
    search_params: Optional[Dict[str, Any]] = Field(None, description="추가 검색 파라미터")


class SavedSearchUpdate(BaseModel):
    """저장된 검색 수정 스키마."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    query: Optional[str] = Field(None, min_length=1, max_length=500)
    date_filter: Optional[str] = Field(None, pattern="^(1h|24h|1w|1m|1y)?$")
    max_pages: Optional[int] = Field(None, ge=1, le=10)
    service_account_id: Optional[int] = None
    is_favorite: Optional[bool] = None
    search_params: Optional[Dict[str, Any]] = None


class SavedSearchResponse(BaseModel):
    """저장된 검색 응답 스키마."""

    id: int
    name: str
    query: str
    date_filter: Optional[str]
    max_pages: int
    service_account_id: Optional[int]
    is_favorite: bool
    search_params: Optional[Dict[str, Any]] = None
    last_search_id: Optional[str]
    last_run_at: Optional[datetime]
    last_result_count: Optional[int]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
