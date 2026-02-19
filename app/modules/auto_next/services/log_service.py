"""로그 스트리밍 서비스 - Redis Pub/Sub 기반 실시간 로그"""

import asyncio
from collections import deque
from pathlib import Path
from typing import Optional, AsyncGenerator
import glob

import redis

from app.modules.auto_next.config import config
from app.modules.auto_next.schemas import LogResponse
from app.modules.auto_next.services.state import get_state

# Redis 설정
REDIS_HOST = "localhost"
REDIS_PORT = 6379
STATE_KEY = "auto-next:state"
LOG_CHANNEL = "auto-next:logs"


class LogService:
    """로그 스트리밍 서비스 - Redis Pub/Sub 기반"""

    def __init__(self):
        """Redis 클라이언트 초기화"""
        self.redis_client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            decode_responses=True,
            socket_connect_timeout=5,
        )

    def _find_current_log(self) -> Optional[Path]:
        """현재 실행 중인 auto-next의 stream 로그 파일 (Redis에서 조회)"""
        try:
            # stream 로그 경로 우선 (executor가 직접 기록한 파일)
            log_path = self.redis_client.get(STATE_KEY + ":stream_log_path")
            if log_path and Path(log_path).exists():
                return Path(log_path)
            # fallback: 기존 log_file_path
            log_path = self.redis_client.get(STATE_KEY + ":log_file_path")
            if log_path and Path(log_path).exists():
                return Path(log_path)
        except redis.ConnectionError:
            pass
        return None

    def tail_log_file(self, n_lines: int = 100) -> LogResponse:
        """로그 파일 끝에서 N줄 읽기 (초기 로드용)"""
        log_file = self._find_current_log()

        if not log_file or not log_file.exists():
            return LogResponse(lines=[], total_lines=0)

        try:
            with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                lines = deque(f, maxlen=n_lines)
                return LogResponse(
                    lines=[line.rstrip('\n') for line in lines],
                    total_lines=len(lines)
                )
        except Exception as e:
            return LogResponse(
                lines=[f"Error reading log: {str(e)}"],
                total_lines=1
            )

    async def stream_log_file(self) -> AsyncGenerator[str, None]:
        """Redis Pub/Sub 기반 실시간 로그 스트리밍 (SSE 형식)

        Redis 미연결 시에도 generator를 유지하여 SSE 연결이 끊기지 않도록 함.
        """
        # 초기 연결 이벤트 — EventSource가 MIME type 검증을 통과하도록 보장
        yield "event: connected\ndata: ok\n\n"

        pubsub = None
        while True:
            try:
                if pubsub is None:
                    pubsub = self.redis_client.pubsub()
                    pubsub.subscribe(LOG_CHANNEL)

                message = pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message and message["type"] == "message":
                    yield f"data: {message['data']}\n\n"
                else:
                    await asyncio.sleep(0.3)

            except redis.ConnectionError:
                # Redis 연결 실패 — generator 종료 대신 heartbeat 유지 + 재연결 대기
                if pubsub:
                    try:
                        pubsub.unsubscribe(LOG_CHANNEL)
                        pubsub.close()
                    except Exception:
                        pass
                    pubsub = None
                yield "event: redis_disconnected\ndata: Redis not available\n\n"
                await asyncio.sleep(5)
                # while 루프로 돌아가서 재연결 시도

            except Exception as e:
                yield f"data: [Error: {str(e)}]\n\n"
                if pubsub:
                    try:
                        pubsub.unsubscribe(LOG_CHANNEL)
                        pubsub.close()
                    except Exception:
                        pass
                    pubsub = None
                await asyncio.sleep(5)


# 싱글톤 인스턴스
log_service = LogService()

__all__ = ['log_service', 'LogService']
