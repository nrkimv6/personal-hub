from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from app.models import TaskSchedule
from app.worker.schedule_handler_base import (
    ClaimedRun,
    HandlerRunOutcome,
    ScheduleHandler,
    WorkerContext,
    claim_pending_manual_run,
    start_claimed_run,
)
from app.worker.schedule_time_utils import should_run_simple_interval

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class KeywordAnalysisScheduler(ScheduleHandler):
    target_type = TaskSchedule.TARGET_TYPE_KEYWORD_ANALYSIS

    def claim_run(
        self,
        db: "Session",
        schedule: TaskSchedule,
        svc,
        ctx: WorkerContext,
    ) -> ClaimedRun | None:
        claimed = claim_pending_manual_run(db, schedule, svc, ctx, "keyword_analysis")
        if claimed:
            logger.info("[%s] 수동 Keyword Analysis 태스크 시작: run_id=%s", ctx.worker_name, claimed.run.id)
            return claimed

        config = schedule.get_target_config()
        last_run = svc.get_latest_run(schedule.id)
        last_run_time = last_run.started_at if last_run else None
        min_interval = config.get("min_interval_hours", 168)
        if not should_run_simple_interval(last_run_time, min_interval):
            return None

        logger.info("[%s] Keyword Analysis 스케줄 실행 시간 도래: schedule_id=%s", ctx.worker_name, schedule.id)
        if svc.has_active_run(schedule.id):
            logger.info("[%s] 이미 활성 실행 존재, 스킵", ctx.worker_name)
            return None

        return start_claimed_run(
            schedule=schedule,
            svc=svc,
            ctx=ctx,
            task_name_prefix="keyword_analysis",
            config_snapshot=config,
        )

    async def execute(self, schedule: TaskSchedule, claimed: ClaimedRun, ctx: WorkerContext) -> HandlerRunOutcome:
        config = schedule.get_target_config()
        if ctx.update_worker_state:
            ctx.update_worker_state("analyzing", "keywords")

        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                self._run_keyword_job_sync,
                config,
                ctx.db_factory,
                ctx.worker_name,
            )
            if result.get("error"):
                raise RuntimeError(result["error"])

            total_keywords = result.get("saved_keywords")
            if total_keywords is None:
                total_keywords = result.get("new_keywords", 0) + result.get("updated_keywords", 0)

            return HandlerRunOutcome(
                collected_count=result.get("total_sources") or result.get("new_sources", 0),
                saved_count=total_keywords,
                stop_reason="completed",
            )
        finally:
            if ctx.update_worker_state:
                ctx.update_worker_state("idle")

    @staticmethod
    def _run_keyword_job_sync(config: dict, db_factory, worker_name: str) -> dict:
        db = db_factory()
        try:
            from app.modules.writing.services.keyword_analyzer import KeywordAnalyzer

            analyzer = KeywordAnalyzer(db)
            mode = config.get("mode", "incremental")
            min_freq = config.get("min_freq", 3)
            min_length = config.get("min_length", 2)

            if mode == "full":
                return analyzer.analyze_all(min_freq=min_freq, min_length=min_length)
            return analyzer.analyze_incremental(min_freq=min_freq, min_length=min_length)
        except Exception as exc:
            logger.error("[%s] KeywordAnalyzer 실행 오류: %s", worker_name, exc, exc_info=True)
            return {"error": str(exc)}
        finally:
            db.close()
