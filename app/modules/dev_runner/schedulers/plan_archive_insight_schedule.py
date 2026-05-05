from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from app.models import TaskSchedule
from app.modules.dev_runner.services.plan_archive_insight_service import (
    PlanArchiveInsightBatchQuery,
    PlanArchiveInsightService,
)
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


class PlanArchiveInsightBatchScheduler(ScheduleHandler):
    target_type = TaskSchedule.TARGET_TYPE_PLAN_ARCHIVE_INSIGHT_BATCH

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
        if svc.has_active_run(schedule.id):
            logger.info("[%s] plan archive insight batch already active, skip", ctx.worker_name)
            return None
        return start_claimed_run(
            schedule=schedule,
            svc=svc,
            ctx=ctx,
            task_name_prefix="plan_archive_insight_batch",
            config_snapshot=schedule.get_target_config(),
        )

    async def execute(self, schedule: TaskSchedule, claimed: ClaimedRun, ctx: WorkerContext) -> HandlerRunOutcome:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            self._enqueue_in_db,
            ctx.db_factory,
            schedule.get_target_config(),
        )
        queued = 1 if result.get("queued") else 0
        stop_reason = result.get("reason") or "queued"
        return HandlerRunOutcome(
            collected_count=queued,
            saved_count=queued,
            stop_reason=stop_reason,
            config_snapshot_patch=result,
        )

    @staticmethod
    def _enqueue_in_db(db_factory, config: dict | None = None) -> dict:
        db = db_factory()
        try:
            config = config or {}
            days = int(config.get("days") or 30)
            range_end = datetime.now()
            range_start = range_end - timedelta(days=max(1, days))
            query = PlanArchiveInsightBatchQuery(
                date_from=range_start,
                date_to=range_end,
                grouping=str(config.get("grouping") or "category"),
                category=config.get("category"),
                path=config.get("path"),
                limit=int(config.get("limit") or 20),
                token_budget=int(config.get("token_budget") or 3000),
            )
            return PlanArchiveInsightService(db).preview_or_enqueue(
                query,
                apply=True,
                force=bool(config.get("force")),
                provider=config.get("provider"),
                model=config.get("model"),
                requested_by="scheduler",
            )
        finally:
            db.close()
