from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from app.models import TaskSchedule
from app.modules.dev_runner.services.plan_archive_execution_service import PlanArchiveExecutionService
from app.services.task_schedule_service import TaskScheduleService
from app.worker.schedule_handler_base import (
    ClaimedRun,
    HandlerRunOutcome,
    ScheduleExecutionSpec,
    ScheduleHandler,
    WorkerContext,
    start_claimed_run,
)
from app.worker.schedule_time_utils import should_run_cron

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)
DEFAULT_MAX_BACKFILL_PER_RUN = 25


class PlanArchiveScheduler(ScheduleHandler):
    target_type = TaskSchedule.TARGET_TYPE_PLAN_ARCHIVE_ANALYZE

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

        logger.info("[%s] plan_archive_analyze 실행 시간 도래: schedule_id=%s", ctx.worker_name, schedule.id)
        if svc.has_active_run(schedule.id):
            logger.info("[%s] 이미 활성 실행 존재, 스킵", ctx.worker_name)
            return None

        return start_claimed_run(
            schedule=schedule,
            svc=svc,
            ctx=ctx,
            task_name_prefix="plan_archive_analyze",
            config_snapshot={},
        )

    async def execute(self, spec: ScheduleExecutionSpec, claimed: ClaimedRun, ctx: WorkerContext) -> HandlerRunOutcome:
        loop = asyncio.get_event_loop()
        target_config = spec.target_config
        import functools as _ft
        stats = await loop.run_in_executor(
            None,
            _ft.partial(
                self._enqueue_unprocessed_plans,
                ctx.db_factory,
                target_config,
                claimed.run_id,
            ),
        )
        count = stats["queued"]
        return HandlerRunOutcome(
            collected_count=count,
            saved_count=count,
            stop_reason="completed",
            config_snapshot_patch=stats,
        )

    @staticmethod
    def _get_max_backfill_per_run(target_config: dict | None) -> int:
        raw_value = (target_config or {}).get("max_backfill_per_run", DEFAULT_MAX_BACKFILL_PER_RUN)
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            return DEFAULT_MAX_BACKFILL_PER_RUN
        return value if value > 0 else DEFAULT_MAX_BACKFILL_PER_RUN

    @classmethod
    def _enqueue_unprocessed_plans(cls, db_factory, target_config: dict | None = None, schedule_run_id: int | None = None) -> dict:
        db = db_factory()
        try:
            return cls._enqueue_unprocessed_plans_in_session(db, target_config=target_config, schedule_run_id=schedule_run_id)
        finally:
            db.close()

    @classmethod
    def _enqueue_unprocessed_plans_in_session(cls, db: "Session", target_config: dict | None = None, schedule_run_id: int | None = None) -> dict:
        target_config = target_config or {}
        include_temp_records = target_config.get("include_temp_records") is True
        max_backfill_per_run = cls._get_max_backfill_per_run(target_config)
        stats = {
            "queued": 0,
            "skipped_temp": 0,
            "skipped_empty": 0,
            "skipped_active_request": 0,
            "remaining_real_unprocessed": 0,
        }
        try:
            stats.update(
                PlanArchiveExecutionService(db).enqueue_unprocessed(
                    include_temp_records=include_temp_records,
                    max_backfill_per_run=max_backfill_per_run,
                    trigger_source="schedule:plan_archive_analyze",
                    source_schedule_run_id=schedule_run_id,
                )
            )
            if stats["queued"] > 0 or stats["skipped_empty"] > 0 or stats["skipped_active_job"] > 0:
                db.commit()
            return stats
        except Exception:
            db.rollback()
            raise
