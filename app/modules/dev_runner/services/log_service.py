"""로그 스트리밍 서비스 - Redis Pub/Sub 기반 실시간 로그"""

import asyncio
import time
from collections import deque
from pathlib import Path
from typing import Optional, AsyncGenerator
import glob

import redis
import redis.asyncio as aioredis

from app.modules.dev_runner.config import config
from app.modules.dev_runner.schemas import LogResponse
from app.modules.dev_runner.services.state import get_state
# Redis 설정
REDIS_HOST = "localhost"
REDIS_PORT = 6379
RUNNER_KEY_PREFIX = "plan-runner:runners"
ACTIVE_RUNNERS_KEY = "plan-runner:active_runners"
LOG_CHANNEL_PREFIX = "plan-runner:logs"

HEARTBEAT_INTERVAL = 30  # 초


class LogService:
    """로그 스트리밍 서비스 - Redis Pub/Sub 기반"""

    def __init__(self):
        """Redis 클라이언트 초기화"""
        # 동기 클라이언트 (tail_log_file, _find_current_log 용)
        self.redis_client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            decode_responses=True,
            socket_connect_timeout=5,
        )
        # 비동기 클라이언트 (stream_log_file 용 — 이벤트 루프 블로킹 방지)
        self.async_redis = aioredis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            decode_responses=True,
            socket_connect_timeout=5,
        )

    def _find_current_log(self, runner_id: str) -> Optional[Path]:
        """특정 runner의 stream 로그 파일 (Redis에서 조회)"""
        try:
            # stream 로그 경로 우선 (executor가 직접 기록한 파일)
            log_path = self.redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:stream_log_path")
            if log_path and Path(log_path).exists():
                return Path(log_path)
            # fallback: 기존 log_file_path
            log_path = self.redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:log_file_path")
            if log_path and Path(log_path).exists():
                return Path(log_path)
        except redis.ConnectionError:
            pass
        return None

    def tail_log_file(self, runner_id: str, n_lines: int = 100) -> LogResponse:
        """로그 파일 끝에서 N줄 읽기 (초기 로드용)."""
        log_file = self._find_current_log(runner_id)

        if log_file and log_file.exists():
            try:
                with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                    lines = deque(f, maxlen=n_lines)
                    if lines:
                        return LogResponse(
                            lines=[line.rstrip('\n') for line in lines],
                            total_lines=len(lines)
                        )
            except Exception as e:
                return LogResponse(
                    lines=[f"Error reading log: {str(e)}"],
                    total_lines=1
                )

        return LogResponse(lines=[], total_lines=0)

    async def stream_log_file(self, runner_id: str) -> AsyncGenerator[str, None]:
        """Redis Pub/Sub 기반 실시간 로그 스트리밍 (SSE 형식)"""
        log_channel = f"{LOG_CHANNEL_PREFIX}:{runner_id}"

        # 초기 연결 이벤트 — EventSource가 MIME type 검증을 통과하도록 보장
        yield "event: connected\ndata: ok\n\n"

        pubsub = None
        last_heartbeat = time.monotonic()
        consecutive_errors = 0
        MAX_CONSECUTIVE_ERRORS = 5

        while True:
            try:
                if pubsub is None:
                    pubsub = self.async_redis.pubsub()
                    await pubsub.subscribe(log_channel)

                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=0.5
                )
                if message and message["type"] == "message":
                    yield f"data: {message['data']}\n\n"
                    last_heartbeat = time.monotonic()
                    consecutive_errors = 0
                else:
                    now = time.monotonic()
                    if now - last_heartbeat >= HEARTBEAT_INTERVAL:
                        yield ": heartbeat\n\n"
                        last_heartbeat = now
                    await asyncio.sleep(0.3)

            except (redis.ConnectionError, aioredis.ConnectionError, ConnectionError, OSError):
                if pubsub:
                    try:
                        await pubsub.unsubscribe(log_channel)
                        await pubsub.aclose()
                    except AttributeError:
                        try:
                            await pubsub.close()
                        except Exception:
                            pass
                    except Exception:
                        pass
                    pubsub = None
                yield "event: redis_disconnected\ndata: Redis not available\n\n"
                last_heartbeat = time.monotonic()
                await asyncio.sleep(5)

            except Exception as e:
                consecutive_errors += 1
                if pubsub:
                    try:
                        await pubsub.unsubscribe(log_channel)
                        await pubsub.aclose()
                    except AttributeError:
                        try:
                            await pubsub.close()
                        except Exception:
                            pass
                    except Exception:
                        pass
                    pubsub = None
                last_heartbeat = time.monotonic()

                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    yield "event: stream_error\ndata: Too many consecutive errors, stream stopped\n\n"
                    return

                yield f"data: [Stream error #{consecutive_errors}: {str(e)}]\n\n"
                await asyncio.sleep(5)


    def run_diagnostics(self) -> dict:
        """파이프라인 진단 (1회성) — 4단계 순차 점검"""
        steps = []

        # 1. Redis 연결
        try:
            self.redis_client.ping()
            steps.append({"step": 1, "name": "Redis 연결", "ok": True, "detail": "연결됨"})
        except Exception:
            steps.append({"step": 1, "name": "Redis 연결", "ok": False, "detail": "연결 실패"})
            return {"steps": steps}

        # 2. Listener heartbeat
        hb = self.redis_client.get("plan-runner:listener:heartbeat")
        steps.append({
            "step": 2, "name": "Listener heartbeat", "ok": hb is not None,
            "detail": "활성" if hb else "heartbeat 키 없음 (리스너 꺼짐)"
        })

        # 3. 로그 파일 — 첫 번째 active runner 기준
        log_path = None
        runner_ids = self.redis_client.smembers(ACTIVE_RUNNERS_KEY)
        if runner_ids:
            first_id = next(iter(runner_ids))
            log_path = self.redis_client.get(f"{RUNNER_KEY_PREFIX}:{first_id}:stream_log_path")
            if not log_path:
                log_path = self.redis_client.get(f"{RUNNER_KEY_PREFIX}:{first_id}:log_file_path")

        if log_path and Path(log_path).exists():
            size = Path(log_path).stat().st_size
            steps.append({
                "step": 3, "name": "로그 파일", "ok": True,
                "detail": f"{Path(log_path).name} ({size:,}B)"
            })
        elif log_path:
            steps.append({
                "step": 3, "name": "로그 파일", "ok": False,
                "detail": f"경로 있으나 파일 없음: {log_path}"
            })
        else:
            steps.append({
                "step": 3, "name": "로그 파일", "ok": False,
                "detail": "stream_log_path / log_file_path 키 없음"
            })

        # 4. CLI 프로세스 — active runners 수 기준
        if runner_ids:
            steps.append({"step": 4, "name": "CLI 프로세스", "ok": True, "detail": f"{len(runner_ids)} runner(s) active"})
        else:
            steps.append({
                "step": 4, "name": "CLI 프로세스", "ok": False,
                "detail": "미실행"
            })

        return {"steps": steps}


# 싱글톤 인스턴스
log_service = LogService()

__all__ = ['log_service', 'LogService']
