"""
TC: scheduled_worker QueuePool 세션 누수 방지
plan: docs/plan/2026-02-28_fix-queuepool-session-leak.md
"""
import asyncio
import pytest
from unittest.mock import MagicMock, patch, call


class TestDispatchScheduledRunsDbClose:
    """_dispatch_scheduled_runs()의 DB 세션 close 보장 검증"""

    def _make_worker(self):
        """ScheduledCrawlWorker 인스턴스를 의존성 없이 생성"""
        from app.worker.scheduled_worker import ScheduledCrawlWorker
        worker = ScheduledCrawlWorker.__new__(ScheduledCrawlWorker)
        worker.name = "scheduled_worker"
        return worker

    def test_right_db_closed_after_success(self):
        """R: 정상 실행 후 db.close() 호출 검증"""
        mock_db = MagicMock()
        mock_service = MagicMock()
        mock_service.get_schedules_by_type.return_value = []

        with patch("app.worker.scheduled_worker.SessionLocal", return_value=mock_db), \
             patch("app.worker.scheduled_worker.TaskScheduleService", return_value=mock_service):
            worker = self._make_worker()
            asyncio.get_event_loop().run_until_complete(worker._dispatch_scheduled_runs())

        mock_db.close.assert_called_once()

    def test_error_db_closed_after_exception(self):
        """E: 내부 예외 발생 시에도 db.close() 호출 검증"""
        mock_db = MagicMock()
        mock_service = MagicMock()
        mock_service.get_schedules_by_type.side_effect = RuntimeError("DB 오류")

        with patch("app.worker.scheduled_worker.SessionLocal", return_value=mock_db), \
             patch("app.worker.scheduled_worker.TaskScheduleService", return_value=mock_service):
            worker = self._make_worker()
            # 예외는 내부에서 catch되고 로깅 → 외부로 전파 안 됨
            asyncio.get_event_loop().run_until_complete(worker._dispatch_scheduled_runs())

        mock_db.close.assert_called_once()

    def test_perf_no_pool_leak_after_repeated_calls(self):
        """P: 루프 10회 반복 후 SessionLocal 호출 횟수 = close 횟수 (누수 없음)"""
        close_count = []
        open_count = []

        def make_mock_db():
            db = MagicMock()
            open_count.append(1)
            original_close = db.close
            def tracked_close():
                close_count.append(1)
            db.close = tracked_close
            return db

        mock_service = MagicMock()
        mock_service.get_schedules_by_type.return_value = []

        with patch("app.worker.scheduled_worker.SessionLocal", side_effect=make_mock_db), \
             patch("app.worker.scheduled_worker.TaskScheduleService", return_value=mock_service):
            worker = self._make_worker()
            for _ in range(10):
                asyncio.get_event_loop().run_until_complete(worker._dispatch_scheduled_runs())

        assert len(open_count) == 10, f"SessionLocal 호출 횟수: {len(open_count)}"
        assert len(close_count) == 10, f"db.close() 호출 횟수: {len(close_count)} (누수 발생!)"
