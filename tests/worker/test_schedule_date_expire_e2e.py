"""Phase T4 E2E: schedule_date_expire dispatcher/process/execute 계약 검증.

- AST/dispatch 등록 존재 검증
- _process_schedule_date_expire_schedule start_run → execute 계약
- has_active_run=True 스킵 계약
"""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

SCHEDULED_WORKER_PATH = Path(__file__).resolve().parents[2] / "app" / "worker" / "scheduled_worker.py"


# ============================================================
# T4.1: AST / dispatch 등록 E2E
# ============================================================

@pytest.mark.e2e
def test_e2e_schedule_date_expire_registered_in_dispatcher_right():
    """[E2E] scheduled_worker.py에 TARGET_TYPE_SCHEDULE_DATE_EXPIRE 분기와 메서드 쌍이 존재한다."""
    src = SCHEDULED_WORKER_PATH.read_text(encoding="utf-8")
    assert "TARGET_TYPE_SCHEDULE_DATE_EXPIRE" in src, \
        "TARGET_TYPE_SCHEDULE_DATE_EXPIRE가 scheduled_worker.py에 없음"
    assert "_process_schedule_date_expire_schedule" in src, \
        "_process_schedule_date_expire_schedule 메서드가 없음"
    assert "_execute_schedule_date_expire_run" in src, \
        "_execute_schedule_date_expire_run 메서드가 없음"


# ============================================================
# T4.2: start_run → execute → complete 경로 E2E
# ============================================================

class StubWorkerE2E:
    name = "test_worker"

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
        from app.worker.scheduled_worker import ScheduledCrawlWorker
        return await ScheduledCrawlWorker._process_schedule_date_expire_schedule(
            self, db, schedule, schedule_service
        )

    async def _execute_schedule_date_expire_run(self, schedule, run):
        pass


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_e2e_process_creates_task_on_start_run_right():
    """[E2E] cron due + active run 없음 → start_run 호출 후 task 생성."""
    worker = StubWorkerE2E()

    schedule = MagicMock()
    schedule.id = 1
    run = MagicMock()
    run.id = 10

    svc = MagicMock()
    svc.get_latest_run.return_value = None
    svc.has_active_run.return_value = False
    svc.start_run.return_value = run

    await worker._process_schedule_date_expire_schedule(None, schedule, svc)

    svc.start_run.assert_called_once_with(
        schedule_id=1,
        worker_id="test_worker",
        config_snapshot={},
    )
    assert "schedule_date_expire_1_run_10" in worker._tasks


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_e2e_process_skips_when_active_run_exists_right():
    """[E2E] has_active_run=True → start_run 미호출."""
    worker = StubWorkerE2E()

    svc = MagicMock()
    svc.get_latest_run.return_value = None
    svc.has_active_run.return_value = True

    await worker._process_schedule_date_expire_schedule(None, MagicMock(id=1), svc)

    svc.start_run.assert_not_called()
