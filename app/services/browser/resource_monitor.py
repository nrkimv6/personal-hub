"""
리소스 모니터링 모듈

메모리 사용량 모니터링 및 리소스 정리를 담당합니다.
"""

import asyncio
import gc
import os
import psutil
import time
from typing import Dict, TYPE_CHECKING

from app.config import settings, logger

if TYPE_CHECKING:
    from .tab_pool_manager import TabPoolManager


class ResourceMonitor:
    """리소스 모니터"""

    def __init__(self, tab_pool_manager: "TabPoolManager"):
        """
        ResourceMonitor 초기화

        Args:
            tab_pool_manager: 탭 풀 관리자
        """
        self.tab_pool_manager = tab_pool_manager

        # 메모리 모니터링 관련 변수
        self.memory_stats: Dict[int, Dict] = {}
        self.last_memory_check: float = 0
        self.resource_cleanup_task = None

        # 리소스 정리 임계값 설정
        self.MEMORY_CHECK_INTERVAL = settings.MEMORY_CHECK_INTERVAL
        self.MEMORY_THRESHOLD_MB = settings.MEMORY_THRESHOLD_MB
        self.last_global_cleanup_time = time.time()
        self.GLOBAL_CLEANUP_INTERVAL = settings.GLOBAL_CLEANUP_INTERVAL

        # 종료 플래그
        self._running = False

    async def start_resource_monitoring_async(self):
        """리소스 모니터링 및 정리 태스크를 비동기적으로 시작합니다."""
        logger.info("start_resource_monitoring_async 호출됨")
        if self.resource_cleanup_task is None:
            logger.info("리소스 모니터링 태스크 생성 시작")
            self.resource_cleanup_task = asyncio.create_task(self.monitor_resources())
            logger.info("리소스 모니터링 태스크가 시작되었습니다")

    def start_resource_monitoring(self):
        """리소스 모니터링 및 정리 태스크를 시작합니다. (이벤트 루프가 실행 중일 때만 호출해야 함)"""
        if self.resource_cleanup_task is None:
            try:
                self.resource_cleanup_task = asyncio.create_task(self.monitor_resources())
                logger.info("리소스 모니터링 태스크가 시작되었습니다")
            except RuntimeError as e:
                logger.error(f"리소스 모니터링 태스크 시작 실패: {str(e)}")
                logger.warning("이벤트 루프가 없어 리소스 모니터링 태스크를 시작할 수 없습니다. 비동기 컨텍스트에서 initialize() 메소드를 호출하세요.")

    async def monitor_resources(self):
        """리소스 사용량을 모니터링하고 필요시 정리합니다."""
        logger.info("monitor_resources 태스크 시작")
        try:
            self._running = True
            while self._running:
                current_time = time.time()

                # 전역 탭 풀 메모리 사용량 확인 및 정리
                if not self._running:
                    break
                try:
                    await self.check_memory()
                except Exception as e:
                    logger.error(f"메모리 체크 오류: {str(e)}")

                # 안전장치: 중간에 태스크가 취소되었는지 확인
                if not self._running:
                    break

                # 주기적인 전체 정리 수행
                if current_time - self.last_global_cleanup_time > self.GLOBAL_CLEANUP_INTERVAL:
                    try:
                        await self.perform_global_cleanup()
                        self.last_global_cleanup_time = current_time
                    except Exception as e:
                        logger.error(f"전체 정리 오류: {str(e)}")

                # 다음 확인까지 대기
                for _ in range(6):
                    if not self._running:
                        break
                    await asyncio.sleep(10)
        except asyncio.CancelledError:
            logger.info("리소스 모니터링 태스크가 취소되었습니다")
            self._running = False
        except Exception as e:
            logger.error(f"리소스 모니터링 오류 발생: {str(e)}")
            self._running = False
            await asyncio.sleep(5)
            if hasattr(self, '_running') and self._running:
                logger.info("리소스 모니터링 태스크 재시작")
                self.resource_cleanup_task = asyncio.create_task(self.monitor_resources())
        finally:
            logger.info("monitor_resources 태스크 종료")
            self._running = False

    async def check_memory(self):
        """전역 메모리 사용량을 확인하고 필요시 정리합니다."""
        current_time = time.time()

        # 마지막 확인 이후 충분한 시간이 지났는지 확인
        if current_time - self.last_memory_check < self.MEMORY_CHECK_INTERVAL:
            return

        # 현재 프로세스의 메모리 사용량 확인
        process = psutil.Process(os.getpid())
        memory_info = process.memory_info()
        memory_mb = memory_info.rss / (1024 * 1024)

        # 전역 메모리 통계 업데이트
        if "global" not in self.memory_stats:
            self.memory_stats["global"] = {"initial": memory_mb, "current": memory_mb, "peak": memory_mb}
        else:
            self.memory_stats["global"]["current"] = memory_mb
            if memory_mb > self.memory_stats["global"]["peak"]:
                self.memory_stats["global"]["peak"] = memory_mb

        self.last_memory_check = current_time

        # 로그 출력
        tab_pool = self.tab_pool_manager.tab_pool
        logger.info(f"전역 메모리 사용량: {memory_mb:.2f}MB (탭 수: {len(tab_pool)}/{self.tab_pool_manager.TOTAL_MAX_TABS})")

        # 메모리 사용량이 임계값을 초과하면 정리 작업 수행
        if memory_mb > self.MEMORY_THRESHOLD_MB and len(tab_pool) > 1:
            logger.info(f"메모리 사용량이 임계값({self.MEMORY_THRESHOLD_MB}MB)을 초과하여 정리를 시작합니다.")
            await self.cleanup_resources()

    async def cleanup_resources(self):
        """전역 탭 풀 리소스를 정리합니다."""
        try:
            tab_pool = self.tab_pool_manager.tab_pool
            tab_count_before = len(tab_pool)
            await self.tab_pool_manager.cleanup_old_tabs(force_cleanup=True)
            tab_count_after = len(tab_pool)

            logger.info(f"탭 정리 완료: {tab_count_before} -> {tab_count_after}")

            # 남은 탭에서 캐시 정리
            if tab_pool:
                tab = next(iter(tab_pool.values()))
                try:
                    await tab.evaluate("""() => {
                        try {
                            if (window.gc) { window.gc(); }
                        } catch (e) {}
                    }""")
                except Exception as e:
                    logger.warning(f"브라우저 캐시 정리 중 오류: {str(e)}")

            # 가비지 컬렉션 강제 실행
            gc.collect()

            # 메모리 사용량 다시 확인
            process = psutil.Process(os.getpid())
            memory_after = process.memory_info().rss / (1024 * 1024)
            logger.info(f"정리 후 메모리 사용량: {memory_after:.2f}MB")

        except Exception as e:
            logger.error(f"리소스 정리 중 오류 발생: {str(e)}")

    async def perform_global_cleanup(self):
        """전역 탭 풀 정리를 수행합니다."""
        logger.info("전체 리소스 정리를 시작합니다...")

        try:
            # 사용 중이지 않은 탭 정리
            await self.tab_pool_manager.cleanup_old_tabs(force_cleanup=True)

            # 메모리 상태 보고
            process = psutil.Process(os.getpid())
            memory_info = process.memory_info()
            memory_mb = memory_info.rss / (1024 * 1024)

            tab_pool = self.tab_pool_manager.tab_pool
            logger.info(
                f"[시스템 상태] 메모리: {memory_mb:.2f}MB, "
                f"탭: {len(tab_pool)}/{self.tab_pool_manager.TOTAL_MAX_TABS}"
            )

        except Exception as e:
            logger.error(f"전체 리소스 정리 중 오류 발생: {str(e)}")

    def stop(self):
        """리소스 모니터링을 중지합니다."""
        self._running = False
        if self.resource_cleanup_task:
            self.resource_cleanup_task.cancel()
            self.resource_cleanup_task = None
