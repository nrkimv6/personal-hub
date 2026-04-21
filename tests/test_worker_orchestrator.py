"""
WorkerOrchestrator 및 관련 컴포넌트 테스트.

테스트 방법론:
- RIGHT-BICEP (결과, 경계, 역관계, 교차검증, 에러, 성능)
- CORRECT (일관성, 순서, 범위, 참조, 존재, 카디널리티, 시간)

테스트 범위:
- WorkerOrchestrator 초기화/종료
- 워커 등록/관리
- 예외 처리 계층
- 재시작 로직
"""
import asyncio
from pathlib import Path
import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock

from app.core.config import settings as core_settings
from app.worker import orchestrator as orchestrator_mod
from app.worker.orchestrator import WorkerOrchestrator, WorkerState
from app.shared.worker.base_worker import BaseWorker
from app.shared.worker.exceptions import (
    WorkerError, WorkerCriticalError, WorkerRecoverableError,
    BrowserError, TabOperationTimeout, BrowserOperationError, BrowserRecoveryFailed
)


class DummyWorker(BaseWorker):
    """테스트용 더미 워커."""

    def __init__(self, name="dummy", should_fail=False, fail_count=0):
        super().__init__(name, browser_manager=None)
        self.should_fail = should_fail
        self.fail_count = fail_count
        self.iteration_count = 0
        self.max_iterations = 3

    def _get_loop_interval(self) -> float:
        return 0.1

    async def _main_loop_iteration(self):
        self.iteration_count += 1
        if self.should_fail and self.iteration_count <= self.fail_count:
            raise Exception(f"Simulated failure #{self.iteration_count}")
        if self.iteration_count >= self.max_iterations:
            self.stop()


# ============================================================
# RIGHT: Are the results right?
# ============================================================

class TestOrchestratorResults:
    """결과 정확성 테스트."""

    def test_worker_state_enum_values(self):
        """WorkerState enum 값 확인."""
        assert WorkerState.PENDING.value == "pending"
        assert WorkerState.RUNNING.value == "running"
        assert WorkerState.STOPPED.value == "stopped"
        assert WorkerState.ERROR.value == "error"
        assert WorkerState.FAILED.value == "failed"

    def test_orchestrator_initialization(self):
        """오케스트레이터 초기화 상태 확인."""
        orchestrator = WorkerOrchestrator()

        assert orchestrator.browser_manager is None
        assert orchestrator.workers == {}
        assert orchestrator.tasks == {}
        assert orchestrator.worker_states == {}
        assert not orchestrator._initialized
        assert not orchestrator.shutdown_event.is_set()

    def test_register_worker(self):
        """워커 등록 결과 확인."""
        orchestrator = WorkerOrchestrator()
        worker = DummyWorker("test_worker")

        orchestrator.register_worker("test", worker)

        assert "test" in orchestrator.workers
        assert orchestrator.workers["test"] is worker
        assert orchestrator.worker_states["test"] == WorkerState.PENDING

    def test_get_status(self):
        """상태 조회 결과 확인."""
        orchestrator = WorkerOrchestrator()

        status = orchestrator.get_status()

        assert "initialized" in status
        assert "shutdown_requested" in status
        assert "worker_count" in status
        assert "worker_states" in status
        assert status["worker_count"] == 0


# ============================================================
# BOUNDARY: Are the boundary conditions correct?
# ============================================================

class TestOrchestratorBoundary:
    """경계 조건 테스트."""

    def test_register_duplicate_worker_raises(self):
        """중복 워커 등록 시 예외 발생."""
        orchestrator = WorkerOrchestrator()
        worker1 = DummyWorker("worker1")
        worker2 = DummyWorker("worker2")

        orchestrator.register_worker("test", worker1)

        with pytest.raises(ValueError, match="이미 등록되어 있습니다"):
            orchestrator.register_worker("test", worker2)

    @pytest.mark.asyncio
    async def test_run_without_initialization_raises(self):
        """초기화 없이 실행 시 예외 발생."""
        orchestrator = WorkerOrchestrator()
        worker = DummyWorker()
        orchestrator.register_worker("test", worker)

        with pytest.raises(RuntimeError, match="초기화되지 않았습니다"):
            await orchestrator.run()

    @pytest.mark.asyncio
    async def test_run_with_no_workers_logs_warning(self):
        """워커 없이 실행 시 경고."""
        orchestrator = WorkerOrchestrator()
        orchestrator._initialized = True  # Mock initialization

        # Should not raise, just return
        await orchestrator.run()

    def test_max_restarts_constant(self):
        """재시작 제한 상수 확인."""
        assert WorkerOrchestrator.MAX_RESTARTS == 5
        assert WorkerOrchestrator.RESTART_WINDOW == 300
        assert WorkerOrchestrator.SHUTDOWN_TIMEOUT == 30


# ============================================================
# INVERSE: Can you check inverse relationships?
# ============================================================

