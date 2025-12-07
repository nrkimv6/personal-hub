"""
모니터링 대기열 관리 모듈

모니터링 태스크의 시작, 중지, 대기열 관리를 담당합니다.
"""

import asyncio
import time
from datetime import datetime
from typing import Dict, Optional, TYPE_CHECKING

from app.config import settings, logger

if TYPE_CHECKING:
    from .tab_pool_manager import TabPoolManager
    from .monitoring_executor import MonitoringExecutor


class MonitoringQueue:
    """모니터링 대기열 관리자"""

    def __init__(
        self,
        tab_pool_manager: "TabPoolManager",
        monitoring_executor: "MonitoringExecutor",
        schedule_service
    ):
        """
        MonitoringQueue 초기화

        Args:
            tab_pool_manager: 탭 풀 관리자
            monitoring_executor: 모니터링 실행자
            schedule_service: 스케줄 서비스
        """
        self.tab_pool_manager = tab_pool_manager
        self.monitoring_executor = monitoring_executor
        self.schedule_service = schedule_service

        # 모니터링 태스크 관리
        self.monitoring_tasks: Dict[int, asyncio.Task] = {}

        # 대기열 관련
        self.monitoring_queue: Optional[asyncio.Queue] = None
        self.monitoring_queue_tasks: Dict[int, dict] = {}
        self.queue_processor_task: Optional[asyncio.Task] = None

        # 설정
        self.TOTAL_MAX_TABS = settings.TOTAL_MAX_TABS

    async def start_monitoring(self, data: dict):
        """새로운 모니터링을 시작합니다."""
        try:
            logger.info(f"모니터링 시작 요청: {data}")

            target_id = data.get("id")

            # 현재 실행 중인 모니터링 태스크 수 확인
            active_tasks = sum(1 for task in self.monitoring_tasks.values() if not task.done())
            logger.info(f"현재 실행 중인 모니터링 태스크 수: {active_tasks}, 전체 탭 제한: {self.TOTAL_MAX_TABS}")

            # 대기열 초기화
            if self.monitoring_queue is None:
                self.monitoring_queue = asyncio.Queue()
                self.monitoring_queue_tasks = {}
                self.queue_processor_task = asyncio.create_task(self._process_monitoring_queue())
                logger.info("모니터링 대기열 시스템 초기화")

            if target_id:
                logger.info(f"기존 모니터링 스케줄 사용: ID {target_id}")
                schedule = self.schedule_service.get_schedule(target_id)
                if not schedule:
                    logger.error(f"모니터링 스케줄을 찾을 수 없음: ID {target_id}")
                    raise ValueError(f"모니터링 스케줄을 찾을 수 없음: ID {target_id}")
            else:
                logger.error("모니터링 스케줄 ID가 필요합니다")
                raise ValueError("모니터링 스케줄 ID가 필요합니다")

            # 이미 모니터링 중인지 확인
            if target_id in self.monitoring_tasks and not self.monitoring_tasks[target_id].done():
                logger.info(f"모니터링이 이미 실행 중: ID {target_id}")
                return target_id

            # 이미 대기열에 있는지 확인
            if target_id in self.monitoring_queue_tasks:
                logger.info(f"모니터링이 이미 대기열에 있음: ID {target_id}")
                return target_id

            # 전체 활성 탭 수 확인
            total_tabs = len(self.tab_pool_manager.tab_pool)

            # 제한에 걸리면 대기열에 추가
            if active_tasks >= self.TOTAL_MAX_TABS or total_tabs >= self.TOTAL_MAX_TABS:
                update_data = {
                    "is_active": True,
                    "run_status": "queued",
                    "error_count": 0,
                    "last_error": f"전체 탭 수 제한({self.TOTAL_MAX_TABS}개)에 도달하여 대기열에 추가됨"
                }

                if not schedule.get("is_enabled", True):
                    update_data["is_enabled"] = False

                self.schedule_service.update_schedule(target_id, update_data)

                logger.warning(f"전체 탭 수 제한({self.TOTAL_MAX_TABS}개)에 도달. 현재 활성 태스크 수: {active_tasks}개, 탭 수: {total_tabs}개")
                logger.info(f"대상 {target_id}({schedule.get('label')})를 대기열에 추가합니다.")

                queue_item = {
                    "target_id": target_id,
                    "schedule": schedule,
                    "added_time": time.time()
                }

                await self.monitoring_queue.put(queue_item)
                self.monitoring_queue_tasks[target_id] = queue_item

                queue_size = self.monitoring_queue.qsize()
                logger.info(f"현재 대기 중인 모니터링 수: {queue_size}개")

                logger.info(
                    f"대기열 추가 - 대상: {schedule.get('label')}, "
                    f"대기 순서: {queue_size}번째, "
                    f"실행 중인 모니터링: {active_tasks}/{self.TOTAL_MAX_TABS}개, "
                    f"사용 중인 탭: {total_tabs}/{self.TOTAL_MAX_TABS}개"
                )

                return target_id

            # 제한에 걸리지 않은 경우 바로 시작
            update_data = {
                "is_active": True,
                "run_status": "running",
                "error_count": 0,
                "last_error": None
            }

            if not schedule.get("is_enabled", True):
                update_data["is_enabled"] = False

            self.schedule_service.update_schedule(target_id, update_data)

            logger.info(f"모니터링 태스크 생성 시작: ID {target_id}, URL: {schedule.get('url')}")

            try:
                task = asyncio.create_task(self._monitor_url(target_id, schedule.get('url'), schedule.get('label')))

                def task_done_callback(fut):
                    try:
                        if fut.exception():
                            logger.error(f"모니터링 태스크 예외 발생 (ID {target_id}): {fut.exception()}")
                        else:
                            logger.info(f"모니터링 태스크 정상 종료 (ID {target_id})")

                        asyncio.create_task(self._check_queue_after_task_completion())
                    except asyncio.CancelledError:
                        logger.info(f"모니터링 태스크 취소됨 (ID {target_id})")
                        asyncio.create_task(self._check_queue_after_task_completion())
                    except Exception as e:
                        logger.error(f"태스크 콜백 처리 중 오류: {str(e)}")

                task.add_done_callback(task_done_callback)
                self.monitoring_tasks[target_id] = task
                logger.info(f"모니터링 태스크 생성 및 시작 완료: ID {target_id}")

                await asyncio.sleep(0)

                if target_id in self.monitoring_tasks and not self.monitoring_tasks[target_id].done():
                    logger.info(f"태스크가 성공적으로 시작됨: ID {target_id}")
                else:
                    logger.warning(f"태스크가 즉시 종료되었거나 실패함: ID {target_id}")

            except Exception as e:
                logger.error(f"태스크 생성 중 오류 발생: {str(e)}")
                self.schedule_service.update_schedule(target_id, {"is_active": False})
                raise

            return target_id
        except Exception as e:
            logger.error(f"모니터링 시작 중 오류 발생: {str(e)}", exc_info=True)
            raise

    async def stop_monitoring(self, target_id: int) -> bool:
        """모니터링을 중지합니다."""
        try:
            logger.info(f"모니터링 중지 요청: ID {target_id}")

            # 대기열에 있는 항목인지 확인
            if target_id in self.monitoring_queue_tasks:
                logger.info(f"대기열에 있는 모니터링 중지: ID {target_id}")
                del self.monitoring_queue_tasks[target_id]
                self.schedule_service.update_schedule(target_id, {
                    "run_status": "stopped",
                    "last_error": "사용자가 대기 중인 모니터링을 취소함"
                })
                return True

            # 실행 중인 태스크인지 확인
            if target_id not in self.monitoring_tasks:
                logger.warning(f"실행 중인 모니터링 태스크가 없음: ID {target_id}")
                return False

            # 모니터링 상태 업데이트
            self.schedule_service.update_schedule(target_id, {
                "run_status": "stopped",
                "is_active": False
            })

            # 태스크 취소
            task = self.monitoring_tasks[target_id]
            if not task.done():
                logger.info(f"모니터링 태스크 취소 중: ID {target_id}")
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    logger.info(f"모니터링 태스크 취소 완료: ID {target_id}")
                except Exception as e:
                    logger.error(f"모니터링 태스크 취소 중 오류 발생: {str(e)}")

            # 리소스 정리
            await self.tab_pool_manager.cleanup_old_tabs()

            # 메모리 통계 정리
            if hasattr(self, 'memory_stats') and target_id in self.memory_stats:
                del self.memory_stats[target_id]

            # 모니터링 태스크 제거
            if target_id in self.monitoring_tasks:
                del self.monitoring_tasks[target_id]

            logger.info(f"모니터링 중지 완료: ID {target_id}")
            return True

        except Exception as e:
            logger.error(f"모니터링 중지 중 오류 발생: {str(e)}")
            return False

    async def add_to_monitoring_queue(self, target_data: dict):
        """모니터링 대상을 대기열에 추가합니다."""
        # 대기열 초기화
        if self.monitoring_queue is None:
            self.monitoring_queue = asyncio.Queue()
            self.monitoring_queue_tasks = {}
            self.queue_processor_task = asyncio.create_task(self._process_monitoring_queue())
            logger.info("모니터링 대기열 시스템 초기화")

        target_id = target_data.get("id")

        # 이미 대기열에 있는지 확인
        if target_id in self.monitoring_queue_tasks:
            logger.info(f"모니터링이 이미 대기열에 있음: ID {target_id}")
            return

        queue_item = {
            "target_id": target_id,
            "target": target_data,
            "added_time": time.time()
        }

        await self.monitoring_queue.put(queue_item)
        self.monitoring_queue_tasks[target_id] = queue_item

        self.schedule_service.update_schedule(target_id, {"run_status": "queued"})

        logger.info(f"대상 {target_id}({target_data.get('label', 'Unknown')})를 대기열에 추가합니다.")

    async def _monitor_url(self, target_id: int, url: str, label: str):
        """URL을 모니터링합니다."""
        check_count = 0

        try:
            while True:
                try:
                    current_time = time.time()

                    # 전역 일시중지 상태 확인
                    if self._is_global_paused():
                        await asyncio.sleep(1)
                        continue

                    # 모니터링 스케줄 정보 조회
                    schedule = self.schedule_service.get_schedule(target_id)
                    if not schedule or not schedule.get("is_active"):
                        logger.info(f"⏹️ [{label}] 모니터링 중지됨 (비활성화 또는 삭제)")
                        break

                    # 첫 실행인지 확인
                    is_first_run = target_id not in self.monitoring_executor.next_run_times

                    if is_first_run:
                        logger.info(f"[{label}] 첫 실행 - 즉시 시작")

                    check_count += 1
                    check_start_time = time.time()

                    logger.info(f"✓ [{label}] 확인 #{check_count} 시작 (URL: {url})")

                    # 태스크가 취소되었는지 확인
                    if asyncio.current_task().cancelled():
                        logger.info(f"[{label}] 태스크가 취소되어 종료합니다.")
                        break

                    await asyncio.sleep(0)

                    # 탭 가져오기
                    account_id = schedule.get("account_id")
                    tab = await self.tab_pool_manager.get_tab(target_id, account_id=account_id)
                    logger.info(f"[{label}] 탭 획득 성공 (계정 ID: {account_id})")

                    # 모니터링 수행
                    result = await self.monitoring_executor.perform_monitoring(tab, url, target_id, label, schedule)

                    # 탭 반환
                    await self.tab_pool_manager.release_tab(tab)
                    logger.info(f"[{label}] 탭 반환 완료")

                    # 다음 실행 시간 계산
                    next_run_time = self.monitoring_executor.calculate_next_run_time(schedule)
                    self.monitoring_executor.next_run_times[target_id] = next_run_time
                    remaining = int(next_run_time - time.time())
                    logger.info(f"[{label}] 다음 실행까지 {remaining}초 대기, 태스크 종료")

                    # DB 업데이트
                    next_run_datetime = datetime.fromtimestamp(next_run_time)
                    self.schedule_service.update_schedule(target_id, {
                        "last_check_time": datetime.now().isoformat(),
                        "next_run_time": next_run_datetime.isoformat()
                    })

                    # 대기열에 재진입
                    await self.add_to_monitoring_queue({
                        "id": target_id,
                        "url": url,
                        "label": label,
                        "next_run_time": next_run_time
                    })

                    # 현재 태스크 종료
                    if target_id in self.monitoring_tasks:
                        del self.monitoring_tasks[target_id]
                    break

                except Exception as e:
                    error_msg = str(e)
                    logger.error(f"[{label}] 모니터링 중 오류 발생: {error_msg}")

                    browser_closed_keywords = [
                        "Target page, context or browser has been closed",
                        "browser has been closed",
                        "context has been closed",
                        "page has been closed",
                        "Target closed",
                        "Connection closed"
                    ]
                    is_browser_closed = any(keyword.lower() in error_msg.lower() for keyword in browser_closed_keywords)

                    # 오류 발생 시에도 탭 반환 시도
                    if 'tab' in locals():
                        try:
                            await self.tab_pool_manager.release_tab(tab)
                        except Exception:
                            pass

                    # 브라우저 닫힘 오류인 경우 정리
                    if is_browser_closed and 'account_id' in locals() and account_id is not None:
                        logger.warning(f"[{label}] 브라우저 닫힘 감지, 계정 {account_id} 브라우저 정리 후 재시도...")
                        await self.tab_pool_manager.handle_browser_closed_error(account_id)
                        await asyncio.sleep(2)
                    else:
                        await asyncio.sleep(5)

        except asyncio.CancelledError:
            logger.info(f"[{label}] 모니터링 태스크가 취소되었습니다.")
        finally:
            if 'tab' in locals():
                await self.tab_pool_manager.release_tab(tab)

    async def _process_monitoring_queue(self):
        """대기열에 있는 모니터링 작업을 처리합니다."""
        logger.info("모니터링 대기열 처리 태스크 시작")
        try:
            while True:
                active_tasks = sum(1 for task in self.monitoring_tasks.values() if not task.done())
                total_tabs = len(self.tab_pool_manager.tab_pool)

                if active_tasks < self.TOTAL_MAX_TABS and total_tabs < self.TOTAL_MAX_TABS:
                    try:
                        # 대기열이 비어있으면 짧게 대기 후 다시 시도
                        if self.monitoring_queue.empty():
                            await asyncio.sleep(0.5)
                            continue

                        queue_item = await asyncio.wait_for(self.monitoring_queue.get(), timeout=0.5)
                        target_id = queue_item["target_id"]
                        target_data = queue_item.get("target", {})
                        schedule = queue_item.get("schedule") or self.schedule_service.get_schedule(target_id)
                        added_time = queue_item["added_time"]

                        # 다음 실행 시간 확인
                        next_run_time = target_data.get("next_run_time") or self.monitoring_executor.next_run_times.get(target_id)
                        current_time = time.time()

                        # 아직 실행 시간이 안 됐으면 다시 대기열에
                        if next_run_time and current_time < next_run_time:
                            remaining = int(next_run_time - current_time)
                            self.monitoring_queue.task_done()
                            await self.monitoring_queue.put(queue_item)
                            await asyncio.sleep(0.1)  # 짧게 대기 후 다른 작업 확인
                            continue

                        wait_time = current_time - added_time

                        # 대기열 항목 제거
                        if target_id in self.monitoring_queue_tasks:
                            del self.monitoring_queue_tasks[target_id]

                        logger.info(f"대기열에서 모니터링 시작: ID {target_id}, 대기 시간: {wait_time:.1f}초")

                        update_data = {
                            "is_active": True,
                            "run_status": "running",
                            "error_count": 0,
                            "last_error": None
                        }
                        self.schedule_service.update_schedule(target_id, update_data)

                        task = asyncio.create_task(self._monitor_url(target_id, schedule.get("url"), schedule.get("label")))

                        def task_done_callback(fut):
                            try:
                                if fut.exception():
                                    logger.error(f"대기열에서 시작된 태스크 예외 발생 (ID {target_id}): {fut.exception()}")
                                else:
                                    logger.info(f"대기열에서 시작된 태스크 정상 종료 (ID {target_id})")
                                asyncio.create_task(self._check_queue_after_task_completion())
                            except Exception as e:
                                logger.error(f"대기열 태스크 콜백 처리 중 오류: {str(e)}")

                        task.add_done_callback(task_done_callback)
                        self.monitoring_tasks[target_id] = task
                        self.monitoring_queue.task_done()

                        logger.info(
                            f"대기열 시작 - 대상: {schedule.get('label')}, "
                            f"대기 시간: {wait_time:.1f}초, "
                            f"현재 실행 중인 모니터링: {active_tasks+1}/{self.TOTAL_MAX_TABS}개"
                        )

                        # 여유 공간이 있으면 즉시 다음 항목 처리 시도 (sleep 없이)
                        continue

                    except asyncio.TimeoutError:
                        # 대기열에서 항목 가져오기 시간 초과
                        await asyncio.sleep(0.1)
                        continue
                    except asyncio.QueueEmpty:
                        await asyncio.sleep(0.5)
                        continue
                else:
                    # 탭 또는 태스크 제한에 도달, 대기
                    await asyncio.sleep(0.5)

        except asyncio.CancelledError:
            logger.info("모니터링 대기열 처리 태스크 취소됨")
        except Exception as e:
            logger.error(f"모니터링 대기열 처리 중 오류 발생: {str(e)}", exc_info=True)
            await asyncio.sleep(5)
            asyncio.create_task(self._process_monitoring_queue())

    async def _check_queue_after_task_completion(self):
        """태스크 완료 후 대기열에서 다음 항목을 처리할 수 있는지 확인합니다."""
        try:
            active_tasks = sum(1 for task in self.monitoring_tasks.values() if not task.done())
            total_tabs = len(self.tab_pool_manager.tab_pool)

            if self.monitoring_queue is not None and not self.monitoring_queue.empty():
                if active_tasks < self.TOTAL_MAX_TABS and total_tabs < self.TOTAL_MAX_TABS:
                    logger.info(f"태스크 완료 후 대기열 확인: 여유 공간 있음 (활성 태스크: {active_tasks}/{self.TOTAL_MAX_TABS}, 탭: {total_tabs}/{self.TOTAL_MAX_TABS})")
                    await asyncio.sleep(0.1)
                else:
                    logger.info(f"태스크 완료 후 대기열 확인: 여유 공간 없음 (활성 태스크: {active_tasks}/{self.TOTAL_MAX_TABS}, 탭: {total_tabs}/{self.TOTAL_MAX_TABS})")
        except Exception as e:
            logger.error(f"대기열 확인 중 오류 발생: {str(e)}")

    async def process_initial_queue(self, max_items: int):
        """대기열에서 지정된 수만큼 항목을 꺼내서 처리합니다."""
        logger.info(f"대기열에서 최대 {max_items}개 항목을 처리합니다.")

        # 브라우저 초기화
        if self.tab_pool_manager.context_manager.browser_context is None:
            logger.info("대기열 처리 전 브라우저 초기화 시작")
            await self.tab_pool_manager.context_manager.initialize_browser()
            logger.info("대기열 처리 전 브라우저 초기화 완료")

        processed_count = 0
        while processed_count < max_items and not self.monitoring_queue.empty():
            try:
                queue_item = await self.monitoring_queue.get()
                target_id = queue_item["target_id"]
                target = queue_item["target"]

                if target_id in self.monitoring_queue_tasks:
                    del self.monitoring_queue_tasks[target_id]

                update_data = {
                    "is_active": True,
                    "run_status": "running",
                    "error_count": 0,
                    "last_error": None
                }
                self.schedule_service.update_schedule(target_id, update_data)

                target = queue_item.get("target", {})
                task = asyncio.create_task(self._monitor_url(target_id, target.get('url'), target.get('label')))

                self.monitoring_tasks[target_id] = task
                self.monitoring_queue.task_done()

                processed_count += 1
                logger.info(f"대기열에서 모니터링 시작: ID {target_id}, 처리된 항목: {processed_count}/{max_items}")

            except Exception as e:
                logger.error(f"대기열 항목 처리 중 오류 발생: {str(e)}")

        logger.info(f"대기열 초기 처리 완료: {processed_count}개 항목 처리됨")

    def _is_global_paused(self) -> bool:
        """전역 모니터링 일시중지 상태를 확인합니다."""
        # BrowserService에서 이 기능을 위임받음
        from app.services.browser_service import get_browser_service
        return get_browser_service().is_global_paused()
