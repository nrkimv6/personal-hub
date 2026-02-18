"""
시스템 상태 백그라운드 수집기

1분 간격으로 PowerShell 명령을 실행하여 시스템 상태를 수집하고 DB에 캐시합니다.
"""
import asyncio
import json
import time
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import text

from app.core.database import SessionLocal
from .system_service import SystemService

logger = logging.getLogger(__name__)


class SystemCacheCollector:
    """시스템 상태를 주기적으로 수집하여 DB에 캐시"""

    def __init__(self, interval_seconds: int = 60):
        self.interval = interval_seconds
        self.service = SystemService()
        self._is_collecting = False

    async def collect_and_cache(self) -> Optional[dict]:
        """시스템 상태를 수집하고 DB에 저장

        Returns:
            수집된 상태 dict (collected_at, collection_duration_ms 포함)
            수집 중이거나 실패 시 None
        """
        if self._is_collecting:
            logger.warning("이미 수집 중입니다")
            return None

        self._is_collecting = True
        start_time = time.time()

        try:
            # 기존 서비스 메서드로 상태 수집
            status = await self.service.get_all_services_status()

            duration_ms = int((time.time() - start_time) * 1000)
            collected_at = datetime.now()

            # DB에 저장
            db = SessionLocal()
            try:
                db.execute(text("""
                    UPDATE system_status_cache
                    SET data = :data,
                        collected_at = :collected_at,
                        collection_duration_ms = :duration_ms,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = 1
                """), {
                    "data": json.dumps(status, ensure_ascii=False),
                    "collected_at": collected_at.isoformat(),
                    "duration_ms": duration_ms
                })
                db.commit()

                logger.info(f"시스템 상태 수집 완료: {duration_ms}ms")
                return {
                    **status,
                    "collected_at": collected_at.isoformat(),
                    "collection_duration_ms": duration_ms
                }
            finally:
                db.close()

        except Exception as e:
            logger.error(f"시스템 상태 수집 실패: {e}")
            return None
        finally:
            self._is_collecting = False

    def get_cached_status(self) -> dict:
        """캐시된 상태 조회 (동기)

        Returns:
            캐시된 상태 dict (collected_at, collection_duration_ms 포함)
        """
        db = SessionLocal()
        try:
            result = db.execute(text("""
                SELECT data, collected_at, collection_duration_ms
                FROM system_status_cache WHERE id = 1
            """)).fetchone()

            if result:
                data = json.loads(result[0]) if result[0] else {"projects": {}}
                return {
                    **data,
                    "collected_at": result[1],
                    "collection_duration_ms": result[2]
                }
            return {"projects": {}, "collected_at": None, "collection_duration_ms": None}
        finally:
            db.close()

    async def run_collector_loop(self):
        """백그라운드 수집 루프

        시작 시 즉시 수집 후, interval 간격으로 반복 수집
        """
        logger.info(f"시스템 상태 수집기 시작 (간격: {self.interval}초)")

        # 시작 시 즉시 수집
        await self.collect_and_cache()

        while True:
            try:
                await asyncio.sleep(self.interval)
                await self.collect_and_cache()
            except asyncio.CancelledError:
                logger.info("시스템 상태 수집기 종료")
                break
            except Exception as e:
                logger.error(f"시스템 상태 수집기 오류: {e}")
                await asyncio.sleep(5)  # 오류 시 짧게 대기 후 재시도
