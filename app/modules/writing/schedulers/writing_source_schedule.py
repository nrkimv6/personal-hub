from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.models import TaskSchedule
from app.modules.writing.services.writing_service import WritingService
from app.worker.schedule_handler_base import (
    ClaimedRun,
    HandlerRunOutcome,
    ScheduleExecutionSpec,
    ScheduleHandler,
    WorkerContext,
    claim_pending_manual_run,
    start_claimed_run,
)
from app.worker.schedule_time_utils import build_time_window_scheduler
from app.utils.error_utils import format_error_message

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class WritingSourceScheduler(ScheduleHandler):
    target_type = TaskSchedule.TARGET_TYPE_WRITING_SOURCE_COLLECT

    def claim_run(
        self,
        db: "Session",
        schedule: TaskSchedule,
        svc,
        ctx: WorkerContext,
    ) -> ClaimedRun | None:
        claimed = claim_pending_manual_run(db, schedule, svc, ctx, "writing_source")
        if claimed:
            logger.info("[%s] 수동 Writing Source 수집 태스크 시작: run_id=%s", ctx.worker_name, claimed.run_id)
            return claimed

        config = schedule.get_target_config()
        scheduler = build_time_window_scheduler(config, default_daily_runs=1)
        last_run = svc.get_latest_run(schedule.id)
        last_run_time = last_run.started_at if last_run else None
        min_interval = config.get("min_interval_hours", 20)
        if not scheduler.should_run_now(last_run=last_run_time, min_interval_hours=min_interval):
            return None

        logger.info("[%s] Writing Source 수집 스케줄 실행 시간 도래: schedule_id=%s", ctx.worker_name, schedule.id)
        if svc.has_active_run(schedule.id):
            logger.info("[%s] 이미 활성 실행 존재, 스킵", ctx.worker_name)
            return None

        return start_claimed_run(
            schedule=schedule,
            svc=svc,
            ctx=ctx,
            task_name_prefix="writing_source",
            config_snapshot=config,
        )

    async def execute(self, spec: ScheduleExecutionSpec, claimed: ClaimedRun, ctx: WorkerContext) -> HandlerRunOutcome:
        config = spec.target_config
        db = ctx.db_factory()
        try:
            writing_service = WritingService(db)
            if ctx.update_worker_state:
                ctx.update_worker_state("collecting", "writing_sources")

            total_collected = 0
            errors: list[str] = []

            if config.get("collect_rss", True):
                try:
                    logger.info("[%s] RSS 수집 시작...", ctx.worker_name)
                    rss_result = await writing_service.collect_from_feeds(
                        min_length=config.get("rss_min_length", 300),
                        max_length=config.get("rss_max_length", 3000),
                    )
                    total_collected += rss_result.get("collected", 0)
                    logger.info("[%s] RSS 수집 완료: %s건", ctx.worker_name, rss_result.get("collected", 0))
                except Exception as exc:
                    errors.append(f"RSS: {format_error_message(exc)}")
                    logger.error("[%s] RSS 수집 오류: %s", ctx.worker_name, exc)

            if config.get("collect_wikisource", True):
                try:
                    logger.info("[%s] 위키문헌 수집 시작...", ctx.worker_name)
                    wiki_result = await writing_service.collect_from_wikisource(
                        min_length=config.get("wiki_min_length", 200),
                        max_length=config.get("wiki_max_length", 10000),
                    )
                    total_collected += wiki_result.get("collected", 0)
                    logger.info("[%s] 위키문헌 수집 완료: %s건", ctx.worker_name, wiki_result.get("collected", 0))
                except Exception as exc:
                    errors.append(f"Wikisource: {format_error_message(exc)}")
                    logger.error("[%s] 위키문헌 수집 오류: %s", ctx.worker_name, exc)

            if config.get("collect_search", False):
                try:
                    logger.info("[%s] 검색 API 수집 시작...", ctx.worker_name)
                    search_result = await writing_service.collect_from_searches(
                        min_length=config.get("search_min_length", 100),
                        max_length=config.get("search_max_length", 5000),
                        max_queries=config.get("search_max_queries", 10),
                    )
                    total_collected += search_result.get("collected", 0)
                    logger.info("[%s] 검색 API 수집 완료: %s건", ctx.worker_name, search_result.get("collected", 0))
                except Exception as exc:
                    errors.append(f"Search: {format_error_message(exc)}")
                    logger.error("[%s] 검색 API 수집 오류: %s", ctx.worker_name, exc)

            if errors and total_collected == 0:
                raise RuntimeError("; ".join(errors))

            stop_reason = "completed"
            if errors:
                stop_reason = f"partial_success: {'; '.join(errors)}"

            return HandlerRunOutcome(
                collected_count=total_collected,
                saved_count=total_collected,
                stop_reason=stop_reason,
            )
        finally:
            if ctx.update_worker_state:
                ctx.update_worker_state("idle")
            db.close()
