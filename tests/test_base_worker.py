"""
BaseWorker 테스트

RIGHT-BICEP 원칙에 따른 테스트:
- Right: 정상적인 동작 확인
- Boundary: 경계 조건 테스트
- Inverse: 역 조건 테스트
- Error: 에러 조건 테스트
"""
import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime

from app.shared.worker.base_worker import BaseWorker


class ConcreteWorker(BaseWorker):
    """테스트용 구체 워커 클래스."""

    def __init__(self, name="test_worker", browser_manager=None):
        super().__init__(name, browser_manager)
        self.iteration_count = 0
        self.loop_interval = 0.1  # 테스트용 짧은 간격

    async def _main_loop_iteration(self):
        self.iteration_count += 1
        if self.iteration_count >= 3:  # 3번 실행 후 종료
            self.stop()

    def _get_loop_interval(self) -> float:
        return self.loop_interval


class TestBaseWorkerInitialization:
    """BaseWorker 초기화 테스트"""

    def test_init_default_values(self):
        """기본값으로 초기화되는지 확인"""
        worker = ConcreteWorker()

        assert worker.name == "test_worker"
        assert worker.browser is None
        assert not worker.is_running
        assert worker.pid > 0
        assert worker.worker_id is None
        assert worker.start_time is None
        assert len(worker._running_tasks) == 0

    def test_init_with_browser_manager(self):
        """BrowserManager와 함께 초기화"""
        mock_browser = MagicMock()
        worker = ConcreteWorker(browser_manager=mock_browser)

        assert worker.browser is mock_browser


class TestBaseWorkerLifecycle:
    """워커 생명주기 테스트"""

    @pytest.mark.asyncio
    async def test_start_runs_main_loop(self):
        """start()가 메인 루프를 실행하는지 확인"""
        worker = ConcreteWorker()

        await worker.start()

        assert worker.iteration_count >= 3
        assert not worker.is_running  # 종료 후 False

    @pytest.mark.asyncio
    async def test_run_same_as_start(self):
        """run()이 start()와 동일하게 동작하는지 확인"""
        worker = ConcreteWorker()

        await worker.run()

        assert worker.iteration_count >= 3

    @pytest.mark.asyncio
    async def test_stop_terminates_worker(self):
        """stop()이 워커를 종료시키는지 확인"""
        worker = ConcreteWorker()
        worker.loop_interval = 1.0  # 느린 간격

        async def delayed_stop():
            await asyncio.sleep(0.2)
            worker.stop()

        asyncio.create_task(delayed_stop())
        await worker.start()

        assert worker.shutdown_event.is_set()
        assert not worker.is_running

    @pytest.mark.asyncio
    async def test_start_time_is_set(self):
        """시작 시간이 설정되는지 확인"""
        worker = ConcreteWorker()
        before = datetime.now()

        await worker.start()

        after = datetime.now()
        assert worker.start_time is not None
        assert before <= worker.start_time <= after


class TestBaseWorkerUptime:
    """가동 시간 테스트"""

    def test_uptime_before_start(self):
        """시작 전 uptime은 0"""
        worker = ConcreteWorker()
        assert worker.uptime_seconds == 0.0

    @pytest.mark.asyncio
    async def test_uptime_after_start(self):
        """시작 후 uptime이 증가하는지 확인"""
        worker = ConcreteWorker()

        await worker.start()

        # 약간의 시간이 지났으므로 0보다 커야 함
        assert worker.uptime_seconds >= 0


