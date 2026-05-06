from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from app.models import TaskSchedule
from app.modules.reports.services.report_service import ReportService
from app.worker.schedule_handler_base import (
    ClaimedRun,
    HandlerRunOutcome,
    ScheduleExecutionSpec,
    ScheduleHandler,
    WorkerContext,
    start_claimed_run,
)
from app.worker.schedule_time_utils import build_time_window_scheduler

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class ReportScheduler(ScheduleHandler):
    target_type = TaskSchedule.TARGET_TYPE_REPORT

    def claim_run(
        self,
        db: "Session",
        schedule: TaskSchedule,
        svc,
        ctx: WorkerContext,
    ) -> ClaimedRun | None:
        config = schedule.get_target_config()
        scheduler = build_time_window_scheduler(config, default_daily_runs=1)
        last_run = svc.get_latest_run(schedule.id)
        last_run_time = last_run.started_at if last_run else None
        min_interval = config.get("min_interval_hours", 24)
        if not scheduler.should_run_now(last_run=last_run_time, min_interval_hours=min_interval):
            return None

        logger.info("[%s] Report 스케줄 실행 시간 도래: schedule_id=%s", ctx.worker_name, schedule.id)
        if svc.has_active_run(schedule.id):
            logger.info("[%s] 이미 활성 실행 존재, 스킵", ctx.worker_name)
            return None

        return start_claimed_run(
            schedule=schedule,
            svc=svc,
            ctx=ctx,
            task_name_prefix="report",
            config_snapshot=config,
        )

    async def execute(self, spec: ScheduleExecutionSpec, claimed: ClaimedRun, ctx: WorkerContext) -> HandlerRunOutcome:
        config = spec.target_config
        db = ctx.db_factory()
        try:
            if ctx.update_worker_state:
                ctx.update_worker_state("generating", f"report_{spec.schedule_id}")

            report_service = ReportService(db)
            period = config.get("period", "daily")
            period_end = datetime.now()
            if period == "daily":
                period_start = period_end - timedelta(days=1)
            elif period == "weekly":
                period_start = period_end - timedelta(weeks=1)
            else:
                period_start = period_end - timedelta(days=30)

            llm_request = report_service.request_report(
                report_type=config.get("report_type", "daily_summary"),
                period_start=period_start,
                period_end=period_end,
                config=config,
            )
            return HandlerRunOutcome(
                collected_count=1,
                saved_count=1,
                stop_reason=f"report_requested_id_{llm_request.id}",
            )
        finally:
            if ctx.update_worker_state:
                ctx.update_worker_state("idle")
            db.close()
