"""Redis 클라이언트 싱글톤.

Redis 연결을 관리하고, 연결 실패 시 SQLite fallback을 지원합니다.
"""
import asyncio
import logging
from typing import Optional

import redis as redis_sync
import redis.asyncio as redis

from app.core.config import settings

logger = logging.getLogger(__name__)


class RedisClient:
    """Redis 연결 관리자.

    싱글톤 패턴으로 Redis 연결을 관리합니다.
    연결 실패 시 None을 반환하여 SQLite fallback을 지원합니다.

    Attributes:
        _instance: Redis 클라이언트 인스턴스
        _connected: 연결 상태
        _lock: 동시 접근 방지용 락
    """

    _instance: Optional[redis.Redis] = None
    _connected: bool = False
    _lock: Optional[asyncio.Lock] = None
    _reconnect_attempts: int = 0
    _max_reconnect_attempts: int = 3
    _async_pool: Optional[redis.ConnectionPool] = None
    _sync_pool: Optional[redis_sync.ConnectionPool] = None
    _sync_client: Optional[redis_sync.Redis] = None

    @classmethod
    async def _get_lock(cls) -> asyncio.Lock:
        """락 인스턴스 반환 (지연 초기화)."""
        if cls._lock is None:
            cls._lock = asyncio.Lock()
        return cls._lock

    @classmethod
    async def get_client(cls) -> Optional[redis.Redis]:
        """Redis 클라이언트 반환.

        연결이 없으면 새로 생성하고, 연결 실패 시 None을 반환합니다.
        이벤트 루프 간 호환성을 위해 항상 현재 루프에서 연결합니다.

        Returns:
            redis.Redis | None: Redis 클라이언트 또는 None
        """
        if not settings.REDIS_ENABLED:
            return None

        lock = await cls._get_lock()
        async with lock:
            # 이미 연결되어 있으면 ping으로 확인
            if cls._instance is not None and cls._connected:
                try:
                    await cls._instance.ping()
                    return cls._instance
                except Exception:
                    # 연결 끊김 - 재연결 시도
                    logger.warning("Redis 연결 끊김, 재연결 시도")
                    cls._connected = False
                    try:
                        await cls._instance.close()
                    except Exception:
                        pass
                    cls._instance = None

            # 새 연결 시도
            try:
                if cls._async_pool is None:
                    cls._async_pool = redis.ConnectionPool(
                        host=settings.REDIS_HOST,
                        port=settings.REDIS_PORT,
                        decode_responses=True,
                        socket_connect_timeout=settings.REDIS_CONNECTION_TIMEOUT,
                        socket_timeout=settings.REDIS_CONNECTION_TIMEOUT,
                        max_connections=50,
                    )
                cls._instance = redis.Redis(connection_pool=cls._async_pool)
                await cls._instance.ping()
                cls._connected = True
                cls._reconnect_attempts = 0
                logger.info(
                    f"Redis 연결 성공: {settings.REDIS_HOST}:{settings.REDIS_PORT}"
                )
                return cls._instance

            except Exception as e:
                cls._reconnect_attempts += 1
                logger.warning(
                    f"Redis 연결 실패 ({cls._reconnect_attempts}/{cls._max_reconnect_attempts}): {e}"
                )
                if cls._instance:
                    try:
                        await cls._instance.close()
                    except Exception:
                        pass
                cls._instance = None
                cls._connected = False
                return None

    @classmethod
    def get_sync_client(cls) -> Optional[redis_sync.Redis]:
        """동기 Redis 클라이언트 반환 (ConnectionPool 기반 싱글톤)."""
        if not settings.REDIS_ENABLED:
            return None
        if cls._sync_client is None:
            if cls._sync_pool is None:
                cls._sync_pool = redis_sync.ConnectionPool(
                    host=settings.REDIS_HOST,
                    port=settings.REDIS_PORT,
                    decode_responses=True,
                    socket_connect_timeout=settings.REDIS_CONNECTION_TIMEOUT,
                    socket_timeout=settings.REDIS_CONNECTION_TIMEOUT,
                    max_connections=20,
                )
            cls._sync_client = redis_sync.Redis(connection_pool=cls._sync_pool)
        return cls._sync_client

    @classmethod
    async def close(cls) -> None:
        """연결 종료."""
        if cls._instance:
            try:
                await cls._instance.close()
                logger.info("Redis 연결 종료")
            except Exception as e:
                logger.warning(f"Redis 연결 종료 중 오류: {e}")
            finally:
                cls._instance = None
                cls._connected = False

    @classmethod
    def is_connected(cls) -> bool:
        """연결 상태 확인.

        Returns:
            bool: 연결 상태
        """
        return cls._connected

    @classmethod
    async def health_check(cls) -> dict:
        """Redis 상태 확인.

        Returns:
            dict: 상태 정보 (connected, host, port, error)
        """
        result = {
            "enabled": settings.REDIS_ENABLED,
            "connected": False,
            "host": settings.REDIS_HOST,
            "port": settings.REDIS_PORT,
            "error": None,
        }

        if not settings.REDIS_ENABLED:
            result["error"] = "Redis disabled"
            return result

        try:
            client = await cls.get_client()
            if client:
                await client.ping()
                result["connected"] = True
                # 추가 정보
                info = await client.info("server")
                result["version"] = info.get("redis_version")
            else:
                result["error"] = "Connection failed"
        except Exception as e:
            result["error"] = str(e)

        return result


async def get_redis() -> Optional[redis.Redis]:
    """FastAPI 의존성용 Redis 클라이언트 반환.

    Returns:
        redis.Redis | None: Redis 클라이언트 또는 None
    """
    return await RedisClient.get_client()