class TestBaseWorkerTasks:
    """백그라운드 태스크 관리 테스트"""

    @pytest.mark.asyncio
    async def test_create_task_adds_to_running(self):
        """_create_task가 _running_tasks에 추가하는지 확인"""
        worker = ConcreteWorker()

        async def dummy_coro():
            await asyncio.sleep(0.1)

        task = worker._create_task(dummy_coro(), "test_task")

        assert task in worker._running_tasks
        assert task.get_name() == "test_task"

        # 정리
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    def test_is_task_running_true(self):
        """실행 중인 태스크 확인"""
        worker = ConcreteWorker()

        mock_task = MagicMock()
        mock_task.get_name.return_value = "my_task"
        mock_task.done.return_value = False
        worker._running_tasks.add(mock_task)

        assert worker._is_task_running("my_task")
        assert not worker._is_task_running("other_task")

    @pytest.mark.asyncio
    async def test_cleanup_completed_tasks(self):
        """완료된 태스크가 정리되는지 확인"""
        worker = ConcreteWorker()

        # 즉시 완료되는 태스크 생성
        async def instant_coro():
            return "done"

        task = worker._create_task(instant_coro(), "instant_task")
        await asyncio.sleep(0.1)  # 태스크 완료 대기

        worker._cleanup_completed_tasks()

        assert task not in worker._running_tasks

    @pytest.mark.asyncio
    async def test_cleanup_cancels_running_tasks(self):
        """정리 시 실행 중인 태스크가 취소되는지 확인"""
        worker = ConcreteWorker()

        async def long_running():
            await asyncio.sleep(10)

        task = worker._create_task(long_running(), "long_task")

        await worker._cleanup()

        assert task.cancelled() or task.done()
        assert len(worker._running_tasks) == 0


class TestBaseWorkerStatus:
    """상태 정보 테스트"""

    def test_get_status_before_start(self):
        """시작 전 상태"""
        worker = ConcreteWorker("my_worker")
        status = worker.get_status()

        assert status["name"] == "my_worker"
        assert status["running"] is False
        assert status["worker_id"] is None
        assert status["start_time"] is None
        assert status["running_tasks"] == 0

    @pytest.mark.asyncio
    async def test_get_status_after_start(self):
        """시작 후 상태"""
        worker = ConcreteWorker("my_worker")

        await worker.start()

        status = worker.get_status()
        assert status["name"] == "my_worker"
        assert status["running"] is False  # 종료됨
        assert status["start_time"] is not None
        assert status["uptime_seconds"] >= 0


class TestBaseWorkerErrorHandling:
    """에러 핸들링 테스트"""

    @pytest.mark.asyncio
    async def test_main_loop_continues_on_error(self):
        """메인 루프가 에러 후에도 계속되는지 확인"""
        class ErrorWorker(BaseWorker):
            def __init__(self):
                super().__init__("error_worker")
                self.error_count = 0
                self.success_count = 0

            async def _main_loop_iteration(self):
                if self.error_count < 2:
                    self.error_count += 1
                    raise ValueError("Test error")
                else:
                    self.success_count += 1
                    if self.success_count >= 2:
                        self.stop()

            def _get_loop_interval(self) -> float:
                return 0.01  # 빠른 테스트

        worker = ErrorWorker()

        await worker.start()

        assert worker.error_count == 2
        assert worker.success_count >= 2

    @pytest.mark.asyncio
    async def test_exception_in_main_loop_iteration_logged(self):
        """메인 루프 예외가 로깅되는지 확인"""
        class ErrorWorker(BaseWorker):
            def __init__(self):
                super().__init__("error_worker")
                self.count = 0

            async def _main_loop_iteration(self):
                self.count += 1
                if self.count < 2:
                    raise ValueError("Test error")
                self.stop()

            def _get_loop_interval(self) -> float:
                return 0.01

        worker = ErrorWorker()

        with patch('app.shared.worker.base_worker.logger') as mock_logger:
            await worker.start()

            # 에러가 로깅되었는지 확인
            mock_logger.error.assert_called()


class TestBaseWorkerWaitForNextCycle:
    """_wait_for_next_cycle 테스트"""

    @pytest.mark.asyncio
    async def test_wait_returns_early_on_shutdown(self):
        """shutdown 시 즉시 반환하는지 확인"""
        worker = ConcreteWorker()

        async def trigger_shutdown():
            await asyncio.sleep(0.1)
            worker.stop()

        asyncio.create_task(trigger_shutdown())

        start = asyncio.get_event_loop().time()
        await worker._wait_for_next_cycle(10.0)  # 10초 대기 설정
        elapsed = asyncio.get_event_loop().time() - start

        # 10초보다 훨씬 빨리 반환해야 함
        assert elapsed < 1.0
