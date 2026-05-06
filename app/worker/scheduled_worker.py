"""
스케줄 기반 크롤링 워커.

TaskSchedule 설정에 따라 정해진 시간에 도메인별 handler를 실행합니다.

실행 방법:
    python -m app.worker.scheduled_worker

주요 기능:
    - 활성 스케줄 조회 후 handler registry 기반 디스패치
    - run claim 이후 공통 task lifecycle 관리
    - 오래된 running 실행 정리
"""

from __future__ import annotations

import inspect
import logging
from datetime import datetime

from app.database import SessionLocal
from app.models import TaskScheduleRun
from app.modules.dev_runner.schedulers.archive_rotation_schedule import ArchiveRotationScheduler
from app.modules.dev_runner.schedulers.auto_dev_runner_schedule import AutoDevRunnerScheduler
from app.modules.dev_runner.schedulers.devguide_staleness_schedule import DevguideStalenessScheduler
from app.modules.dev_runner.schedulers.plan_archive_insight_schedule import PlanArchiveInsightBatchScheduler
from app.modules.dev_runner.schedulers.plan_archive_schedule import PlanArchiveScheduler
from app.modules.dev_runner.schedulers.pytest_run_schedule import PytestRunScheduler
from app.modules.dev_runner.schedulers.worktree_hygiene_schedule import WorktreeHygieneScheduler
from app.modules.google_search.schedulers.search_schedule import GoogleSearchScheduler
from app.modules.instagram.schedulers.feed_schedule import InstagramFeedScheduler
from app.modules.writing.schedulers.keyword_analysis_schedule import KeywordAnalysisScheduler
from app.modules.reports.schedulers.report_schedule import ReportScheduler
from app.modules.writing.schedulers.topic_extract_schedule import TopicExtractScheduler
from app.modules.writing.schedulers.writing_source_schedule import WritingSourceScheduler
from app.modules.writing.schedulers.writing_task_schedule import WritingTaskScheduler
from app.services.task_schedule_service import TaskScheduleService
from app.worker.crawl_worker_base import CrawlWorkerBase
from app.worker.schedule_handler_base import (
    ClaimedRun,
    HandlerRunOutcome,
    ScheduleHandler,
    WorkerContext,
    merge_config_snapshot,
)
from app.worker.schedulers.schedule_date_expire_schedule import ScheduleDateExpireScheduler

logger = logging.getLogger(__name__)


