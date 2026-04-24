from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from sqlalchemy import text as sa_text

from app.models import TaskSchedule
from app.services import monitor_schedule_cutoff
from app.services.task_schedule_service import TaskScheduleService
from app.worker.schedule_handler_base import (
    ClaimedRun,
    HandlerRunOutcome,
    ScheduleHandler,
    WorkerContext,
    start_claimed_run,
)
from app.worker.schedule_time_utils import should_run_cron

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def get_today_kst_iso(*args, **kwargs):
    """Late-bind cutoff helper so local and service-level patches both apply."""
    return monitor_schedule_cutoff.get_today_kst_iso(*args, **kwargs)


class ScheduleDateExpireScheduler(ScheduleHandler):
    target_type = TaskSchedule.TARGET_TYPE_SCHEDULE_DATE_EXPIRE

    def claim_run(
        self,
        db: "Session",
        schedule: TaskSchedule,
        svc: TaskScheduleService,
        ctx: WorkerContext,
    ) -> ClaimedRun | None:
        last_run = svc.get_latest_run(schedule.id)
        last_run_at = last_run.started_at if last_run else None
        if not should_run_cron(schedule, last_run_at):
            return None

        logger.info("[%s] schedule_date_expire 실행 시간 도래: schedule_id=%s", ctx.worker_name, schedule.id)
        if svc.has_active_run(schedule.id):
            logger.info("[%s] 이미 활성 실행 존재, 스킵", ctx.worker_name)
            return None

        return start_claimed_run(
            schedule=schedule,
            svc=svc,
            ctx=ctx,
            task_name_prefix="schedule_date_expire",
            config_snapshot={},
        )

    async def execute(self, schedule: TaskSchedule, claimed: ClaimedRun, ctx: WorkerContext) -> HandlerRunOutcome:
        loop = asyncio.get_event_loop()
        today_kst, affected_ids = await loop.run_in_executor(None, self._expire_schedules, ctx.db_factory)
        count = len(affected_ids)
        return HandlerRunOutcome(
            collected_count=count,
            saved_count=count,
            stop_reason="completed",
            config_snapshot_patch={
                "cutoff_date": today_kst,
                "affected_count": count,
                "affected_ids": affected_ids[:500],
            },
        )

    @staticmethod
    def _expire_schedules(db_factory) -> tuple[str, list[int]]:
        db = db_factory()
        try:
            today_kst = get_today_kst_iso()
            result = db.execute(
                sa_text(
                    """
                    UPDATE monitor_schedules
                    SET is_enabled = false,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE is_enabled = true
                      AND date < :today_kst
                    RETURNING id
                    """
                ),
                {"today_kst": today_kst},
            )
            affected_ids = [row[0] for row in result.fetchall()]
            db.commit()
            return today_kst, affected_ids
        finally:
            db.close()
