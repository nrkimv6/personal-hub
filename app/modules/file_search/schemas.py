"""
파일 검색 모듈 Pydantic 스키마
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


# ============================================================
# Request
# ============================================================


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, description="검색 키워드")
    mode: Literal["filename", "content", "both"] = "both"
    regex: bool = False
    case_sensitive: bool = False
    paths: List[str] = Field(default_factory=list, description="검색 경로 목록 (빈 배열 = 전체)")
    extensions: List[str] = Field(default_factory=list, description="확장자 필터 (py, ts, ...)")
    excludes: List[str] = Field(
        default_factory=list,
        description="제외 경로/패턴 (node_modules, __pycache__, ...)",
    )
    preset: Optional[str] = Field(None, description="프리셋 ID — 지정 시 paths/extensions/excludes 오버라이드")
    max_results: int = Field(100, ge=1, le=10000)
    context_lines: int = Field(2, ge=0, le=10, description="ripgrep 결과 전후 컨텍스트 라인 수")


class OpenFileRequest(BaseModel):
    file_path: str
    line_number: Optional[int] = None


# ============================================================
# Response building blocks
# ============================================================


class ContentMatch(BaseModel):
    line_number: int
    line_text: str
    context_before: List[str] = Field(default_factory=list)
    context_after: List[str] = Field(default_factory=list)
    submatches: List[dict] = Field(
        default_factory=list,
        description="매칭 범위 정보 [{start, end, match}] — 프론트 하이라이트용",
    )


class FileMatch(BaseModel):
    file_path: str
    file_name: str
    file_size: Optional[int] = None
    modified: Optional[str] = None
    matches: List[ContentMatch] = Field(default_factory=list)
    match_source: Literal["filename", "content", "both"] = "filename"


class SearchResponse(BaseModel):
    results: List[FileMatch]
    total_count: int
    search_time_ms: int
    mode: str
    truncated: bool = False


class StatusResponse(BaseModel):
    everything_ok: bool
    everything_message: str = ""
    ripgrep_ok: bool
    ripgrep_path: Optional[str] = None


class DirectoryItem(BaseModel):
    name: str
    path: str


class BrowseResponse(BaseModel):
    current: str
    parent: Optional[str] = None
    directories: List[DirectoryItem] = Field(default_factory=list)


# ============================================================
# Preset
# ============================================================


class PresetResponse(BaseModel):
    id: str
    name: str
    icon: str
    paths: List[str]
    extensions: List[str]
    excludes: List[str]


# ============================================================
# Async (Redis worker) 응답 스키마
# ============================================================


class SearchAcceptedResponse(BaseModel):
    """POST /search 202 응답 — Redis 워커로 비동기 처리 시작."""
    search_id: str
    status: str  # "queued"


class SearchPollResponse(BaseModel):
    """GET /search/{search_id} 폴링 응답."""
    search_id: str
    status: str  # pending / queued / processing / completed / failed
    result: Optional[SearchResponse] = None
    error_message: Optional[str] = None