class ScheduledCrawlWorker(CrawlWorkerBase):
    """Thin orchestrator for schedule handler registry execution."""

    def __init__(self, check_interval: int = 30, browser_manager=None):
        super().__init__(
            name="scheduled_worker",
            worker_type="scheduled",
            browser_manager=browser_manager,
        )
        self.check_interval = check_interval
        self._worker_ctx = self._build_worker_ctx()
        self._handlers: list[ScheduleHandler] = self._build_handlers()

    def _build_worker_ctx(self) -> WorkerContext:
        return WorkerContext(
            worker_name=self.name,
            browser_manager=getattr(self, "browser", None),
            db_factory=SessionLocal,
            execute_with_tab=getattr(self, "execute_with_tab", None),
            update_worker_state=getattr(self, "_update_worker_state", None),
            is_browser_closed_error=getattr(self, "is_browser_closed_error", None),
            reset_browser_manager=getattr(self, "_reset_browser_manager", None),
        )

    def _get_worker_ctx(self) -> WorkerContext:
        ctx = getattr(self, "_worker_ctx", None)
        if ctx is None:
            ctx = self._build_worker_ctx()
            self._worker_ctx = ctx
        return ctx

    def _build_handlers(self) -> list[ScheduleHandler]:
        return [
            InstagramFeedScheduler(),
            GoogleSearchScheduler(),
            WritingTaskScheduler(),
            WritingSourceScheduler(),
            KeywordAnalysisScheduler(),
            TopicExtractScheduler(),
            ReportScheduler(),
            PytestRunScheduler(),
            PlanArchiveScheduler(),
            PlanArchiveInsightBatchScheduler(),
            DevguideStalenessScheduler(),
            ArchiveRotationScheduler(),
            ScheduleDateExpireScheduler(),
            AutoDevRunnerScheduler(),
            WorktreeHygieneScheduler(),
        ]

    def _get_loop_interval(self) -> float:
        return 1.0

    async def _main_loop_iteration(self):
        self._cleanup_completed_tasks()

        if not hasattr(self, "_last_stale_cleanup"):
            self._last_stale_cleanup = datetime.now()

        if (datetime.now() - self._last_stale_cleanup).total_seconds() >= 300:
            self._cleanup_stale_requests()
            self._last_stale_cleanup = datetime.now()

        await self._dispatch_scheduled_runs()

    def _cleanup_stale_requests(self):
        db = SessionLocal()
        try:
            schedule_service = TaskScheduleService(db)
            cleaned = schedule_service.cleanup_stale_runs(timeout_minutes=30)
            if cleaned > 0:
                logger.info("[%s] %s개의 오래된 running 실행 정리 완료", self.name, cleaned)
        except Exception as exc:
            logger.error("[%s] Stale run 정리 오류: %s", self.name, exc)
        finally:
            db.close()

    async def _dispatch_scheduled_runs(self) -> None:
        """Query active schedules per handler and enqueue claimed runs."""
        db = SessionLocal()
        try:
            schedule_service = TaskScheduleService(db)
            for handler in self._handlers:
                schedules = schedule_service.get_schedules_by_type(handler.target_type, enabled_only=True)
                for schedule in schedules:
                    try:
                        claimed = handler.claim_run(db, schedule, schedule_service, self._get_worker_ctx())
                        if claimed:
                            await self._schedule_claimed_run(handler, schedule, claimed)
                    except Exception as exc:
                        self._log_worker_error(f"{handler.target_type} claim_run", exc)
        except Exception as exc:
            self._log_worker_error("스케줄 디스패치", exc)
        finally:
            db.close()

    async def _schedule_claimed_run(
        self,
        handler: ScheduleHandler,
        schedule,
        claimed: ClaimedRun,
    ) -> None:
        """Create one background task per claimed run when not already running."""
        if self._is_task_running(claimed.task_name):
            logger.info("[%s] 이미 실행 중인 태스크 스킵: %s", self.name, claimed.task_name)
            return

        self._create_task(
            self._run_handler(handler, schedule, claimed),
            claimed.task_name,
        )
        logger.info(
            "[%s] %s 태스크 시작: run_id=%s",
            self.name,
            handler.target_type,
            claimed.run.id,
        )

    async def _run_handler(
        self,
        handler: ScheduleHandler,
        schedule,
        claimed: ClaimedRun,
    ) -> None:
        """Execute a handler and normalize complete/fail lifecycle updates."""
        completed = False
        try:
            maybe_outcome = handler.execute(schedule, claimed, self._get_worker_ctx())
            outcome = await maybe_outcome if inspect.isawaitable(maybe_outcome) else maybe_outcome
            if outcome is None:
                outcome = HandlerRunOutcome()

            db = SessionLocal()
            try:
                schedule_service = TaskScheduleService(db)
                schedule_service.complete_run(
                    claimed.run.id,
                    collected_count=outcome.collected_count,
                    saved_count=outcome.saved_count,
                    stop_reason=outcome.stop_reason,
                )
                completed = True

                config_patch = merge_config_snapshot(claimed.config_snapshot_patch, outcome.config_snapshot_patch)
                if config_patch:
                    run_obj = db.query(TaskScheduleRun).filter_by(id=claimed.run.id).first()
                    if run_obj:
                        run_obj.set_config_snapshot(
                            merge_config_snapshot(run_obj.get_config_snapshot(), config_patch)
                        )
                        db.commit()

                schedule_service.update_schedule_after_run(claimed.schedule_id)
            finally:
                db.close()
        except Exception as exc:
            self._log_worker_error(f"{handler.target_type} execute", exc)
            if not completed:
                db = SessionLocal()
                try:
                    TaskScheduleService(db).fail_run(claimed.run.id, error_message=str(exc))
                except Exception:
                    pass
                finally:
                    db.close()

    async def _reset_browser_manager(self) -> None:
        if self.browser and self.browser.is_initialized:
            await self.browser.cleanup()
            self._browser_initialized = False
