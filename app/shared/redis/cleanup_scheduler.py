"""Redis 좀비 연결 주기적 정리 스케줄러.

API 서버 lifespan에서 백그라운드 태스크로 실행된다.
- startup 즉시: idle > 10초인 좀비 일괄 정리 (이전 프로세스 잔여물)
- 이후 5분 주기: idle > 300초인 좀비 정리
"""
import asyncio
import logging

from app.shared.redis.client import RedisClient
from app.shared.redis.cleanup import kill_zombie_connections

logger = logging.getLogger(__name__)


class RedisCleanupScheduler:
    """Redis 좀비 연결 주기적 정리 스케줄러."""

    def __init__(
        self,
        interval: int = 300,
        startup_idle_threshold: int = 10,
        normal_idle_threshold: int = 300,
    ) -> None:
        self.interval = interval
        self.startup_idle_threshold = startup_idle_threshold
        self.normal_idle_threshold = normal_idle_threshold

    async def _run_once(self, idle_threshold: int) -> None:
        """단일 정리 실행. Redis 미연결 시 skip."""
        client = await RedisClient.get_client()
        if not client:
            logger.debug("Redis 미연결 — 좀비 정리 스킵")
            return

        result = await kill_zombie_connections(client, idle_threshold=idle_threshold)
        if result.get("found", 0) > 0:
            logger.warning(
                f"Redis 좀비 연결 정리: found={result['found']}, "
                f"killed={result['killed']}, errors={result['errors']}"
            )
        else:
            logger.debug("Redis 좀비 연결 없음")

    async def run_cleanup_loop(self) -> None:
        """백그라운드 정리 루프.

        시작 시 즉시 정리 후, interval 간격으로 반복 정리.
        SystemCacheCollector.run_collector_loop() 패턴 동일.
        """
        logger.info(f"Redis 좀비 정리 스케줄러 시작 (간격: {self.interval}초)")

        # startup 즉시 실행 — 이전 프로세스 잔여 좀비 정리 (완화된 threshold)
        try:
            await asyncio.wait_for(
                self._run_once(self.startup_idle_threshold), timeout=30
            )
        except asyncio.TimeoutError:
            logger.warning("Redis 좀비 초기 정리 타임아웃 (30초) — 스킵")
        except Exception as e:
            logger.error(f"Redis 좀비 초기 정리 실패: {e}")

        while True:
            try:
                await asyncio.sleep(self.interval)
                await asyncio.wait_for(
                    self._run_once(self.normal_idle_threshold), timeout=30
                )
            except asyncio.CancelledError:
                logger.info("Redis 좀비 정리 스케줄러 종료")
                break
            except Exception as e:
                logger.error(f"Redis 좀비 정리 스케줄러 오류: {e}")
                await asyncio.sleep(5)  # 오류 시 짧게 대기 후 재시도
