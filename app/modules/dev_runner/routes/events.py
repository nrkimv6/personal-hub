"""SSE 이벤트 스트림 라우트 — GET /events"""

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.modules.dev_runner.services.event_service import event_service

router = APIRouter()


@router.get("/events")
async def stream_events():
    """
    Redis keyspace notifications 기반 실시간 SSE 스트림.

    이벤트 타입:
      - connected    : 연결 확인 (최초 1회)
      - status       : runner 상태 변경
      - tracking     : 현재 추적 중인 태스크 변경
      - plan_changed : 추적 plan_file 변경
    """
    return StreamingResponse(
        event_service.stream_events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
