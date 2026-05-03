"""
워커 오케스트레이터.

모든 워커를 관리하고, 예외 격리와 자동 복구를 담당합니다.

Layer 1 예외 처리:
    - asyncio.gather(return_exceptions=True)로 태스크 크래시 감지
    - 태스크 감독 (supervision)으로 자동 재시작
    - Fail-Fast 전략: 재시작 횟수 초과 시 프로세스 종료 → Watchdog 위임

Redis 큐 지원:
    - 시작 시 Redis 연결 초기화
    - 종료 시 Redis 연결 정리

사용 예시:
    orchestrator = WorkerOrchestrator()
    await orchestrator.initialize()
    await orchestrator.run()
"""
import asyncio
import logging
import sys
import time
from collections import defaultdict
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, TYPE_CHECKING

from app.shared.browser.browser_manager import BrowserManager
from app.shared.worker.base_worker import BaseWorker
from app.shared.worker.exceptions import WorkerCriticalError
from app.shared.redis import RedisClient
from app.shared.process.orphan_detector import OrphanDetector
from app.shared.process.registry import ProcessRegistry

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class WorkerState(Enum):
    """워커 상태 열거형."""
    PENDING = "pending"      # 시작 전
    RUNNING = "running"      # 실행 중
    STOPPED = "stopped"      # 정상 종료
    ERROR = "error"          # 에러 발생
    FAILED = "failed"        # 영구 실패 (재시작 포기)


