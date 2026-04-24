from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from app.models import TaskSchedule
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


class ArchiveRotationScheduler(ScheduleHandler):
    target_type = TaskSchedule.TARGET_TYPE_ARCHIVE_ROTATION

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

        logger.info("[%s] archive_rotation 실행 시간 도래: schedule_id=%s", ctx.worker_name, schedule.id)
        if svc.has_active_run(schedule.id):
            logger.info("[%s] 이미 활성 실행 존재, 스킵", ctx.worker_name)
            return None

        return start_claimed_run(
            schedule=schedule,
            svc=svc,
            ctx=ctx,
            task_name_prefix="archive_rotation",
            config_snapshot={},
        )

    async def execute(self, schedule: TaskSchedule, claimed: ClaimedRun, ctx: WorkerContext) -> HandlerRunOutcome:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, self._rotate_archives)
        rotated = result.get("rotated", 0)
        return HandlerRunOutcome(
            collected_count=rotated,
            saved_count=rotated,
            stop_reason="completed",
            config_snapshot_patch=result,
        )

    @staticmethod
    def _rotate_archives() -> dict:
        from scripts.services.rotate_archive_files import rotate

        return rotate(apply=True)
