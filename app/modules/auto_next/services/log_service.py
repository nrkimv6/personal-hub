"""로그 스트리밍 서비스 - Redis 기반 로그 경로 조회"""

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


class LogService:
    """로그 파일 스트리밍 서비스 - Redis 기반"""

    def __init__(self):
        """Redis 클라이언트 초기화"""
        self.redis_client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            decode_responses=True,
            socket_connect_timeout=5,
        )

    def _find_current_log(self) -> Optional[Path]:
        """현재 실행 중인 auto-next 프로세스의 로그 파일 (Redis에서 조회)"""
        try:
            # Redis에서 로그 경로 조회
            log_path = self.redis_client.get(STATE_KEY + ":log_file_path")
            if log_path and Path(log_path).exists():
                return Path(log_path)
        except redis.ConnectionError:
            pass
        return None

    def tail_log_file(self, n_lines: int = 100) -> LogResponse:
        """로그 파일 끝에서 N줄 읽기"""
        log_file = self._find_current_log()

        if not log_file or not log_file.exists():
            return LogResponse(lines=[], total_lines=0)

        # 파일 끝에서 N줄 읽기 (deque 활용)
        try:
            with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                lines = deque(f, maxlen=n_lines)
                return LogResponse(
                    lines=list(lines),
                    total_lines=len(lines)
                )
        except Exception as e:
            return LogResponse(
                lines=[f"Error reading log: {str(e)}"],
                total_lines=1
            )

    async def stream_log_file(self) -> AsyncGenerator[str, None]:
        """로그 파일 실시간 스트리밍 (SSE 형식) - 현재 프로세스 로그만"""
        current_file: Optional[Path] = None
        f = None

        try:
            while True:
                # 매 루프마다 현재 프로세스의 로그 파일 확인
                new_file = self._find_current_log()

                if new_file != current_file:
                    # 로그 파일이 바뀜 (새 실행 시작 등)
                    if f:
                        f.close()
                        f = None
                    current_file = new_file

                    if current_file and current_file.exists():
                        f = open(current_file, "r", encoding="utf-8", errors="ignore")
                        # 처음부터 읽기 (새 실행이므로)
                    else:
                        yield "data: [Waiting for log...]\n\n"
                        await asyncio.sleep(1)
                        continue

                if f:
                    line = f.readline()
                    if line:
                        yield f"data: {line}\n\n"
                    else:
                        await asyncio.sleep(0.5)
                else:
                    await asyncio.sleep(1)
        except Exception as e:
            yield f"data: [Error: {str(e)}]\n\n"
        finally:
            if f:
                f.close()


# 싱글톤 인스턴스
log_service = LogService()

__all__ = ['log_service', 'LogService']
