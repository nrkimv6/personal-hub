"""
파일 검색 API 라우트

6개 엔드포인트:
  POST /api/v1/file-search/search              — 통합 검색 (비동기, 202 반환)
  GET  /api/v1/file-search/search/{search_id} — 검색 결과 폴링
  GET  /api/v1/file-search/presets            — 프리셋 목록
  POST /api/v1/file-search/open               — 파일 열기 (Redis 위임)
  GET  /api/v1/file-search/status             — 도구 상태 확인 (DB 캐시)
  GET  /api/v1/file-search/browse             — 서버 디렉토리 탐색

변경 사항 (2026-02-23):
  - POST /search: 동기 → 비동기 (202 + search_id)
  - GET /search/{search_id}: 폴링 엔드포인트 신규 추가
  - POST /open: subprocess 직접 호출 → Redis 큐 위임 (fire-and-forget)
  - GET /status: SearchService 직접 호출 → DB 캐시 조회
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.file_search_request import FileSearchRequest
from app.models.file_search_status import FileSearchStatus
from app.models.file_search_ignore_pattern import FileSearchIgnorePattern
from app.modules.file_search.schemas import (
    BrowseResponse,
    IgnorePatternCreate,
    IgnorePatternResponse,
    IgnorePatternUpdate,
    OpenFileRequest,
    PresetResponse,
    SearchAcceptedResponse,
    SearchPollResponse,
    SearchRequest,
    SearchResponse,
    StatusResponse,
)
from app.modules.file_search.services.presets import PRESETS
from app.modules.file_search.services.search_service import SearchService
from app.shared.redis import RedisClient, RedisQueue
from app.shared.redis.queue import FILE_SEARCH_QUEUE, FILE_SEARCH_OPEN_QUEUE

logger = logging.getLogger("file_search.routes")

router = APIRouter(prefix="/api/v1/file-search", tags=["file-search"])

_service = SearchService()

# 캐시된 Redis 큐 인스턴스 (None = 미연결)
_redis_queue: Optional[RedisQueue] = None
_open_queue: Optional[RedisQueue] = None
_redis_checked = False


async def _get_redis_queues():
    """Redis 큐 인스턴스 (lazy init, 연결 실패 시 None 반환)."""
    global _redis_queue, _open_queue, _redis_checked
    if not _redis_checked:
        redis_client = await RedisClient.get_client()
        if redis_client:
            _redis_queue = RedisQueue(redis_client, FILE_SEARCH_QUEUE)
            _open_queue = RedisQueue(redis_client, FILE_SEARCH_OPEN_QUEUE)
        _redis_checked = True
    return _redis_queue, _open_queue


# ============================================================
# POST /search — 비동기 (202 Accepted)
# ============================================================


@router.post("/search", status_code=202, response_model=SearchAcceptedResponse)
async def search(request: SearchRequest, db: Session = Depends(get_db)):
    """파일명 / 내용 / 둘 다 통합 검색 (비동기).

    1. DB에 FileSearchRequest INSERT (status=pending)
    2. Redis 큐에 LPUSH (search_id)
    3. 202 + search_id 반환 → 클라이언트가 GET /search/{search_id}로 폴링

    Redis 연결 실패 시에도 DB INSERT는 수행 (워커가 DB 폴링 fallback).
    """
    search_id = str(uuid.uuid4())

    # DB INSERT
    req = FileSearchRequest(
        search_id=search_id,
        status=FileSearchRequest.STATUS_PENDING,
        request_json=request.model_dump_json(),
    )
    db.add(req)
    db.commit()

    # Redis LPUSH
    try:
        redis_queue, _ = await _get_redis_queues()
        if redis_queue:
            await redis_queue.push({"search_id": search_id})
            req.status = FileSearchRequest.STATUS_QUEUED
            db.commit()
    except Exception as e:
        logger.warning(f"[file_search] Redis LPUSH 실패 (DB 폴링으로 처리됨): {e}")

    return SearchAcceptedResponse(search_id=search_id, status=req.status)


# ============================================================
# GET /search/{search_id} — 폴링
# ============================================================


@router.get("/search/{search_id}", response_model=SearchPollResponse)
async def get_search_result(search_id: str, db: Session = Depends(get_db)):
    """검색 결과 폴링.

    status: pending / queued / processing → 진행 중
    status: completed → result에 SearchResponse 반환
    status: failed → error_message 반환
    """
    req = db.query(FileSearchRequest).filter_by(search_id=search_id).first()
    if not req:
        raise HTTPException(status_code=404, detail=f"검색 요청을 찾을 수 없습니다: {search_id}")

    result = None
    if req.status == FileSearchRequest.STATUS_COMPLETED and req.result_json:
        try:
            result = SearchResponse(**json.loads(req.result_json))
        except Exception as e:
            logger.error(f"[file_search] result_json 파싱 오류: {e}")

    return SearchPollResponse(
        search_id=search_id,
        status=req.status,
        result=result,
        error_message=req.error_message,
    )


# ============================================================
# GET /presets
# ============================================================


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


# ============================================================
# POST /open — Redis 위임 (fire-and-forget)
# ============================================================


@router.post("/open")
async def open_file(request: OpenFileRequest):
    """파일을 VSCode로 열기 (Redis 워커에 위임).

    파일 존재 확인은 API에서 유지 (Session 0에서도 파일시스템 접근 가능).
    실제 subprocess(VSCode 실행)는 유저 세션 워커에서 처리.
    """
    if not os.path.exists(request.file_path):
        raise HTTPException(status_code=404, detail=f"파일을 찾을 수 없습니다: {request.file_path}")

    # Redis 위임
    try:
        _, open_queue = await _get_redis_queues()
        if open_queue:
            await open_queue.push({
                "file_path": request.file_path,
                "line_number": request.line_number,
            })
            return {"ok": True, "file_path": request.file_path, "via": "redis"}
    except Exception as e:
        logger.warning(f"[file_search] open Redis LPUSH 실패: {e}")

    # fallback: 직접 실행 (Redis 미연결 시)
    try:
        _service.open_file(request.file_path, request.line_number)
        return {"ok": True, "file_path": request.file_path, "via": "direct"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ============================================================
# GET /status — DB 캐시 조회
# ============================================================


@router.get("/status", response_model=StatusResponse)
async def get_status(db: Session = Depends(get_db)):
    """Everything/ripgrep 상태 확인 (DB 캐시).

    FileSearchWorker가 30초마다 체크하고 file_search_status 테이블에 캐싱.
    캐시 없거나 60초 이상 경과 시 unknown 반환.
    """
    CACHE_TTL_SECONDS = 60

    try:
        row = db.query(FileSearchStatus).filter_by(id=1).first()
        if row and row.checked_at:
            # 캐시 유효성 확인
            try:
                checked = datetime.strptime(row.checked_at, "%Y-%m-%d %H:%M:%S")
                age = (datetime.now() - checked).total_seconds()
                if age <= CACHE_TTL_SECONDS:
                    return StatusResponse(
                        everything_ok=bool(row.everything_ok),
                        everything_message="" if row.everything_ok else "Everything 연결 불가 (워커 상태 확인)",
                        ripgrep_ok=bool(row.ripgrep_ok),
                        ripgrep_path=row.ripgrep_path,
                    )
            except ValueError:
                pass
    except Exception as e:
        logger.warning(f"[file_search] 상태 캐시 조회 실패: {e}")

    # 캐시 없거나 만료
    return StatusResponse(
        everything_ok=False,
        everything_message="상태 정보 없음 (워커 미실행 또는 체크 대기 중)",
        ripgrep_ok=False,
        ripgrep_path=None,
    )


# ============================================================
# GET /browse
# ============================================================


@router.get("/browse", response_model=BrowseResponse)
async def browse_directory(
    path: str = Query("", description="탐색할 디렉토리 경로 (비어 있으면 드라이브 목록)"),
):
    """서버 측 디렉토리 목록 조회 (폴더 브라우저 모달용)."""
    return _service.browse_directory(path)


# ============================================================
# Ignore Patterns CRUD
# ============================================================


@router.get("/ignore-patterns", response_model=List[IgnorePatternResponse])
async def get_ignore_patterns(db: Session = Depends(get_db)):
    """무시 패턴 목록 조회 (sort_order ASC)."""
    rows = (
        db.query(FileSearchIgnorePattern)
        .order_by(FileSearchIgnorePattern.sort_order.asc())
        .all()
    )
    return [
        IgnorePatternResponse(
            id=r.id,
            label=r.label,
            pattern=r.pattern,
            enabled=bool(r.enabled),
            sort_order=r.sort_order,
        )
        for r in rows
    ]


@router.post("/ignore-patterns", response_model=IgnorePatternResponse, status_code=201)
async def add_ignore_pattern(body: IgnorePatternCreate, db: Session = Depends(get_db)):
    """무시 패턴 추가. sort_order 미지정 시 현재 max+1 자동 설정."""
    if body.sort_order is None:
        max_row = db.query(FileSearchIgnorePattern).order_by(
            FileSearchIgnorePattern.sort_order.desc()
        ).first()
        next_order = (max_row.sort_order + 1) if max_row else 1
    else:
        next_order = body.sort_order

    row = FileSearchIgnorePattern(
        label=body.label,
        pattern=body.pattern,
        enabled=1,
        sort_order=next_order,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return IgnorePatternResponse(
        id=row.id,
        label=row.label,
        pattern=row.pattern,
        enabled=bool(row.enabled),
        sort_order=row.sort_order,
    )


@router.patch("/ignore-patterns/{pattern_id}", response_model=IgnorePatternResponse)
async def update_ignore_pattern(
    pattern_id: int, body: IgnorePatternUpdate, db: Session = Depends(get_db)
):
    """무시 패턴 수정 (enabled 토글 또는 label 수정)."""
    row = db.query(FileSearchIgnorePattern).filter_by(id=pattern_id).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"패턴을 찾을 수 없습니다: {pattern_id}")

    if body.enabled is not None:
        row.enabled = 1 if body.enabled else 0
    if body.label is not None:
        row.label = body.label

    db.commit()
    db.refresh(row)
    return IgnorePatternResponse(
        id=row.id,
        label=row.label,
        pattern=row.pattern,
        enabled=bool(row.enabled),
        sort_order=row.sort_order,
    )


@router.delete("/ignore-patterns/{pattern_id}", status_code=204)
async def delete_ignore_pattern(pattern_id: int, db: Session = Depends(get_db)):
    """무시 패턴 삭제."""
    row = db.query(FileSearchIgnorePattern).filter_by(id=pattern_id).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"패턴을 찾을 수 없습니다: {pattern_id}")

    db.delete(row)
    db.commit()
