from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.models import ServiceAccount, TaskSchedule, TaskScheduleRun
from app.modules.instagram.services.crawl_service import CrawlService
from app.modules.instagram.services.crawler import InstagramCrawler
from app.modules.instagram.services.scheduler import InstagramScheduler
from app.services.task_schedule_service import TaskScheduleService
from app.utils.error_utils import format_error_message
from app.worker.schedule_handler_base import (
    ClaimedRun,
    HandlerRunOutcome,
    ScheduleExecutionSpec,
    ScheduleHandler,
    WorkerContext,
    load_schedule_value,
    start_claimed_run,
)
from app.worker.schedule_time_utils import parse_time_windows

if TYPE_CHECKING:
    from playwright.async_api import Page
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class InstagramFeedScheduler(ScheduleHandler):
    target_type = TaskSchedule.TARGET_TYPE_INSTAGRAM_FEED

    def claim_run(
        self,
        db: "Session",
        schedule: TaskSchedule,
        svc: TaskScheduleService,
        ctx: WorkerContext,
    ) -> ClaimedRun | None:
        config = schedule.get_target_config()
        service_account_id = config.get("service_account_id")
        if not service_account_id:
            return None

        schedule_value = load_schedule_value(schedule)
        scheduler = InstagramScheduler(
            daily_runs=schedule_value.get("daily_runs", 3),
            time_windows=parse_time_windows(schedule_value.get("time_windows", [])),
        )
        health = svc.get_schedule_health(schedule)
        if health.get("health") == "error":
            logger.warning(
                "[%s] Instagram schedule health error: schedule_id=%s reason=%s "
                "candidate_count=%s daily_runs=%s time_windows_count=%s",
                ctx.worker_name,
                schedule.id,
                health.get("reason"),
                health.get("candidate_count"),
                health.get("daily_runs"),
                health.get("time_window_count"),
            )
        deferred_run = svc.get_oldest_deferred_run(schedule.id)
        if deferred_run and not svc.has_active_run(schedule.id):
            claimed = svc.claim_deferred_run(deferred_run.id, worker_id=ctx.worker_name)
            if claimed:
                logger.info(
                    "[%s] deferred Instagram slot claimed: schedule_id=%s run_id=%s",
                    ctx.worker_name,
                    schedule.id,
                    claimed.id,
                )
                return ClaimedRun(
                    run_id=claimed.id,
                    schedule_id=schedule.id,
                    task_name=f"instagram_schedule_{schedule.id}_run_{claimed.id}",
                )

        last_run = svc.get_latest_run(schedule.id)
        last_run_time = last_run.started_at if last_run else None

        due_run_time = scheduler.get_due_run_time(
            last_run=last_run_time,
            now=ctx.now,
        )
        if due_run_time is None:
            next_due = scheduler.get_next_run_time(now=ctx.now)
            logger.debug(
                "[%s] Instagram schedule not due: schedule_id=%s next_due=%s last_run=%s "
                "daily_runs=%s time_windows_count=%s",
                ctx.worker_name,
                schedule.id,
                next_due.isoformat() if next_due else None,
                last_run_time.isoformat() if last_run_time else None,
                schedule_value.get("daily_runs", 3),
                len(schedule_value.get("time_windows", [])),
            )
            return None

        logger.info(
            "[%s] 스케줄 실행 시간 도래: schedule_id=%s, scheduled_for=%s",
            ctx.worker_name,
            schedule.id,
            due_run_time.isoformat(),
        )
        if svc.is_slot_claimed(schedule.id, due_run_time):
            logger.info(
                "[%s] 이미 claim된 Instagram slot: schedule_id=%s, scheduled_for=%s",
                ctx.worker_name,
                schedule.id,
                due_run_time.isoformat(),
            )
            return None

        config_snapshot = dict(config)
        config_snapshot.update(
            {
                "scheduled_for": due_run_time.isoformat(),
                "schedule_params": {
                    "daily_runs": schedule_value.get("daily_runs", 3),
                    "time_windows": schedule_value.get("time_windows", []),
                    "min_interval_hours": config.get("min_interval_hours"),
                },
            }
        )

        if svc.has_active_run(schedule.id):
            svc.get_or_create_deferred_run(
                schedule_id=schedule.id,
                scheduled_for=due_run_time,
                worker_id=ctx.worker_name,
                config_snapshot=config_snapshot,
            )
            logger.info("[%s] 활성 실행 존재, due slot deferred 보존", ctx.worker_name)
            return None

        return start_claimed_run(
            schedule=schedule,
            svc=svc,
            ctx=ctx,
            task_name_prefix="instagram_schedule",
            config_snapshot=config_snapshot,
        )

    async def execute(
        self,
        spec: ScheduleExecutionSpec,
        claimed: ClaimedRun,
        ctx: WorkerContext,
    ) -> HandlerRunOutcome:
        config = spec.target_config
        service_account_id = config.get("service_account_id")
        if not service_account_id:
            raise RuntimeError("service_account_id 없음")
        if ctx.execute_with_tab is None:
            raise RuntimeError("Instagram handler requires execute_with_tab context")

        db = ctx.db_factory()
        max_retries = 3
        retry_count = 0
        try:
            crawl_service = CrawlService(db)
            schedule_obj = db.query(TaskSchedule).filter_by(id=spec.schedule_id).first()
            run_obj = db.query(TaskScheduleRun).filter_by(id=claimed.run_id).first()
            if not schedule_obj or not run_obj:
                raise RuntimeError("Instagram schedule/run not found")

            while retry_count <= max_retries:
                try:
                    account = db.query(ServiceAccount).filter(ServiceAccount.id == service_account_id).first()
                    if not account:
                        logger.warning(
                            "[%s] 계정 없음: service_account_id=%s",
                            ctx.worker_name,
                            service_account_id,
                        )
                        raise RuntimeError("계정을 찾을 수 없음")

                    if ctx.update_worker_state:
                        ctx.update_worker_state("crawling", account.identifier)

                    outcome = await ctx.execute_with_tab(
                        callback=self._crawl_feed_with_tab,
                        service_account_id=account.id,
                        operation_timeout=3600.0,
                        schedule=schedule_obj,
                        run=run_obj,
                        account=account,
                        db=db,
                        crawl_service=crawl_service,
                        ctx=ctx,
                    )
                    if outcome is not None:
                        return outcome
                except Exception as exc:
                    if (
                        ctx.is_browser_closed_error
                        and ctx.is_browser_closed_error(exc)
                        and retry_count < max_retries
                    ):
                        retry_count += 1
                        logger.warning(
                            "[%s] 브라우저 closed 에러 감지, 재시도 (%s/%s): %s",
                            ctx.worker_name,
                            retry_count,
                            max_retries,
                            exc,
                        )
                        if ctx.reset_browser_manager:
                            await ctx.reset_browser_manager()
                        continue
                    raise RuntimeError(format_error_message(exc)) from exc

            raise RuntimeError("Instagram 피드 크롤링 재시도 초과")
        finally:
            if ctx.update_worker_state:
                ctx.update_worker_state("idle")
            db.close()

    async def _crawl_feed_with_tab(
        self,
        tab: "Page",
        schedule: TaskSchedule,
        run: TaskScheduleRun,
        account: ServiceAccount,
        db: "Session",
        crawl_service: CrawlService,
        ctx: WorkerContext,
    ) -> HandlerRunOutcome:
        logger.info("[%s] 인스타그램 피드 페이지로 이동 중...", ctx.worker_name)
        await tab.goto("https://www.instagram.com/", wait_until="domcontentloaded")
        await tab.wait_for_timeout(2000)
        logger.info("[%s] 인스타그램 페이지 로드 완료: %s", ctx.worker_name, tab.url)

        is_logged_in = await self._is_logged_in(tab)
        if not is_logged_in:
            account.is_logged_in = False
            db.commit()
            logger.warning("[%s] Instagram 로그인 필요: account=%s", ctx.worker_name, account.identifier)
            raise RuntimeError("Instagram 로그인 필요")

        account.is_logged_in = True
        db.commit()

        crawler = InstagramCrawler(tab)
        logger.info("[%s] InstagramCrawler 생성 완료, 크롤링 시작...", ctx.worker_name)

        crawl_run = await crawl_service.run_crawl(
            crawler=crawler,
            service_account_id=account.id,
            schedule_run_id=run.id,
        )
        if ctx.update_worker_state:
            ctx.update_worker_state("crawling", account.identifier, run.id)

        crawl_success = crawl_run.status == TaskScheduleRun.STATUS_COMPLETED
        logger.info(
            "[%s] 크롤링 완료: success=%s, collected=%s, new=%s",
            ctx.worker_name,
            crawl_success,
            crawl_run.collected_count,
            crawl_run.saved_count,
        )

        if not crawl_success:
            raise RuntimeError(crawl_run.error_message or "크롤링 실패")

        return HandlerRunOutcome(
            collected_count=crawl_run.collected_count,
            saved_count=crawl_run.saved_count,
            stop_reason=crawl_run.stop_reason,
        )

    async def _is_logged_in(self, page: "Page") -> bool:
        try:
            login_button = await page.query_selector('a[href="/accounts/login/"]')
            if login_button:
                return False

            login_indicators = [
                'a[href*="/direct/inbox/"]',
                'svg[aria-label="홈"]',
                'svg[aria-label="Home"]',
                "article",
            ]
            for selector in login_indicators:
                elem = await page.query_selector(selector)
                if elem:
                    return True

            return False
        except Exception as exc:
            logger.warning("Instagram 로그인 상태 확인 실패: %s", exc)
            return False
