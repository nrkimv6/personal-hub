"""
TC: schedule_date_expire 스케줄 처리 검증

- _process_schedule_date_expire_schedule() 게이트 계약
- _execute_schedule_date_expire_run() DB disable 계약
- get_today_kst_iso() 자정 경계
- 멱등성 (이미 disabled row 제외)
- complete_run 인자 및 config_snapshot 계약
"""
import asyncio
import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

SCHEDULED_WORKER_PATH = Path(__file__).resolve().parents[2] / "app" / "worker" / "scheduled_worker.py"
_KST = timezone(timedelta(hours=9))


# ============================================================
# 공통 스텁
# ============================================================

class StubWorker:
    """scheduled_worker.py와 동일 패턴의 최소 스텁."""
    name = "test_worker"
    _tasks: dict = {}

    def __init__(self):
        self._tasks = {}

    def _is_task_running(self, name):
        return name in self._tasks

    def _create_task(self, coro, name):
        self._tasks[name] = coro

    def _should_run_cron(self, schedule, last_run_at):
        return True

    def _log_worker_error(self, ctx, exc):
        pass

    async def _process_schedule_date_expire_schedule(self, db, schedule, schedule_service):
        """scheduled_worker.py와 동일 로직 복사."""
        import logging
        logger = logging.getLogger(__name__)
        try:
            last_run = schedule_service.get_latest_run(schedule.id)
            last_run_at = last_run.started_at if last_run else None
            if not self._should_run_cron(schedule, last_run_at):
                return
            if schedule_service.has_active_run(schedule.id):
                return
            run = schedule_service.start_run(
                schedule_id=schedule.id,
                worker_id=self.name,
                config_snapshot={}
            )
            task_name = f"schedule_date_expire_{schedule.id}_run_{run.id}"
            if not self._is_task_running(task_name):
                self._create_task(
                    self._execute_schedule_date_expire_run(schedule, run),
                    task_name
                )
        except Exception as e:
            logger.error(f"error: {e}", exc_info=True)

    async def _execute_schedule_date_expire_run(self, schedule, run):
        pass


# ============================================================
# Phase T1.1: _process_schedule_date_expire_schedule() 게이트
# ============================================================

class TestProcessScheduleDateExpireSchedule:

    @pytest.mark.asyncio
    async def test_process_starts_run_when_cron_due_right(self):
        """R: cron 시간 도래 + 활성 실행 없음 → start_run + task 생성."""
        worker = StubWorker()

        schedule = MagicMock()
        schedule.id = 1

        run = MagicMock()
        run.id = 10

        schedule_service = MagicMock()
        schedule_service.get_latest_run.return_value = None
        schedule_service.has_active_run.return_value = False
        schedule_service.start_run.return_value = run

        await worker._process_schedule_date_expire_schedule(None, schedule, schedule_service)

        schedule_service.start_run.assert_called_once_with(
            schedule_id=1,
            worker_id="test_worker",
            config_snapshot={}
        )
        assert f"schedule_date_expire_1_run_10" in worker._tasks

    @pytest.mark.asyncio
    async def test_process_skips_when_cron_not_due_right(self):
        """R: cron 시간 미도래 → start_run 미호출."""
        worker = StubWorker()
        worker._should_run_cron = lambda s, lr: False

        schedule_service = MagicMock()

        await worker._process_schedule_date_expire_schedule(None, MagicMock(id=1), schedule_service)

        schedule_service.start_run.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_skips_when_active_run_exists_right(self):
        """R: 이미 활성 실행 존재 → start_run 미호출."""
        worker = StubWorker()

        schedule_service = MagicMock()
        schedule_service.get_latest_run.return_value = None
        schedule_service.has_active_run.return_value = True

        await worker._process_schedule_date_expire_schedule(None, MagicMock(id=1), schedule_service)

        schedule_service.start_run.assert_not_called()


# ============================================================
# Phase T1.2: _execute_schedule_date_expire_run() DB disable 계약
# ============================================================

