"""Chat log and SSE streaming routes for LLM requests."""

import asyncio
import logging
from collections import deque
from typing import AsyncGenerator

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.dev_runner.services.sse_helpers import safe_close_pubsub

logger = logging.getLogger("claude_worker.api")
router = APIRouter(tags=["llm"])

# Redis singleton for SSE streaming. Tests may monkeypatch this module attribute.
_redis_async = aioredis.Redis(host="localhost", port=6379, decode_responses=True)

async def _chat_sse_generator(request_id: int) -> AsyncGenerator[str, None]:
    """Redis Pub/Sub 구독 -> SSE yield. __COMPLETED__ 수신 시 종료."""
    channel = f"llm-chat:stream:{request_id}"
    pubsub = _redis_async.pubsub()
    try:
        await pubsub.subscribe(channel)

        heartbeat_interval = 30  # seconds
        last_heartbeat = asyncio.get_event_loop().time()

        async for message in pubsub.listen():
            now = asyncio.get_event_loop().time()

            # heartbeat
            if now - last_heartbeat >= heartbeat_interval:
                yield ": heartbeat\n\n"
                last_heartbeat = now

            if message["type"] != "message":
                continue

            data = message["data"]
            if data == "__COMPLETED__":
                yield "event: completed\ndata: done\n\n"
                break
            else:
                escaped = data.replace("\n", "\\n")
                yield f"data: {escaped}\n\n"
    except Exception as e:
        logger.error(f"SSE stream error request_id={request_id}: {e}")
        yield f"data: [ERROR] {e}\n\n"
    finally:
        await safe_close_pubsub(pubsub)


@router.get("/chat/{request_id}/stream")
async def stream_chat_logs(request_id: int, db: Session = Depends(get_db)):
    """chat 모드 요청의 실시간 SSE 스트림.

    Redis Pub/Sub llm-chat:stream:{request_id} 구독 후 SSE로 전달.
    __COMPLETED__ 수신 시 'event: completed' 발행 후 종료.
    """
    # 요청 존재 확인
    from app.modules.claude_worker.models.llm_request import LLMRequest
    req = db.query(LLMRequest).filter(LLMRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="LLMRequest not found")

    return StreamingResponse(
        _chat_sse_generator(request_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.get("/chat/{request_id}/logs")
def get_chat_logs(
    request_id: int,
    lines: int = Query(200, ge=1, le=2000),
    db: Session = Depends(get_db),
):
    """chat 요청의 로그 파일 내용 반환 (fallback).

    stream_log_path가 있으면 파일 마지막 N줄 반환.
    없으면 raw_response 반환 (완료된 경우).
    """
    from app.modules.claude_worker.models.llm_request import LLMRequest
    req = db.query(LLMRequest).filter(LLMRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="LLMRequest not found")

    if req.stream_log_path:
        import os
        if os.path.exists(req.stream_log_path):
            tail = deque(maxlen=lines)
            with open(req.stream_log_path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    tail.append(line.rstrip("\n"))
            return {"source": "log_file", "lines": list(tail), "status": req.status}

    # fallback: raw_response
    return {
        "source": "raw_response",
        "lines": (req.raw_response or "").splitlines()[-lines:],
        "status": req.status,
    }
