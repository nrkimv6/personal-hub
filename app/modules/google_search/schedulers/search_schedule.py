from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from app.models import TaskSchedule, TaskScheduleRun
from app.models.google_search import GoogleSavedSearch, GoogleSearchQueue
from app.modules.google_search.services.queue_service import enqueue_google_search
from app.modules.instagram.services.scheduler import InstagramScheduler
from app.services.task_schedule_service import TaskScheduleService
from app.utils.error_utils import format_error_message
from app.worker.schedule_handler_base import (
    ClaimedRun,
    HandlerRunOutcome,
    ScheduleExecutionSpec,
    ScheduleHandler,
    WorkerContext,
    start_claimed_run,
)
from app.worker.schedule_time_utils import parse_time_windows

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class GoogleSearchScheduler(ScheduleHandler):
    target_type = TaskSchedule.TARGET_TYPE_GOOGLE_SEARCH

    def claim_run(
        self,
        db: "Session",
        schedule: TaskSchedule,
        svc: TaskScheduleService,
        ctx: WorkerContext,
    ) -> ClaimedRun | None:
        config = schedule.get_target_config()
        saved_search_id = config.get("saved_search_id")
        if not saved_search_id:
            logger.warning("[%s] saved_search_id 없음: schedule_id=%s", ctx.worker_name, schedule.id)
            return None

        scheduler = InstagramScheduler(
            daily_runs=config.get("daily_runs", 1),
            time_windows=None if not config.get("time_windows") else None,
        )
        if config.get("time_windows", []):
            scheduler = InstagramScheduler(
                daily_runs=config.get("daily_runs", 1),
                time_windows=parse_time_windows(config.get("time_windows", [])),
            )

        last_run = svc.get_latest_run(schedule.id)
        last_run_time = last_run.started_at if last_run else None
        if not scheduler.should_run_now(
            last_run=last_run_time,
            min_interval_hours=config.get("min_interval_hours", 1),
        ):
            return None

        logger.info("[%s] Google 검색 스케줄 실행 시간 도래: schedule_id=%s", ctx.worker_name, schedule.id)
        if svc.has_active_run(schedule.id):
            logger.info("[%s] 이미 활성 실행 존재, 스킵", ctx.worker_name)
            return None

        return start_claimed_run(
            schedule=schedule,
            svc=svc,
            ctx=ctx,
            task_name_prefix="google_schedule",
            config_snapshot=config,
        )

    async def execute(
        self,
        spec: ScheduleExecutionSpec,
        claimed: ClaimedRun,
        ctx: WorkerContext,
    ) -> HandlerRunOutcome:
        config = spec.target_config
        saved_search_id = config.get("saved_search_id")
        if not saved_search_id:
            raise RuntimeError("saved_search_id 없음")

        db = ctx.db_factory()
        try:
            saved_search = db.query(GoogleSavedSearch).filter_by(id=saved_search_id).first()
            if not saved_search:
                logger.warning(
                    "[%s] 저장된 검색 없음: saved_search_id=%s",
                    ctx.worker_name,
                    saved_search_id,
                )
                raise RuntimeError("저장된 검색을 찾을 수 없습니다")

            if ctx.update_worker_state:
                ctx.update_worker_state("searching", saved_search.name)

            search_id = str(uuid.uuid4())
            queue_item = GoogleSearchQueue(
                search_id=search_id,
                query=saved_search.query,
                date_filter=saved_search.date_filter,
                max_pages=saved_search.max_pages or 1,
                service_account_id=saved_search.service_account_id,
                search_params=saved_search.search_params,
                saved_search_id=saved_search_id,
                schedule_id=spec.schedule_id,
                status=GoogleSearchQueue.STATUS_QUEUED,
            )
            db.add(queue_item)
            db.commit()
            db.refresh(queue_item)

            status = await enqueue_google_search(queue_item, db)
            logger.info(
                "[%s] Google 검색 큐에 추가: search_id=%s, query=%s, schedule_id=%s, mode=%s, status=%s",
                ctx.worker_name,
                search_id,
                saved_search.query,
                spec.schedule_id,
                "redis" if status == GoogleSearchQueue.STATUS_QUEUED else "sqlite",
                status,
            )

            return HandlerRunOutcome(
                collected_count=0,
                saved_count=0,
                stop_reason=TaskScheduleRun.STOP_REASON_SEARCH_QUEUED,
                config_snapshot_patch={"search_id": search_id},
            )
        except Exception as exc:
            raise RuntimeError(format_error_message(exc)) from exc
        finally:
            if ctx.update_worker_state:
                ctx.update_worker_state("idle")
            db.close()