class WorkerOrchestrator:
    """워커 오케스트레이터.

    모든 워커를 관리하고, 예외 격리와 자동 복구를 담당합니다.

    Attributes:
        browser_manager: 브라우저 중앙 관리자
        workers: 이름별 워커 인스턴스
        tasks: 이름별 asyncio 태스크
        worker_states: 이름별 워커 상태
        shutdown_event: 종료 신호용 이벤트

    상수:
        MAX_RESTARTS: 5분 내 최대 재시작 횟수 (기본 5회)
        RESTART_WINDOW: 재시작 카운트 윈도우 (기본 300초 = 5분)
        SHUTDOWN_TIMEOUT: 종료 대기 타임아웃 (기본 30초)
    """

    # 클래스 상수
    MAX_RESTARTS = 5
    RESTART_WINDOW = 300  # 5분
    SHUTDOWN_TIMEOUT = 30

    def __init__(self):
        """WorkerOrchestrator 초기화."""
        self.browser_manager: Optional[BrowserManager] = None
        self.workers: Dict[str, BaseWorker] = {}
        self.tasks: Dict[str, asyncio.Task] = {}
        self.shutdown_event = asyncio.Event()

        # 워커별 상태 추적
        self.worker_states: Dict[str, WorkerState] = {}
        self.restart_times: Dict[str, List[float]] = defaultdict(list)

        self._initialized = False
        self._orphan_task: Optional[asyncio.Task] = None

    async def initialize(self):
        """브라우저 매니저, Redis 및 워커 초기화.

        이 메서드는 run() 전에 호출되어야 합니다.
        하위 클래스에서 오버라이드하여 워커를 등록합니다.
        """
        if self._initialized:
            logger.debug("[Orchestrator] 이미 초기화됨")
            return

        logger.info("[Orchestrator] 초기화 시작")

        # 1. Redis 연결 초기화
        redis_client = await RedisClient.get_client()
        if redis_client:
            health = await RedisClient.health_check()
            logger.info(
                f"[Orchestrator] Redis 연결 완료: "
                f"{health.get('host')}:{health.get('port')} "
                f"(v{health.get('version', 'unknown')})"
            )
        else:
            logger.info("[Orchestrator] Redis 미연결 - SQLite 폴링 모드로 동작")

        # 2. 브라우저 매니저 초기화
        self.browser_manager = BrowserManager()
        await self.browser_manager.initialize()
        logger.info("[Orchestrator] BrowserManager 초기화 완료")

        self._initialized = True
        logger.info("[Orchestrator] 초기화 완료")

    def register_worker(self, name: str, worker: BaseWorker):
        """워커 등록.

        Args:
            name: 워커 이름 (고유해야 함)
            worker: BaseWorker 인스턴스

        Raises:
            ValueError: 이미 등록된 이름인 경우
        """
        if name in self.workers:
            raise ValueError(f"워커 '{name}'이 이미 등록되어 있습니다.")

        self.workers[name] = worker
        self.worker_states[name] = WorkerState.PENDING
        logger.info(f"[Orchestrator] 워커 등록: {name}")

    async def run(self):
        """모든 워커 실행 및 감시.

        등록된 모든 워커를 병렬로 실행하고 감시합니다.
        워커가 크래시하면 자동으로 재시작합니다.
        모든 워커가 종료되거나 shutdown_event가 설정되면 반환합니다.
        """
        if not self._initialized:
            raise RuntimeError(
                "Orchestrator가 초기화되지 않았습니다. initialize()를 먼저 호출하세요."
            )

        if not self.workers:
            logger.warning("[Orchestrator] 등록된 워커가 없습니다.")
            return

        logger.info(
            f"[Orchestrator] 워커 실행 시작: {list(self.workers.keys())}"
        )

        # 워커별 태스크 생성 (supervision 포함)
        for name, worker in self.workers.items():
            self.tasks[name] = asyncio.create_task(
                self._run_worker_with_supervision(name, worker),
                name=f"worker_{name}"
            )

        # OrphanDetector 태스크 시작
        from app.core.config import settings
        self._orphan_task = asyncio.create_task(
            OrphanDetector(
                ProcessRegistry(),
                repo_root=Path(__file__).resolve().parents[2],
                cleanup_callback=self._cleanup_orphan_test_worktrees,
            ).run_periodic(
                settings.PROCESS_SCAN_INTERVAL,
                settings.MEMORY_PRESSURE_CHECK_INTERVAL,
            ),
            name="orphan_detector",
        )

        # 모든 태스크 완료 대기
        try:
            results = await asyncio.gather(
                *self.tasks.values(),
                return_exceptions=True
            )

            # 결과 분석
            for name, result in zip(self.tasks.keys(), results):
                if isinstance(result, Exception):
                    logger.error(f"[Orchestrator] 워커 {name} 비정상 종료: {result}")
                else:
                    logger.info(f"[Orchestrator] 워커 {name} 정상 종료")

        except asyncio.CancelledError:
            logger.info("[Orchestrator] 실행 취소됨")

    async def _run_worker_with_supervision(
        self,
        name: str,
        worker: BaseWorker
    ):
        """워커 실행 및 자동 재시작 감독.

        워커가 예외로 종료되면 재시작을 시도합니다.
        5분 내 5회 재시작 초과 시 영구 실패로 표시하고 중단합니다.

        Fail-Fast 전략:
            - 재시작 횟수 초과 시 해당 워커만 중단
            - 모든 워커가 FAILED 상태가 되면 프로세스 종료 → Watchdog 재시작
        """
        while not self.shutdown_event.is_set():
            try:
                self.worker_states[name] = WorkerState.RUNNING
                logger.info(f"[Orchestrator] 워커 {name} 시작")

                await worker.run()

                # 정상 종료
                self.worker_states[name] = WorkerState.STOPPED
                logger.info(f"[Orchestrator] 워커 {name} 정상 종료")
                break

            except asyncio.CancelledError:
                self.worker_states[name] = WorkerState.STOPPED
                logger.info(f"[Orchestrator] 워커 {name} 취소됨")
                break

            except WorkerCriticalError as e:
                # 치명적 에러 → 재시작 시도
                self.worker_states[name] = WorkerState.ERROR
                logger.error(
                    f"[Orchestrator] 워커 {name} 치명적 에러: {e}",
                    exc_info=True
                )

                if not await self._should_restart(name):
                    break

            except Exception as e:
                # 일반 예외 → 재시작 시도
                self.worker_states[name] = WorkerState.ERROR
                logger.error(
                    f"[Orchestrator] 워커 {name} 예외 발생: {e}",
                    exc_info=True
                )

                if not await self._should_restart(name):
                    break

        # 모든 워커가 FAILED인지 체크
        self._check_all_workers_failed()

    async def _should_restart(self, name: str) -> bool:
        """재시작 여부 결정.

        5분 내 재시작 횟수를 체크하여 재시작 여부를 결정합니다.

        Args:
            name: 워커 이름

        Returns:
            bool: 재시작해야 하면 True
        """
        now = time.time()

        # 5분 이내 재시작 기록만 유지
        self.restart_times[name] = [
            t for t in self.restart_times[name]
            if now - t < self.RESTART_WINDOW
        ]
        self.restart_times[name].append(now)

        restart_count = len(self.restart_times[name])

        if restart_count >= self.MAX_RESTARTS:
            logger.critical(
                f"[Orchestrator] 워커 {name}: {self.RESTART_WINDOW}초 내 "
                f"{self.MAX_RESTARTS}회 재시작 초과. 영구 중지."
            )
            self.worker_states[name] = WorkerState.FAILED
            await self._send_worker_failure_alert(name)
            return False

        # Exponential backoff로 대기
        wait_time = min(30, 2 ** restart_count)
        logger.warning(
            f"[Orchestrator] 워커 {name}: {wait_time}초 후 재시작 "
            f"({restart_count}/{self.MAX_RESTARTS})"
        )

        try:
            await asyncio.wait_for(
                self.shutdown_event.wait(),
                timeout=wait_time
            )
            # shutdown_event가 set되면 재시작 안 함
            return False
        except asyncio.TimeoutError:
            # 타임아웃 → 재시작 진행
            return True

    def _check_all_workers_failed(self):
        """모든 워커가 FAILED 상태인지 체크.

        모든 워커가 FAILED면 프로세스를 종료하여 Watchdog이 재시작하도록 합니다.
        """
        if not self.workers:
            return

        all_failed = all(
            state == WorkerState.FAILED
            for state in self.worker_states.values()
        )

        if all_failed:
            logger.critical(
                "[Orchestrator] 모든 워커가 FAILED 상태. 프로세스 종료."
            )
            # 비동기 종료 시작
            asyncio.create_task(self._force_exit())

    async def _force_exit(self):
        """프로세스 강제 종료.

        cleanup 후 exit code 1로 종료합니다.
        Watchdog이 이를 감지하고 프로세스를 재시작합니다.
        """
        try:
            await self.shutdown()
        except Exception as e:
            logger.error(f"[Orchestrator] 종료 중 오류: {e}")
        finally:
            sys.exit(1)

    async def _send_worker_failure_alert(self, name: str):
        """워커 실패 알림 발송.

        Args:
            name: 실패한 워커 이름
        """
        # Permanent worker failures are surfaced through logs; notification fan-out
        # is handled outside the core supervisor.
        logger.warning(
            f"[Orchestrator] 워커 {name} 영구 실패 알림"
        )

    async def _cleanup_orphan_test_worktrees(self, branches: list[str]) -> object:
        from app.modules.dev_runner.services.worktree_service import cleanup_worktrees

        return await cleanup_worktrees(
            branches,
            dry_run=False,
            repo_root=Path(__file__).resolve().parents[2],
        )

    async def shutdown(self):
        """모든 워커 정상 종료.

        모든 워커에 종료 신호를 보내고 완료를 대기합니다.
        타임아웃 시 강제 취소합니다.
        """
        logger.info("[Orchestrator] 종료 시작")
        self.shutdown_event.set()

        # OrphanDetector 태스크 취소
        if self._orphan_task and not self._orphan_task.done():
            self._orphan_task.cancel()
            try:
                await self._orphan_task
            except asyncio.CancelledError:
                pass

        # 모든 워커에 종료 신호
        for worker in self.workers.values():
            worker.request_shutdown()

        # 태스크 완료 대기 (타임아웃)
        if self.tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self.tasks.values(), return_exceptions=True),
                    timeout=self.SHUTDOWN_TIMEOUT
                )
            except asyncio.TimeoutError:
                logger.warning(
                    f"[Orchestrator] 워커 종료 타임아웃 ({self.SHUTDOWN_TIMEOUT}초), 강제 취소"
                )
                for task in self.tasks.values():
                    if not task.done():
                        task.cancel()

                # 취소 완료 대기
                await asyncio.gather(*self.tasks.values(), return_exceptions=True)

        # 브라우저 정리
        if self.browser_manager:
            await self.browser_manager.cleanup()

        # Redis 연결 정리
        await RedisClient.close()
        logger.info("[Orchestrator] Redis 연결 종료")

        self._initialized = False
        logger.info("[Orchestrator] 종료 완료")

    def get_status(self) -> dict:
        """오케스트레이터 상태 정보 반환.

        Returns:
            dict: 상태 정보
        """
        return {
            "initialized": self._initialized,
            "shutdown_requested": self.shutdown_event.is_set(),
            "worker_count": len(self.workers),
            "worker_states": {
                name: state.value
                for name, state in self.worker_states.items()
            },
            "restart_counts": {
                name: len(times)
                for name, times in self.restart_times.items()
            },
            "browser_status": (
                self.browser_manager.get_status()
                if self.browser_manager else None
            ),
            "redis_connected": RedisClient.is_connected(),
        }

    async def __aenter__(self):
        """비동기 컨텍스트 매니저 진입."""
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """비동기 컨텍스트 매니저 종료."""
        await self.shutdown()
        return False
