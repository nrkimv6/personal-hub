"""로그 스트리밍 API"""

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from app.modules.dev_runner.schemas import LogResponse
from app.modules.dev_runner.services.log_service import log_service

router = APIRouter()


@router.get("/logs/recent", response_model=LogResponse)
async def get_recent_logs(
    runner_id: str = Query(..., description="runner ID"),
    lines: int = Query(100, ge=1, le=1000, description="조회할 줄 수"),
):
    """최근 로그 조회 (끝에서 N줄)"""
    return log_service.tail_log_file(runner_id=runner_id, n_lines=lines)


@router.get("/logs/stream")
async def stream_logs(
    runner_id: str = Query(..., description="runner ID"),
):
    """로그 실시간 스트리밍 (SSE)"""
    return StreamingResponse(
        log_service.stream_log_file(runner_id=runner_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.get("/logs/diagnostics")
async def get_diagnostics():
    """파이프라인 진단 (1회성) — LogViewer 시작 시 호출"""
    return log_service.run_diagnostics()


__all__ = ['router']
