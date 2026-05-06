from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from app.core.database import is_connection_error
from app.models import TaskSchedule, TaskScheduleRun
from app.modules.writing.worker.topic_extract_worker import TopicExtractWorker
from app.worker.schedule_handler_base import (
    ClaimedRun,
    HandlerRunOutcome,
    ScheduleExecutionSpec,
    ScheduleHandler,
    WorkerContext,
    claim_pending_manual_run,
    start_claimed_run,
)
from app.worker.schedule_time_utils import should_run_simple_interval

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class TopicExtractScheduler(ScheduleHandler):
    target_type = TaskSchedule.TARGET_TYPE_TOPIC_EXTRACT

    def claim_run(
        self,
        db: "Session",
        schedule: TaskSchedule,
        svc,
        ctx: WorkerContext,
    ) -> ClaimedRun | None:
        claimed = claim_pending_manual_run(db, schedule, svc, ctx, "topic_extract")
        if claimed:
            logger.info("[%s] 수동 Topic Extract 태스크 시작: run_id=%s", ctx.worker_name, claimed.run_id)
            return claimed

        config = schedule.get_target_config()
        last_run = svc.get_latest_run(schedule.id)
        last_run_time = last_run.started_at if last_run else None
        min_interval = config.get("min_interval_hours", 20)
        if not should_run_simple_interval(last_run_time, min_interval):
            return None

        logger.info("[%s] Topic Extract 스케줄 실행 시간 도래: schedule_id=%s", ctx.worker_name, schedule.id)
        if svc.has_active_run(schedule.id):
            logger.info("[%s] 이미 활성 실행 존재, 스킵", ctx.worker_name)
            return None

        return start_claimed_run(
            schedule=schedule,
            svc=svc,
            ctx=ctx,
            task_name_prefix="topic_extract",
            config_snapshot=config,
        )

    async def execute(self, spec: ScheduleExecutionSpec, claimed: ClaimedRun, ctx: WorkerContext) -> HandlerRunOutcome:
        if ctx.update_worker_state:
            ctx.update_worker_state("extracting", "topics")

        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                self._run_topic_job_sync,
                spec.schedule_id,
                claimed.run_id,
                ctx.db_factory,
                ctx.worker_name,
            )
            if result.get("error"):
                raise RuntimeError(result["error"])
            return HandlerRunOutcome(
                collected_count=result.get("total", 0),
                saved_count=result.get("extracted", 0),
                stop_reason="completed",
            )
        finally:
            if ctx.update_worker_state:
                ctx.update_worker_state("idle")

    @staticmethod
    def _run_topic_job_sync(schedule_id: int, run_id: int, db_factory, worker_name: str) -> dict:
        db = db_factory()
        try:
            schedule = db.query(TaskSchedule).filter_by(id=schedule_id).first()
            run = db.query(TaskScheduleRun).filter_by(id=run_id).first()
            if not schedule or not run:
                return {"error": "Topic extract schedule/run not found"}
            worker = TopicExtractWorker(db)
            return worker.run(schedule, run)
        except Exception as exc:
            if is_connection_error(exc):
                raise
            logger.error("[%s] TopicExtractWorker 실행 오류: %s", worker_name, exc, exc_info=True)
            return {"error": str(exc)}
        finally:
            db.close()
