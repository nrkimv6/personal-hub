"""작업 목록 API"""

from fastapi import APIRouter
from typing import Optional

from app.modules.dev_runner.schemas import CurrentTrackingResponse

try:
    import redis as redis_lib
    _redis_client = redis_lib.Redis(
        host="localhost", port=6379,
        socket_connect_timeout=2,
        socket_timeout=2,
    )
except Exception:
    _redis_client = None

router = APIRouter()

REDIS_STATE_KEY = "plan-runner:state"


@router.get("/tasks/current-tracking", response_model=Optional[CurrentTrackingResponse])
async def get_current_tracking():
    """
    TaskTracker가 현재 추적 중인 체크박스 조회 (Redis 기반, TTL 60초).
    실행 중이 아니거나 정보가 없으면 null 반환.
    """
    if not _redis_client:
        return None

    try:
        text = _redis_client.get(f"{REDIS_STATE_KEY}:current_task_text")
        confidence = _redis_client.get(f"{REDIS_STATE_KEY}:current_task_confidence")

        if not text or not confidence:
            return None

        # str 디코딩
        if isinstance(text, bytes):
            text = text.decode("utf-8")
        if isinstance(confidence, bytes):
            confidence = confidence.decode("utf-8")

        line_num_raw = _redis_client.get(f"{REDIS_STATE_KEY}:current_task_line_num")
        plan_file_raw = _redis_client.get(f"{REDIS_STATE_KEY}:current_task_plan_file")

        line_num = None
        if line_num_raw:
            try:
                line_num = int(line_num_raw.decode("utf-8") if isinstance(line_num_raw, bytes) else line_num_raw)
            except (ValueError, AttributeError):
                pass

        plan_file = None
        if plan_file_raw:
            plan_file = plan_file_raw.decode("utf-8") if isinstance(plan_file_raw, bytes) else plan_file_raw

        return CurrentTrackingResponse(
            text=text,
            confidence=confidence,
            line_num=line_num,
            plan_file=plan_file,
            stale=False,  # TTL 기반 — 키가 살아있으면 stale 아님
        )
    except Exception:
        return None


__all__ = ['router']