class TestOrchestratorInverse:
    """역관계 테스트."""

    @pytest.mark.asyncio
    async def test_shutdown_sets_event(self):
        """종료 시 이벤트 설정 확인."""
        orchestrator = WorkerOrchestrator()
        orchestrator._initialized = True

        assert not orchestrator.shutdown_event.is_set()
        await orchestrator.shutdown()
        assert orchestrator.shutdown_event.is_set()

    @pytest.mark.asyncio
    async def test_context_manager_initializes_and_cleans(self):
        """컨텍스트 매니저 진입/종료 확인."""
        with patch.object(WorkerOrchestrator, 'initialize', new_callable=AsyncMock) as mock_init:
            with patch.object(WorkerOrchestrator, 'shutdown', new_callable=AsyncMock) as mock_shutdown:
                async with WorkerOrchestrator() as orchestrator:
                    mock_init.assert_called_once()

                mock_shutdown.assert_called_once()


# ============================================================
# CROSS-CHECK: Can you cross-check results?
# ============================================================

class TestOrchestratorCrossCheck:
    """교차 검증 테스트."""

    def test_worker_count_matches_dict_length(self):
        """워커 수와 딕셔너리 길이 일치."""
        orchestrator = WorkerOrchestrator()

        for i in range(5):
            worker = DummyWorker(f"worker_{i}")
            orchestrator.register_worker(f"worker_{i}", worker)

        assert len(orchestrator.workers) == 5
        assert len(orchestrator.worker_states) == 5
        assert orchestrator.get_status()["worker_count"] == 5

    @pytest.mark.asyncio
    async def test_run_starts_orphan_detector_with_cleanup_callback(self):
        """run()이 stale test worktree 정리용 OrphanDetector를 올바르게 wiring한다."""
        orchestrator = WorkerOrchestrator()
        orchestrator._initialized = True
        orchestrator.register_worker("test", DummyWorker("test"))

        class FakeDetector:
            instances = []

            def __init__(self, registry, repo_root=None, cleanup_callback=None):
                self.registry = registry
                self.repo_root = repo_root
                self.cleanup_callback = cleanup_callback
                self.run_args = None
                FakeDetector.instances.append(self)

            async def run_periodic(self, interval, memory_check_interval):
                self.run_args = (interval, memory_check_interval)
                return None

        with patch.object(orchestrator_mod, "OrphanDetector", FakeDetector), \
             patch.object(
                 WorkerOrchestrator,
                 "_run_worker_with_supervision",
                 new=AsyncMock(return_value=None),
             ), \
             patch.object(core_settings, "PROCESS_SCAN_INTERVAL", 12.5), \
             patch.object(core_settings, "MEMORY_PRESSURE_CHECK_INTERVAL", 3.5):
            await orchestrator.run()
            if orchestrator._orphan_task is not None:
                await orchestrator._orphan_task

        assert len(FakeDetector.instances) == 1
        detector = FakeDetector.instances[0]
        assert detector.repo_root == Path(orchestrator_mod.__file__).resolve().parents[2]
        assert detector.run_args == (12.5, 3.5)
        assert detector.cleanup_callback.__self__ is orchestrator
        assert (
            detector.cleanup_callback.__func__
            is WorkerOrchestrator._cleanup_orphan_test_worktrees
        )

    @pytest.mark.asyncio
    async def test_cleanup_orphan_test_worktrees_delegates_to_worktree_service(self):
        """cleanup helper는 cleanup_worktrees(..., dry_run=False)만 호출해야 한다."""
        orchestrator = WorkerOrchestrator()
        expected = {"results": [{"branch": "runner/t-stale-001", "status": "removed"}]}

        with patch(
            "app.modules.dev_runner.services.worktree_service.cleanup_worktrees",
            new=AsyncMock(return_value=expected),
        ) as mock_cleanup:
            result = await orchestrator._cleanup_orphan_test_worktrees(
                ["runner/t-stale-001"]
            )

        assert result == expected
        mock_cleanup.assert_awaited_once_with(
            ["runner/t-stale-001"],
            dry_run=False,
            repo_root=Path(orchestrator_mod.__file__).resolve().parents[2],
        )


# ============================================================
# ERROR: Can you force error conditions?
# ============================================================

class TestOrchestratorError:
    """에러 조건 테스트."""

    def test_worker_critical_error_attributes(self):
        """WorkerCriticalError 속성 확인."""
        error = WorkerCriticalError(
            "Test error",
            worker_name="test_worker",
            consecutive_errors=5
        )

        assert str(error) == "Test error"
        assert error.worker_name == "test_worker"
        assert error.consecutive_errors == 5

    def test_tab_operation_timeout_attributes(self):
        """TabOperationTimeout 속성 확인."""
        error = TabOperationTimeout("Timeout occurred", timeout=30.0)

        assert "30.0s" in str(error)
        assert error.timeout == 30.0

    def test_browser_recovery_failed_attributes(self):
        """BrowserRecoveryFailed 속성 확인."""
        error = BrowserRecoveryFailed("Recovery failed", attempts=3)

        assert "attempts: 3" in str(error)
        assert error.attempts == 3

    def test_browser_operation_error_with_original(self):
        """BrowserOperationError 원본 예외 포함."""
        original = ValueError("Original error")
        error = BrowserOperationError("Browser error", original_error=original)

        assert error.original_error is original


