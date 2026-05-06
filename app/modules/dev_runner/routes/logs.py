"""로그 스트리밍 API"""

import asyncio

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from app.modules.dev_runner.schemas import LogResponse, RunHistoryResponse, FullLogResponse
from app.modules.dev_runner.services.log_service import log_service
from app.modules.dev_runner.services.diagnostics_service import diagnostics_service

router = APIRouter()


@router.get("/logs/recent", response_model=LogResponse)
async def get_recent_logs(
    runner_id: str = Query(..., description="runner ID"),
    lines: int = Query(100, ge=1, le=1000, description="조회할 줄 수"),
):
    """최근 로그 조회 (끝에서 N줄)"""
    return await asyncio.to_thread(log_service.tail_log_file, runner_id=runner_id, n_lines=lines)


@router.get("/logs/stream")
async def stream_logs(
    runner_id: str = Query(..., description="runner ID"),
    since_line: int = Query(0, ge=0, description="마지막 수신 줄 번호"),
):
    """로그 실시간 스트리밍 (SSE)"""
    return StreamingResponse(
        log_service.stream_log_file(runner_id=runner_id, since_line=since_line),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.get("/logs/diagnostics")
async def get_diagnostics():
    """파이프라인 진단 (1회성) — LogViewer 시작 시 호출"""
    return diagnostics_service.run_diagnostics()


@router.get("/logs/history", response_model=RunHistoryResponse)
async def get_run_history(
    limit: int = Query(20, ge=1, le=100, description="최대 반환 수"),
    offset: int = Query(0, ge=0, description="페이지 오프셋"),
    visible_only: bool = Query(False, description="user runner만 필터링"),
):
    """실행 이력 조회 (Redis active_runners + 로그 파일 스캔)"""
    return await asyncio.to_thread(
        log_service.get_run_history,
        limit=limit,
        offset=offset,
        visible_only=visible_only,
    )


@router.get("/logs/full", response_model=FullLogResponse)
async def get_full_log(
    runner_id: str = Query(..., description="runner ID"),
    offset: int = Query(0, ge=0, description="시작 라인 오프셋"),
    limit: int = Query(500, ge=1, le=5000, description="최대 라인 수"),
):
    """종료된 Runner 전체 로그 조회 (offset/limit 청크)"""
    return await asyncio.to_thread(
        log_service.get_full_log,
        runner_id=runner_id,
        offset=offset,
        limit=limit,
    )


@router.get("/merge-log/stream")
async def stream_merge_log(runner_id: str = Query(..., description="runner ID")):
    """머지 진행 로그 SSE 스트리밍"""
    return StreamingResponse(
        log_service.stream_merge_log(runner_id=runner_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.get("/logs/system", response_model=LogResponse)
async def get_system_log(
    lines: int = Query(200, ge=1, le=2000, description="tail 줄 수"),
):
    """Listener 시스템 로그 조회 (가장 최신 plan-runner-*.log)"""
    return await asyncio.to_thread(log_service.get_system_log, lines=lines)


__all__ = ['router']