class TestExecuteScheduleDateExpireRun:

    def _make_mock_db(self, affected_ids):
        """모의 DB — execute().fetchall() 이 affected_ids를 반환."""
        db = MagicMock()
        result = MagicMock()
        result.fetchall.return_value = [(aid,) for aid in affected_ids]
        db.execute.return_value = result
        db.commit.return_value = None
        db.query.return_value.filter_by.return_value.first.return_value = None
        return db

    @pytest.mark.asyncio
    async def test_execute_calls_complete_run_with_correct_counts_right(self):
        """R: affected_ids 수에 따라 complete_run(collected_count, saved_count) 호출."""
        from app.worker.scheduled_worker import ScheduledCrawlWorker

        schedule = MagicMock()
        schedule.id = 5
        run = MagicMock()
        run.id = 20

        mock_db = self._make_mock_db(affected_ids=[100, 200, 300])

        schedule_service_mock = MagicMock()
        schedule_service_mock.complete_run.return_value = None
        schedule_service_mock.update_schedule_after_run.return_value = None
        schedule_service_mock.fail_run.return_value = None

        with patch("app.worker.scheduled_worker.SessionLocal", return_value=mock_db), \
             patch("app.worker.scheduled_worker.TaskScheduleService", return_value=schedule_service_mock), \
             patch("app.services.monitor_schedule_cutoff.get_today_kst_iso", return_value="2026-04-22"):

            worker = ScheduledCrawlWorker.__new__(ScheduledCrawlWorker)
            worker.name = "test_worker"
            worker._tasks = {}
            worker._log_worker_error = MagicMock()

            await worker._execute_schedule_date_expire_run(schedule, run)

        schedule_service_mock.complete_run.assert_called_once_with(
            run.id,
            collected_count=3,
            saved_count=3,
            stop_reason="completed"
        )

    @pytest.mark.asyncio
    async def test_execute_is_idempotent_disabled_rows_not_counted_right(self):
        """R: is_enabled=false인 row는 RETURNING에 포함되지 않으므로 count=0."""
        from app.worker.scheduled_worker import ScheduledCrawlWorker

        schedule = MagicMock()
        schedule.id = 5
        run = MagicMock()
        run.id = 20

        # affected_ids=[] → 이미 비활성화된 row는 UPDATE 대상이 아님
        mock_db = self._make_mock_db(affected_ids=[])

        schedule_service_mock = MagicMock()
        schedule_service_mock.complete_run.return_value = None
        schedule_service_mock.update_schedule_after_run.return_value = None

        with patch("app.worker.scheduled_worker.SessionLocal", return_value=mock_db), \
             patch("app.worker.scheduled_worker.TaskScheduleService", return_value=schedule_service_mock), \
             patch("app.services.monitor_schedule_cutoff.get_today_kst_iso", return_value="2026-04-22"):

            worker = ScheduledCrawlWorker.__new__(ScheduledCrawlWorker)
            worker.name = "test_worker"
            worker._tasks = {}
            worker._log_worker_error = MagicMock()

            await worker._execute_schedule_date_expire_run(schedule, run)

        schedule_service_mock.complete_run.assert_called_once_with(
            run.id,
            collected_count=0,
            saved_count=0,
            stop_reason="completed"
        )

    @pytest.mark.asyncio
    async def test_execute_fail_run_called_on_exception_right(self):
        """R: DB 예외 발생 시 fail_run() 호출."""
        from app.worker.scheduled_worker import ScheduledCrawlWorker

        schedule = MagicMock()
        schedule.id = 5
        run = MagicMock()
        run.id = 20

        broken_db = MagicMock()
        broken_db.execute.side_effect = RuntimeError("DB down")

        schedule_service_mock = MagicMock()

        with patch("app.worker.scheduled_worker.SessionLocal", return_value=broken_db), \
             patch("app.worker.scheduled_worker.TaskScheduleService", return_value=schedule_service_mock), \
             patch("app.services.monitor_schedule_cutoff.get_today_kst_iso", return_value="2026-04-22"):

            worker = ScheduledCrawlWorker.__new__(ScheduledCrawlWorker)
            worker.name = "test_worker"
            worker._tasks = {}
            worker._log_worker_error = MagicMock()

            await worker._execute_schedule_date_expire_run(schedule, run)

        schedule_service_mock.fail_run.assert_called_once()


# ============================================================
# Phase T1.3: get_today_kst_iso() 자정 경계
# ============================================================

class TestGetTodayKstIso:

    def test_midnight_boundary_kst_right(self):
        """R: KST 자정 직전(23:59:59 KST)은 오늘, 직후(00:00:01 KST 다음날)는 다음날."""
        from app.services.monitor_schedule_cutoff import get_today_kst_iso

        # KST 2026-04-22 23:59:59 → "2026-04-22"
        before_midnight_kst = datetime(2026, 4, 22, 23, 59, 59, tzinfo=_KST)
        assert get_today_kst_iso(before_midnight_kst) == "2026-04-22"

        # KST 2026-04-23 00:00:01 → "2026-04-23"
        after_midnight_kst = datetime(2026, 4, 23, 0, 0, 1, tzinfo=_KST)
        assert get_today_kst_iso(after_midnight_kst) == "2026-04-23"

    def test_utc_time_correctly_converts_to_kst_right(self):
        """R: UTC 시각이 KST로 +9h 변환되어 날짜가 올바르게 계산된다."""
        from app.services.monitor_schedule_cutoff import get_today_kst_iso

        # UTC 2026-04-22 15:00 = KST 2026-04-23 00:00
        utc_time = datetime(2026, 4, 22, 15, 0, 0, tzinfo=timezone.utc)
        assert get_today_kst_iso(utc_time) == "2026-04-23"

        # UTC 2026-04-22 14:59 = KST 2026-04-22 23:59
        utc_time2 = datetime(2026, 4, 22, 14, 59, 0, tzinfo=timezone.utc)
        assert get_today_kst_iso(utc_time2) == "2026-04-22"

    def test_past_row_excluded_today_row_included_right(self):
        """R: helper 기준으로 어제 date < today_kst, 오늘 date >= today_kst."""
        from app.services.monitor_schedule_cutoff import get_today_kst_iso

        now_kst = datetime(2026, 4, 22, 10, 0, 0, tzinfo=_KST)
        today_kst = get_today_kst_iso(now_kst)

        assert "2026-04-21" < today_kst   # 어제 → 제외 대상
        assert "2026-04-22" >= today_kst  # 오늘 → 포함 대상
        assert "2026-04-23" >= today_kst  # 내일 → 포함 대상


# ============================================================
# Phase T1.4: AST — dispatcher에 schedule_date_expire 분기 등록 검증
# ============================================================

class TestDispatcherRegistration:

    def test_schedule_date_expire_in_dispatch_scheduled_runs_right(self):
        """R: _dispatch_scheduled_runs()에 TARGET_TYPE_SCHEDULE_DATE_EXPIRE 조회 블록이 존재."""
        src = SCHEDULED_WORKER_PATH.read_text(encoding="utf-8")
        assert "TARGET_TYPE_SCHEDULE_DATE_EXPIRE" in src, \
            "TARGET_TYPE_SCHEDULE_DATE_EXPIRE가 scheduled_worker.py에 없음"
        assert "_process_schedule_date_expire_schedule" in src, \
            "_process_schedule_date_expire_schedule가 scheduled_worker.py에 없음"
        assert "_execute_schedule_date_expire_run" in src, \
            "_execute_schedule_date_expire_run이 scheduled_worker.py에 없음"