# ============================================================
# CORRECT: Conformance, Ordering, Range, Reference, Existence, Cardinality, Time
# ============================================================

class TestBaseWorkerCorrect:
    """BaseWorker CORRECT 테스트."""

    def test_conformance_abstract_methods(self):
        """추상 메서드 구현 확인."""
        # BaseWorker is abstract - cannot instantiate directly
        with pytest.raises(TypeError):
            BaseWorker("test", None)

    def test_ordering_error_counts(self):
        """에러 카운트 순서 확인."""
        worker = DummyWorker()

        assert worker._consecutive_errors == 0
        worker._consecutive_errors += 1
        assert worker._consecutive_errors == 1

    def test_range_max_consecutive_errors(self):
        """연속 에러 범위 확인."""
        worker = DummyWorker()

        assert worker._max_consecutive_errors == 10
        assert worker.DEFAULT_MAX_CONSECUTIVE_ERRORS == 10
        assert worker.DEFAULT_ERROR_BACKOFF_SECONDS == 5

    def test_reference_browser_manager(self):
        """브라우저 매니저 참조 확인."""
        mock_browser = Mock()
        worker = DummyWorker()
        worker.browser = mock_browser

        assert worker.browser is mock_browser

    def test_existence_shutdown_event(self):
        """종료 이벤트 존재 확인."""
        worker = DummyWorker()

        assert worker.shutdown_event is not None
        assert isinstance(worker.shutdown_event, asyncio.Event)
        assert not worker.shutdown_event.is_set()

    def test_cardinality_running_tasks(self):
        """실행 중 태스크 카디널리티."""
        worker = DummyWorker()

        assert len(worker._running_tasks) == 0
        assert isinstance(worker._running_tasks, set)

    @pytest.mark.asyncio
    async def test_time_uptime_seconds(self):
        """가동 시간 계산."""
        worker = DummyWorker()

        # Before start
        assert worker.uptime_seconds == 0.0

        # After start
        from datetime import datetime
        worker.start_time = datetime.now()
        await asyncio.sleep(0.1)

        assert worker.uptime_seconds >= 0.1


# ============================================================
# Integration Tests (minimal, mocked)
# ============================================================

class TestOrchestratorIntegration:
    """통합 테스트 (최소한, 모킹)."""

    @pytest.mark.asyncio
    async def test_worker_lifecycle_basic(self):
        """워커 기본 생명주기."""
        worker = DummyWorker("lifecycle_test")
        worker.max_iterations = 2

        # Start and stop
        task = asyncio.create_task(worker.run())
        await asyncio.sleep(0.5)

        # Worker should have stopped itself
        assert not worker.is_running or task.done()

        if not task.done():
            worker.stop()
            await asyncio.wait_for(task, timeout=1.0)

    @pytest.mark.asyncio
    async def test_safe_execute_success(self):
        """_safe_execute 성공 케이스."""
        worker = DummyWorker()

        async def success_task():
            return "success"

        result = await worker._safe_execute("test_task", success_task)
        assert result is True

    @pytest.mark.asyncio
    async def test_safe_execute_failure(self):
        """_safe_execute 실패 케이스."""
        worker = DummyWorker()

        async def failing_task():
            raise ValueError("Test error")

        result = await worker._safe_execute("test_task", failing_task)
        assert result is False
        assert worker._task_error_counts["test_task"] == 1

    @pytest.mark.asyncio
    async def test_request_shutdown(self):
        """종료 요청 처리."""
        worker = DummyWorker()

        assert not worker.shutdown_event.is_set()
        worker.request_shutdown()
        assert worker.shutdown_event.is_set()


# ============================================================
# Exception Hierarchy Tests
# ============================================================

class TestExceptionHierarchy:
    """예외 계층 구조 테스트."""

    def test_worker_error_hierarchy(self):
        """워커 에러 상속 관계."""
        assert issubclass(WorkerCriticalError, WorkerError)
        assert issubclass(WorkerRecoverableError, WorkerError)
        assert issubclass(WorkerError, Exception)

    def test_browser_error_hierarchy(self):
        """브라우저 에러 상속 관계."""
        assert issubclass(TabOperationTimeout, BrowserError)
        assert issubclass(BrowserOperationError, BrowserError)
        assert issubclass(BrowserRecoveryFailed, BrowserError)
        assert issubclass(BrowserError, Exception)

    def test_worker_recoverable_error_retry_after(self):
        """복구 가능 에러 재시도 시간."""
        error = WorkerRecoverableError("Recoverable", retry_after=10.0)
        assert error.retry_after == 10.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
