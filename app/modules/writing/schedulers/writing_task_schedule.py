from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from app.core.database import is_connection_error
from app.models import TaskSchedule, TaskScheduleRun
from app.modules.writing.worker.writing_worker import WritingWorker
from app.worker.schedule_handler_base import (
    ClaimedRun,
    HandlerRunOutcome,
    ScheduleHandler,
    WorkerContext,
    start_claimed_run,
)
from app.worker.schedule_time_utils import build_time_window_scheduler

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class WritingTaskScheduler(ScheduleHandler):
    target_type = TaskSchedule.TARGET_TYPE_WRITING_TASK

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
        min_interval = config.get("min_interval_hours", 20)
        if not scheduler.should_run_now(last_run=last_run_time, min_interval_hours=min_interval):
            return None

        logger.info("[%s] Writing task 스케줄 실행 시간 도래: schedule_id=%s", ctx.worker_name, schedule.id)
        if svc.has_active_run(schedule.id):
            logger.info("[%s] 이미 활성 실행 존재, 스킵", ctx.worker_name)
            return None

        return start_claimed_run(
            schedule=schedule,
            svc=svc,
            ctx=ctx,
            task_name_prefix="writing_schedule",
            config_snapshot=config,
        )

    async def execute(self, schedule: TaskSchedule, claimed: ClaimedRun, ctx: WorkerContext) -> HandlerRunOutcome:
        if ctx.update_worker_state:
            ctx.update_worker_state("writing", f"schedule_{schedule.id}")

        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                self._run_writing_job_sync,
                schedule.id,
                claimed.run.id,
                ctx.db_factory,
                ctx.worker_name,
            )
            if result.get("error"):
                raise RuntimeError(result["error"])
            return HandlerRunOutcome(
                collected_count=result.get("total", 0),
                saved_count=result.get("success", 0),
                stop_reason="completed",
            )
        finally:
            if ctx.update_worker_state:
                ctx.update_worker_state("idle")

    @staticmethod
    def _run_writing_job_sync(
        schedule_id: int,
        run_id: int,
        db_factory,
        worker_name: str,
    ) -> dict:
        db = db_factory()
        try:
            schedule = db.query(TaskSchedule).filter_by(id=schedule_id).first()
            run = db.query(TaskScheduleRun).filter_by(id=run_id).first()
            if not schedule or not run:
                return {"error": "Writing task schedule/run not found"}
            worker = WritingWorker(db)
            return worker.run(schedule, run)
        except Exception as exc:
            if is_connection_error(exc):
                raise
            logger.error("[%s] WritingWorker 실행 오류: %s", worker_name, exc, exc_info=True)
            return {"error": str(exc)}
        finally:
            db.close()
