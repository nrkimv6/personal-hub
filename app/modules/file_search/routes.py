"""
파일 검색 API 라우트

5개 엔드포인트:
  POST /api/v1/file-search/search   — 통합 검색
  GET  /api/v1/file-search/presets  — 프리셋 목록
  POST /api/v1/file-search/open     — 파일 열기
  GET  /api/v1/file-search/status   — 도구 상태 확인
  GET  /api/v1/file-search/browse   — 서버 디렉토리 탐색
"""
from __future__ import annotations

import logging
from typing import List

from fastapi import APIRouter, HTTPException, Query

from app.modules.file_search.schemas import (
    BrowseResponse,
    OpenFileRequest,
    PresetResponse,
    SearchRequest,
    SearchResponse,
    StatusResponse,
)
from app.modules.file_search.services.presets import PRESETS
from app.modules.file_search.services.search_service import SearchService

logger = logging.getLogger("file_search.routes")

router = APIRouter(prefix="/api/v1/file-search", tags=["file-search"])

_service = SearchService()


@router.post("/search", response_model=SearchResponse)
async def search(request: SearchRequest):
    """파일명 / 내용 / 둘 다 통합 검색."""
    try:
        return await _service.search(request)
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.exception(f"파일 검색 오류: {exc}")
        raise HTTPException(status_code=500, detail="검색 중 오류가 발생했습니다.")


@router.get("/presets", response_model=List[PresetResponse])
async def get_presets():
    """사용 가능한 검색 프리셋 목록."""
    return [
        PresetResponse(
            id=p.id,
            name=p.name,
            icon=p.icon,
            paths=p.paths,
            extensions=p.extensions,
            excludes=p.excludes,
        )
        for p in PRESETS.values()
    ]


@router.post("/open")
async def open_file(request: OpenFileRequest):
    """파일을 VSCode 또는 기본 프로그램으로 열기."""
    import os
    if not os.path.exists(request.file_path):
        raise HTTPException(status_code=404, detail=f"파일을 찾을 수 없습니다: {request.file_path}")

    try:
        _service.open_file(request.file_path, request.line_number)
        return {"ok": True, "file_path": request.file_path}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/status", response_model=StatusResponse)
async def get_status():
    """Everything HTTP 서버 연결 상태 + ripgrep 설치 여부 확인."""
    return await _service.check_status()


@router.get("/browse", response_model=BrowseResponse)
async def browse_directory(
    path: str = Query("", description="탐색할 디렉토리 경로 (비어 있으면 드라이브 목록)"),
):
    """서버 측 디렉토리 목록 조회 (폴더 브라우저 모달용)."""
    return _service.browse_directory(path)
