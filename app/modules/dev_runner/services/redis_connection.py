"""Redis 연결 관리 및 공통 인프라 — ExecutorService/RunnerState 공유"""

import os

import redis
import redis.asyncio as aioredis
from fastapi import HTTPException

from app.config import logger

# RECENT runner 보존 TTL 계약
_ENV_RECENT_RUNNERS_TTL = "DEV_RUNNER_RECENT_TTL_SECONDS"
_DEFAULT_RECENT_RUNNERS_TTL = 86400  # 24시간


def _resolve_recent_runners_ttl() -> int:
    """RECENT_RUNNERS_TTL 환경변수를 안전하게 파싱한다."""
    raw = os.environ.get(_ENV_RECENT_RUNNERS_TTL, str(_DEFAULT_RECENT_RUNNERS_TTL))
    try:
        ttl = int(str(raw).strip())
        if ttl <= 0:
            raise ValueError("TTL must be > 0")
        return ttl
    except (TypeError, ValueError):
        logger.warning(
            "[executor-service] %s=%r invalid → fallback %s",
            _ENV_RECENT_RUNNERS_TTL,
            raw,
            _DEFAULT_RECENT_RUNNERS_TTL,
        )
        return _DEFAULT_RECENT_RUNNERS_TTL


# Redis 설정
REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_DB = int(os.environ.get("PLAN_RUNNER_REDIS_DB", "0"))
COMMANDS_KEY = "plan-runner:commands"
RESULTS_KEY = "plan-runner:command_results"
RUNNER_KEY_PREFIX = "plan-runner:runners"
ACTIVE_RUNNERS_KEY = "plan-runner:active_runners"
RECENT_RUNNERS_KEY = "plan-runner:recent_runners"  # sorted set: score=종료 timestamp
RECENT_RUNNERS_TTL = _resolve_recent_runners_ttl()  # 기본 24시간
COMMAND_TIMEOUT = 30  # 명령 결과 대기 타임아웃 (초) — worktree 생성 시간 고려
# per-runner 키 suffix 전체 목록 (listener와 공유되는 단일 진실 원천)
# scripts/dev-runner-command-listener.py도 동일 상수를 별도 정의하여 참조
RUNNER_KEY_SUFFIXES = (
    "status", "pid", "plan_file", "start_time", "log_file_path", "stream_log_path",
    "engine", "fix_engine", "worktree_path", "branch", "merge_status", "merge_requested",
    "current_cycle", "quota_stopped", "error", "restart_after_merge", "test_source", "trigger",
    "exit_reason", "stop_stage",
)


class RedisConnection:
    """Redis 연결 풀 관리 + runner 키 접근 헬퍼."""

    def __init__(self):
        self.reconnect()

    def reconnect(self):
        """환경변수를 반영하여 Redis 클라이언트를 재연결합니다."""
        # 기존 클라이언트 정리 (연결 누수 방지)
        if hasattr(self, 'redis_client') and self.redis_client:
            try:
                self.redis_client.close()
            except Exception:
                pass
        if hasattr(self, 'async_redis') and self.async_redis:
            try:
                import asyncio
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(self.async_redis.aclose())
                else:
                    loop.run_until_complete(self.async_redis.aclose())
            except Exception:
                pass

        # 상수 재갱신 (테스트에서 os.environ 변경 시 반영을 위함)
        global REDIS_DB, RECENT_RUNNERS_TTL
        REDIS_DB = int(os.environ.get("PLAN_RUNNER_REDIS_DB", "0"))
        RECENT_RUNNERS_TTL = _resolve_recent_runners_ttl()

        self._sync_pool = redis.ConnectionPool(
            host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB,
            decode_responses=True, socket_connect_timeout=5, socket_timeout=10,
            max_connections=20,
        )
        self.redis_client = redis.Redis(connection_pool=self._sync_pool)
        # 비동기 클라이언트 (brpop 등 블로킹 호출용)
        self._async_pool = aioredis.ConnectionPool(
            host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB,
            decode_responses=True, socket_connect_timeout=5,
            socket_timeout=COMMAND_TIMEOUT + 5, max_connections=20,
        )
        self.async_redis = aioredis.Redis(connection_pool=self._async_pool)
        logger.info(f"[executor-service] Redis 재연결 완료 (db={REDIS_DB})")

    async def check_redis_and_listener(self):
        """Redis 연결 + command listener 존재 여부 사전 확인."""
        try:
            await self.async_redis.ping()
        except (redis.ConnectionError, ConnectionRefusedError, OSError):
            raise HTTPException(
                status_code=503,
                detail="Redis에 연결할 수 없습니다. Redis 서버가 실행 중인지 확인하세요."
            )

        heartbeat = await self.async_redis.get("plan-runner:listener:heartbeat")
        if heartbeat is None:
            raise HTTPException(
                status_code=503,
                detail="dev-runner command listener가 실행 중이지 않습니다. 워커를 시작하세요."
            )

    def runner_key(self, rid: str, suffix: str) -> str:
        """Runner 단일 필드 Redis 키 조립."""
        return f"{RUNNER_KEY_PREFIX}:{rid}:{suffix}"

    async def get_runner_fields(self, rid: str, *fields: str) -> dict:
        """Runner 필드 여러 개를 개별 GET으로 조회, {field: value_or_None} dict 반환."""
        result = {}
        for f in fields:
            result[f] = await self.async_redis.get(self.runner_key(rid, f))
        return result
