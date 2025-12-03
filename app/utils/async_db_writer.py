# app/utils/async_db_writer.py
"""
비동기 DB 쓰기를 위한 큐 기반 Writer

모니터링 루프를 블로킹하지 않고 DB 작업을 백그라운드에서 처리합니다.
선착순 예약 시스템과 같이 밀리초 단위 응답이 중요한 경우에 유용합니다.
"""

import asyncio
import logging
from typing import Callable, Optional, List, Tuple, Any
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class DBOperation:
    """DB 작업을 나타내는 데이터 클래스"""
    operation: Callable
    args: Tuple
    kwargs: dict
    created_at: datetime
    priority: int = 0  # 낮을수록 높은 우선순위


class AsyncDBWriter:
    """
    비동기 DB 쓰기를 위한 큐 기반 Writer

    사용법:
        writer = AsyncDBWriter()
        await writer.start()

        # 비동기 컨텍스트에서
        await writer.write(db_update_function, arg1, arg2, kwarg1=value1)

        # 동기 컨텍스트에서 (논블로킹)
        writer.write_nowait(db_update_function, arg1, arg2)

        # 종료 시
        await writer.stop()
    """

    def __init__(
        self,
        batch_size: int = 10,
        flush_interval: float = 1.0,
        max_queue_size: int = 1000,
        name: str = "default"
    ):
        """
        Args:
            batch_size: 한 번에 처리할 최대 작업 수
            flush_interval: 배치 수집 타임아웃 (초)
            max_queue_size: 최대 큐 크기 (초과 시 경고)
            name: Writer 이름 (로깅용)
        """
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.max_queue_size = max_queue_size
        self.name = name

        self.queue: asyncio.Queue = asyncio.Queue()
        self._running = False
        self._task: Optional[asyncio.Task] = None

        # 통계
        self._total_operations = 0
        self._failed_operations = 0
        self._total_batches = 0

    async def start(self):
        """Writer 백그라운드 태스크 시작"""
        if self._running:
            logger.warning(f"[{self.name}] AsyncDBWriter가 이미 실행 중입니다")
            return

        self._running = True
        self._task = asyncio.create_task(self._process_loop())
        logger.info(f"[{self.name}] AsyncDBWriter 시작됨 (batch_size={self.batch_size}, flush_interval={self.flush_interval}s)")

    async def stop(self, timeout: float = 10.0):
        """
        안전한 종료 - 남은 작업 모두 처리 후 종료

        Args:
            timeout: 종료 대기 최대 시간 (초)
        """
        if not self._running:
            return

        logger.info(f"[{self.name}] AsyncDBWriter 종료 시작 (남은 작업: {self.queue.qsize()}개)")
        self._running = False

        # 남은 작업 처리
        try:
            await asyncio.wait_for(self._flush_remaining(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(f"[{self.name}] 종료 타임아웃 - 일부 작업이 처리되지 않았을 수 있음")

        # 태스크 취소
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        logger.info(
            f"[{self.name}] AsyncDBWriter 종료됨 "
            f"(총 작업: {self._total_operations}, 실패: {self._failed_operations}, 배치: {self._total_batches})"
        )

    async def write(self, operation: Callable, *args, **kwargs):
        """
        쓰기 작업을 큐에 추가 (비동기, awaitable)

        Args:
            operation: 실행할 DB 작업 함수
            *args: 함수 인자
            **kwargs: 함수 키워드 인자
        """
        if not self._running:
            logger.warning(f"[{self.name}] Writer가 실행 중이 아닙니다. 직접 실행합니다.")
            await asyncio.to_thread(operation, *args, **kwargs)
            return

        await self._check_queue_size()
        op = DBOperation(
            operation=operation,
            args=args,
            kwargs=kwargs,
            created_at=datetime.now()
        )
        await self.queue.put(op)

    def write_nowait(self, operation: Callable, *args, **kwargs):
        """
        쓰기 작업을 큐에 추가 (동기, 논블로킹)

        동기 함수에서 호출할 때 사용합니다.
        큐가 가득 차면 QueueFull 예외가 발생할 수 있습니다.

        Args:
            operation: 실행할 DB 작업 함수
            *args: 함수 인자
            **kwargs: 함수 키워드 인자
        """
        if not self._running:
            logger.warning(f"[{self.name}] Writer가 실행 중이 아닙니다")
            return

        op = DBOperation(
            operation=operation,
            args=args,
            kwargs=kwargs,
            created_at=datetime.now()
        )
        try:
            self.queue.put_nowait(op)
            logger.debug(f"[{self.name}] 큐 추가: {operation.__name__}")
        except asyncio.QueueFull:
            logger.error(f"[{self.name}] 큐가 가득 찼습니다. 작업이 무시됩니다: {operation.__name__}")

    async def write_priority(self, operation: Callable, priority: int, *args, **kwargs):
        """
        우선순위가 있는 쓰기 작업 추가

        Args:
            operation: 실행할 DB 작업 함수
            priority: 우선순위 (낮을수록 먼저 실행)
            *args: 함수 인자
            **kwargs: 함수 키워드 인자
        """
        await self._check_queue_size()
        op = DBOperation(
            operation=operation,
            args=args,
            kwargs=kwargs,
            created_at=datetime.now(),
            priority=priority
        )
        await self.queue.put(op)

    async def _check_queue_size(self):
        """큐 크기 확인 및 경고"""
        current_size = self.queue.qsize()
        if current_size > self.max_queue_size * 0.8:
            logger.warning(
                f"[{self.name}] 큐 크기 경고: {current_size}/{self.max_queue_size} "
                f"({current_size / self.max_queue_size * 100:.1f}%)"
            )

    async def _process_loop(self):
        """백그라운드에서 큐를 처리하는 메인 루프"""
        logger.debug(f"[{self.name}] 처리 루프 시작")

        while self._running:
            batch: List[DBOperation] = []

            try:
                # 배치 수집
                while len(batch) < self.batch_size:
                    try:
                        op = await asyncio.wait_for(
                            self.queue.get(),
                            timeout=self.flush_interval
                        )
                        batch.append(op)
                        self.queue.task_done()
                    except asyncio.TimeoutError:
                        # 타임아웃 시 현재 배치 처리
                        break

                # 배치가 있으면 실행
                if batch:
                    # 우선순위별 정렬
                    batch.sort(key=lambda x: x.priority)
                    await self._execute_batch(batch)

            except asyncio.CancelledError:
                # 취소 시 남은 배치 처리
                if batch:
                    await self._execute_batch(batch)
                raise
            except Exception as e:
                logger.error(f"[{self.name}] 처리 루프 오류: {e}", exc_info=True)
                await asyncio.sleep(1)  # 오류 시 잠시 대기

    async def _execute_batch(self, batch: List[DBOperation]):
        """
        배치 작업 실행 (스레드 풀에서)

        Args:
            batch: 실행할 DB 작업 목록
        """
        if not batch:
            return

        self._total_batches += 1

        try:
            await asyncio.to_thread(self._sync_execute_batch, batch)
        except Exception as e:
            logger.error(f"[{self.name}] 배치 실행 오류: {e}", exc_info=True)

    def _sync_execute_batch(self, batch: List[DBOperation]):
        """
        실제 DB 작업 실행 (동기, 스레드 풀에서 호출됨)

        Args:
            batch: 실행할 DB 작업 목록
        """
        for op in batch:
            try:
                op.operation(*op.args, **op.kwargs)
                self._total_operations += 1
            except Exception as e:
                self._failed_operations += 1
                logger.error(
                    f"[{self.name}] DB 작업 실패: {op.operation.__name__} - {e}",
                    exc_info=True
                )

    async def _flush_remaining(self):
        """남은 모든 작업 처리"""
        remaining: List[DBOperation] = []

        while not self.queue.empty():
            try:
                op = self.queue.get_nowait()
                remaining.append(op)
                self.queue.task_done()
            except asyncio.QueueEmpty:
                break

        if remaining:
            logger.info(f"[{self.name}] 종료 전 {len(remaining)}개 작업 처리 중...")
            await self._execute_batch(remaining)

    @property
    def pending_count(self) -> int:
        """대기 중인 작업 수"""
        return self.queue.qsize()

    @property
    def stats(self) -> dict:
        """통계 정보 반환"""
        return {
            "name": self.name,
            "running": self._running,
            "pending": self.queue.qsize(),
            "total_operations": self._total_operations,
            "failed_operations": self._failed_operations,
            "total_batches": self._total_batches,
            "success_rate": (
                (self._total_operations - self._failed_operations) / self._total_operations * 100
                if self._total_operations > 0 else 100.0
            )
        }


# 싱글톤 인스턴스 (전역 사용용)
_default_writer: Optional[AsyncDBWriter] = None


async def get_db_writer() -> AsyncDBWriter:
    """기본 DB Writer 인스턴스 반환 (싱글톤)"""
    global _default_writer
    if _default_writer is None:
        _default_writer = AsyncDBWriter(name="global")
        await _default_writer.start()
    return _default_writer


async def shutdown_db_writer():
    """기본 DB Writer 종료"""
    global _default_writer
    if _default_writer is not None:
        await _default_writer.stop()
        _default_writer = None
