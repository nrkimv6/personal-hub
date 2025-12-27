"""
워커 기본 클래스.

모든 워커가 상속받는 추상 기본 클래스입니다.
공통 기능 (heartbeat, 시그널 핸들링, 에러 핸들링 등)을 제공합니다.

사용 예시:
    class MyWorker(BaseWorker):
        def __init__(self, browser_manager):
            super().__init__("my_worker", browser_manager)

        async def _main_loop_iteration(self):
            # 한 사이클의 작업 수행
            await self._process_requests()

        def _get_loop_interval(self) -> float:
            return 5.0  # 5초마다 실행
"""
import asyncio
import os
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional, Set, TYPE_CHECKING

if TYPE_CHECKING:
    from app.shared.browser.browser_manager import BrowserManager

logger = logging.getLogger(__name__)


class BaseWorker(ABC):
    """워커 기본 클래스 (추상).

    모든 워커는 이 클래스를 상속받아 구현합니다.
    공통 기능:
    - 메인 루프 관리
    - Heartbeat 업데이트
    - 백그라운드 태스크 관리
    - 시그널 핸들링
    - 에러 핸들링

    Attributes:
        name: 워커 이름 (로깅/상태 추적용)
        browser: BrowserManager 참조 (소유 X, 참조만)
        shutdown_event: 종료 신호용 이벤트
        pid: 프로세스 ID
        start_time: 워커 시작 시간
        worker_id: 워커 상태 추적용 ID (DB 저장)
    """

    def __init__(
        self,
        name: str,
        browser_manager: Optional["BrowserManager"] = None
    ):
        """BaseWorker 초기화.

        Args:
            name: 워커 이름 (예: "scheduled_worker", "ondemand_worker")
            browser_manager: BrowserManager 참조 (소유하지 않음)
        """
        self.name = name
        self.browser = browser_manager  # 소유 X, 참조만
        self.shutdown_event = asyncio.Event()
        self.pid = os.getpid()
        self.start_time: Optional[datetime] = None
        self.worker_id: Optional[str] = None
        self._running = False

        # 백그라운드 태스크 관리
        self._running_tasks: Set[asyncio.Task] = set()

    @property
    def is_running(self) -> bool:
        """워커 실행 중 여부."""
        return self._running

    @property
    def uptime_seconds(self) -> float:
        """워커 가동 시간 (초)."""
        if not self.start_time:
            return 0.0
        return (datetime.now() - self.start_time).total_seconds()

    async def run(self):
        """워커 실행.

        메인 진입점입니다. start()와 동일한 기능을 합니다.
        """
        await self.start()

    async def start(self):
        """워커 시작."""
        logger.info(f"[{self.name}] 워커 시작 (PID: {self.pid})")
        self._running = True
        self.start_time = datetime.now()

        # 워커 상태 등록
        self._register_worker_status()

        try:
            # 초기화
            await self._initialize()

            # 메인 루프 실행
            await self._main_loop()

        except asyncio.CancelledError:
            logger.info(f"[{self.name}] 워커 취소됨")
            raise

        except Exception as e:
            logger.error(f"[{self.name}] 워커 오류: {e}", exc_info=True)
            raise

        finally:
            self._running = False
            await self._cleanup()
            logger.info(f"[{self.name}] 워커 종료")

    def stop(self):
        """워커 중지 신호.

        비동기가 아닌 동기 메서드로 시그널 핸들러에서 호출할 수 있습니다.
        """
        logger.info(f"[{self.name}] 종료 요청")
        self.shutdown_event.set()

    async def stop_async(self):
        """워커 중지 (비동기 버전)."""
        self.stop()

    # ========== 추상 메서드 (하위 클래스에서 구현) ==========

    @abstractmethod
    async def _main_loop_iteration(self):
        """메인 루프 한 사이클의 작업.

        하위 클래스에서 구현합니다.
        이 메서드는 _main_loop에서 반복적으로 호출됩니다.
        """
        pass

    @abstractmethod
    def _get_loop_interval(self) -> float:
        """메인 루프 간격 (초).

        하위 클래스에서 구현합니다.
        Returns:
            float: 루프 사이클 간 대기 시간 (초)
        """
        pass

    # ========== 오버라이드 가능한 메서드 ==========

    async def _initialize(self):
        """초기화 로직.

        하위 클래스에서 필요시 오버라이드합니다.
        기본 구현은 아무것도 하지 않습니다.
        """
        pass

    async def _cleanup(self):
        """정리 로직.

        하위 클래스에서 필요시 오버라이드합니다.
        기본 구현은 실행 중인 태스크를 취소합니다.
        """
        # 1. 실행 중인 태스크 취소
        if self._running_tasks:
            logger.info(f"[{self.name}] 실행 중인 태스크 {len(self._running_tasks)}개 취소 중...")
            for task in self._running_tasks:
                if not task.done():
                    task.cancel()

            try:
                await asyncio.gather(*self._running_tasks, return_exceptions=True)
            except Exception as e:
                logger.warning(f"[{self.name}] 태스크 대기 중 오류 (무시): {e}")

            self._running_tasks.clear()

        # 2. 워커 상태를 종료로 표시
        self._mark_worker_dead()

    def _register_worker_status(self):
        """워커 상태를 DB에 등록.

        하위 클래스에서 필요시 오버라이드합니다.
        """
        # 기본 구현은 아무것도 하지 않음
        # 하위 클래스에서 WorkerStatusService를 사용하여 등록
        pass

    def _update_heartbeat(self):
        """워커 heartbeat 업데이트.

        하위 클래스에서 필요시 오버라이드합니다.
        """
        # 기본 구현은 아무것도 하지 않음
        pass

    def _mark_worker_dead(self):
        """워커를 종료 상태로 표시.

        하위 클래스에서 필요시 오버라이드합니다.
        """
        # 기본 구현은 아무것도 하지 않음
        pass

    # ========== 내부 메서드 ==========

    async def _main_loop(self):
        """메인 루프."""
        interval = self._get_loop_interval()
        logger.info(f"[{self.name}] 메인 루프 시작 (간격: {interval}초)")

        while not self.shutdown_event.is_set():
            try:
                # Heartbeat 업데이트
                self._update_heartbeat()

                # 완료된 태스크 정리
                self._cleanup_completed_tasks()

                # 메인 작업 실행
                await self._main_loop_iteration()

                # 대기
                await self._wait_for_next_cycle(interval)

            except asyncio.CancelledError:
                logger.info(f"[{self.name}] 메인 루프 취소됨")
                break

            except Exception as e:
                logger.error(f"[{self.name}] 메인 루프 오류: {e}", exc_info=True)
                await asyncio.sleep(5)  # 오류 시 5초 대기 후 재시도

    async def _wait_for_next_cycle(self, interval: float):
        """다음 사이클까지 대기.

        shutdown_event가 set되면 즉시 반환합니다.

        Args:
            interval: 대기 시간 (초)
        """
        try:
            await asyncio.wait_for(
                self.shutdown_event.wait(),
                timeout=interval
            )
        except asyncio.TimeoutError:
            pass  # 정상적인 타임아웃

    def _cleanup_completed_tasks(self):
        """완료된 백그라운드 태스크 정리."""
        completed = {t for t in self._running_tasks if t.done()}
        for task in completed:
            try:
                exc = task.exception()
                if exc:
                    logger.error(f"[{self.name}] 태스크 예외: {task.get_name()} - {exc}")
            except asyncio.CancelledError:
                pass
            except asyncio.InvalidStateError:
                pass
        self._running_tasks -= completed

    def _is_task_running(self, task_name: str) -> bool:
        """특정 이름의 태스크가 실행 중인지 확인.

        Args:
            task_name: 태스크 이름

        Returns:
            bool: 실행 중이면 True
        """
        for task in self._running_tasks:
            if task.get_name() == task_name:
                return True
        return False

    def _create_task(self, coro, name: str) -> asyncio.Task:
        """백그라운드 태스크 생성 및 추적.

        Args:
            coro: 실행할 코루틴
            name: 태스크 이름

        Returns:
            asyncio.Task: 생성된 태스크
        """
        task = asyncio.create_task(coro, name=name)
        self._running_tasks.add(task)
        return task

    def get_status(self) -> dict:
        """워커 상태 정보 반환.

        Returns:
            dict: 상태 정보
        """
        return {
            "name": self.name,
            "pid": self.pid,
            "running": self._running,
            "worker_id": self.worker_id,
            "uptime_seconds": self.uptime_seconds,
            "running_tasks": len(self._running_tasks),
            "start_time": self.start_time.isoformat() if self.start_time else None,
        }
