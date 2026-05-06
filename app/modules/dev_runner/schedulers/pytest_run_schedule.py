from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from app.models import TaskSchedule
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


class PytestRunScheduler(ScheduleHandler):
    target_type = TaskSchedule.TARGET_TYPE_PYTEST_RUN

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

        logger.info("[%s] pytest_run 실행 시간 도래: schedule_id=%s", ctx.worker_name, schedule.id)
        if svc.has_active_run(schedule.id):
            logger.info("[%s] 이미 활성 실행 존재, 스킵", ctx.worker_name)
            return None

        return start_claimed_run(
            schedule=schedule,
            svc=svc,
            ctx=ctx,
            task_name_prefix="pytest_run",
            config_snapshot=schedule.get_target_config(),
        )

    async def execute(self, spec: ScheduleExecutionSpec, claimed: ClaimedRun, ctx: WorkerContext) -> HandlerRunOutcome:
        config = spec.target_config
        if ctx.update_worker_state:
            ctx.update_worker_state("running_pytest", f"pytest_{spec.schedule_id}")

        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                self._run_pytest_sync,
                config,
                claimed.run_id,
                ctx.db_factory,
            )
            if result.get("error"):
                raise RuntimeError(result["error"])

            return HandlerRunOutcome(
                collected_count=result["total_tests"],
                saved_count=result["failed"] + result["errors"],
                stop_reason=f"pytest_run_id_{result['test_run_id']}",
            )
        finally:
            if ctx.update_worker_state:
                ctx.update_worker_state("idle")

    @staticmethod
    def _run_pytest_sync(config: dict, schedule_run_id: int, db_factory) -> dict:
        from app.services.pytest_runner_service import PytestRunnerService

        db = db_factory()
        try:
            runner = PytestRunnerService(db)
            test_path = config.get("test_path", "tests/")
            extra_args_raw = config.get("extra_args", [])
            extra_args = extra_args_raw if isinstance(extra_args_raw, list) else []
            timeout = config.get("timeout", 1800)

            test_run = runner.run_tests(
                test_path=test_path,
                extra_args=extra_args,
                timeout=timeout,
                triggered_by="scheduler",
                schedule_run_id=schedule_run_id,
            )

            if config.get("auto_fix_plan", True) and (test_run.failed + test_run.errors) > 0:
                provider = config.get("llm_provider")
                model = config.get("llm_model")
                if provider is None:
                    provider = config.get("provider")
                if model is None:
                    model = config.get("model")
                runner.create_fix_plan_requests(
                    test_run_id=test_run.id,
                    provider=provider,
                    model=model,
                )

            return {
                "test_run_id": test_run.id,
                "total_tests": test_run.total_tests,
                "failed": test_run.failed,
                "errors": test_run.errors,
            }
        finally:
            db.close()
