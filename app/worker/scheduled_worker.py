"""
스케줄 기반 크롤링 워커.

CrawlSchedule 설정에 따라 정해진 시간에 크롤링을 자동으로 수행합니다.

실행 방법:
    python -m app.worker.scheduled_worker

주요 기능:
    - 스케줄 설정에 따른 자동 피드 크롤링
    - TimeWindow 기반 실행 시간 관리
    - 최소 간격 제한 준수
    - Google 검색 스케줄 지원
"""
import asyncio
import logging
import uuid
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from app.worker.crawl_worker_base import CrawlWorkerBase
from app.database import SessionLocal
from app.models import ServiceAccount, CrawlSchedule, CrawlScheduleRun
from app.models.google_search import GoogleSearchQueue, GoogleSearchHistory, GoogleSavedSearch

from app.services.crawl_schedule_service import CrawlScheduleService
from app.modules.instagram.services.crawl_service import CrawlService
from app.utils.error_utils import format_error_message
from app.modules.instagram.services.scheduler import InstagramScheduler
from app.modules.instagram.services.crawler import InstagramCrawler
from app.modules.instagram.models.schemas import TimeWindow

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = logging.getLogger(__name__)


class ScheduledCrawlWorker(CrawlWorkerBase):
    """스케줄 기반 Instagram 피드 크롤링 워커.

    CrawlSchedule 설정에 따라 정해진 시간에
    자동으로 Instagram 피드를 크롤링합니다.

    Attributes:
        check_interval: 스케줄 확인 간격 (초)
    """

    def __init__(self, check_interval: int = 30, browser_manager=None):
        """ScheduledCrawlWorker 초기화.

        Args:
            check_interval: 스케줄 확인 간격 (초). 기본 30초.
            browser_manager: 외부에서 주입받을 BrowserManager (None이면 자체 생성)
        """
        super().__init__(
            name="scheduled_worker",
            worker_type="scheduled",
            browser_manager=browser_manager
        )
        self.check_interval = check_interval

    def _get_loop_interval(self) -> float:
        """메인 루프 간격 반환."""
        return 1.0  # 1초마다 체크 (shutdown 빠른 반응)

    async def _main_loop_iteration(self):
        """메인 루프 한 사이클.

        스케줄 설정을 확인하고, 실행 시간이 되면 크롤링을 시작합니다.
        """
        # 완료된 태스크 정리
        self._cleanup_completed_tasks()

        # 스케줄 기반 실행 디스패치
        await self._dispatch_scheduled_runs()

    def _cleanup_stale_requests(self):
        """오래된 running 상태 실행 정리."""
        db = SessionLocal()
        try:
            schedule_service = CrawlScheduleService(db)
            cleaned = schedule_service.cleanup_stale_runs(timeout_minutes=30)
            if cleaned > 0:
                logger.info(f"[{self.name}] {cleaned}개의 오래된 running 실행 정리 완료")
        except Exception as e:
            logger.error(f"[{self.name}] Stale run 정리 오류: {e}")
        finally:
            db.close()

    async def _dispatch_scheduled_runs(self):
        """스케줄 설정을 확인하고 실행 시간이면 크롤링을 시작합니다."""
        db = SessionLocal()
        try:
            schedule_service = CrawlScheduleService(db)

            # Instagram feed 타입의 활성 스케줄 조회
            instagram_schedules = schedule_service.get_schedules_by_type(
                CrawlSchedule.TARGET_TYPE_INSTAGRAM_FEED,
                enabled_only=True
            )
            for schedule in instagram_schedules:
                await self._process_schedule(db, schedule, schedule_service)

            # Google search 타입의 활성 스케줄 조회
            google_schedules = schedule_service.get_schedules_by_type(
                CrawlSchedule.TARGET_TYPE_GOOGLE_SEARCH,
                enabled_only=True
            )
            for schedule in google_schedules:
                await self._process_google_search_schedule(db, schedule, schedule_service)

        except Exception as e:
            logger.error(f"[{self.name}] 스케줄 디스패치 오류: {e}", exc_info=True)
        finally:
            db.close()

    async def _process_schedule(
        self,
        db,
        schedule: CrawlSchedule,
        schedule_service: CrawlScheduleService
    ):
        """개별 스케줄 처리."""
        try:
            config = schedule.get_target_config()
            service_account_id = config.get("service_account_id")

            if not service_account_id:
                return

            # 타임 윈도우 설정
            time_windows = [
                TimeWindow(**tw) for tw in config.get("time_windows", [])
            ]
            daily_runs = config.get("daily_runs", 3)
            min_interval = config.get("min_interval_hours", 2)

            scheduler = InstagramScheduler(
                daily_runs=daily_runs,
                time_windows=time_windows,
            )

            # 마지막 실행 시간 조회
            last_run = schedule_service.get_latest_run(schedule.id)
            last_run_time = last_run.started_at if last_run else None

            if scheduler.should_run_now(
                last_run=last_run_time,
                min_interval_hours=min_interval,
            ):
                logger.info(f"[{self.name}] 스케줄 실행 시간 도래: schedule_id={schedule.id}")

                # 이미 활성 실행이 있는지 확인
                if schedule_service.has_active_run(schedule.id):
                    logger.info(f"[{self.name}] 이미 활성 실행 존재, 스킵")
                    return

                # 실행 시작
                run = schedule_service.start_run(
                    schedule_id=schedule.id,
                    worker_id=self.name,
                    config_snapshot=config
                )

                task_name = f"schedule_{schedule.id}_run_{run.id}"
                if not self._is_task_running(task_name):
                    self._create_task(
                        self._execute_feed_crawl(schedule, run, service_account_id),
                        task_name
                    )
                    logger.info(f"[{self.name}] 스케줄 피드 크롤링 태스크 시작: run_id={run.id}")

        except Exception as e:
            logger.error(f"[{self.name}] 스케줄 처리 오류: schedule_id={schedule.id}, error={e}", exc_info=True)

    async def _execute_feed_crawl(
        self,
        schedule: CrawlSchedule,
        run: CrawlScheduleRun,
        service_account_id: int
    ):
        """Instagram 피드 크롤링 실행.

        Args:
            schedule: 크롤링 스케줄
            run: 실행 기록
            service_account_id: 계정 ID
        """
        db = SessionLocal()
        max_retries = 3
        retry_count = 0

        try:
            schedule_service = CrawlScheduleService(db)
            crawl_service = CrawlService(db)

            while retry_count <= max_retries:
                try:
                    account = db.query(ServiceAccount).filter(
                        ServiceAccount.id == service_account_id
                    ).first()
                    if not account:
                        schedule_service.fail_run(run.id, "계정을 찾을 수 없음")
                        logger.warning(f"[{self.name}] 계정 없음: service_account_id={service_account_id}")
                        return

                    self._update_worker_state("crawling", account.identifier)

                    # BrowserManager를 통한 탭 획득 및 크롤링 실행
                    result = await self.execute_with_tab(
                        callback=self._crawl_with_tab,
                        service_account_id=account.id,
                        schedule=schedule,
                        run=run,
                        account=account,
                        db=db,
                        schedule_service=schedule_service,
                        crawl_service=crawl_service,
                    )

                    if result:
                        return  # 성공적으로 완료

                except Exception as e:
                    if self.is_browser_closed_error(e) and retry_count < max_retries:
                        retry_count += 1
                        logger.warning(
                            f"[{self.name}] 브라우저 closed 에러 감지, 재시도 ({retry_count}/{max_retries}): {e}"
                        )
                        # 브라우저 재초기화
                        if self.browser and self.browser.is_initialized:
                            await self.browser.cleanup()
                            self._browser_initialized = False
                        continue

                    schedule_service.fail_run(run.id, format_error_message(e))
                    logger.error(f"[{self.name}] 크롤링 예외: {format_error_message(e)}", exc_info=True)
                    return

        except Exception as e:
            logger.error(f"[{self.name}] 피드 크롤링 실패: run_id={run.id}, error={format_error_message(e)}", exc_info=True)
            try:
                schedule_service = CrawlScheduleService(db)
                schedule_service.fail_run(run.id, format_error_message(e))
            except Exception:
                pass
        finally:
            self._update_worker_state("idle")
            db.close()

    async def _crawl_with_tab(
        self,
        tab: "Page",
        schedule: CrawlSchedule,
        run: CrawlScheduleRun,
        account: ServiceAccount,
        db,
        schedule_service: CrawlScheduleService,
        crawl_service: CrawlService,
    ) -> bool:
        """탭을 사용하여 피드 크롤링을 수행합니다.

        Args:
            tab: Playwright Page 객체
            schedule: 크롤링 스케줄
            run: 실행 기록
            account: 계정 정보
            db: DB 세션
            schedule_service: 스케줄 서비스
            crawl_service: 크롤링 서비스

        Returns:
            성공 여부
        """
        logger.info(f"[{self.name}] 인스타그램 피드 페이지로 이동 중...")
        await tab.goto("https://www.instagram.com/", wait_until="domcontentloaded")
        await tab.wait_for_timeout(2000)
        logger.info(f"[{self.name}] 인스타그램 페이지 로드 완료: {tab.url}")

        is_logged_in = await self._check_instagram_login(tab)
        if not is_logged_in:
            account.is_logged_in = False
            db.commit()
            schedule_service.fail_run(run.id, "Instagram 로그인 필요")
            logger.warning(f"[{self.name}] Instagram 로그인 필요: account={account.name}")
            return False
        else:
            account.is_logged_in = True
            db.commit()

        crawler = InstagramCrawler(tab)
        logger.info(f"[{self.name}] InstagramCrawler 생성 완료, 크롤링 시작...")

        # CrawlService.run_crawl 사용 (CrawlScheduleRun 생성)
        crawl_run = await crawl_service.run_crawl(
            crawler=crawler,
            service_account_id=account.id,
        )

        self._update_worker_state("crawling", account.name, run.id)

        logger.info(
            f"[{self.name}] 크롤링 완료: success={crawl_run.success}, "
            f"collected={crawl_run.total_collected}, new={crawl_run.new_saved}"
        )

        # CrawlScheduleRun 업데이트
        if crawl_run.success:
            schedule_service.complete_run(
                run.id,
                collected_count=crawl_run.total_collected,
                saved_count=crawl_run.new_saved,
                stop_reason=crawl_run.stop_reason
            )
            schedule_service.update_schedule_after_run(schedule.id)
            logger.info(
                f"[{self.name}] 크롤링 완료: run_id={run.id}, "
                f"collected={crawl_run.total_collected}, new={crawl_run.new_saved}"
            )
        else:
            schedule_service.fail_run(run.id, crawl_run.error_message or "크롤링 실패")
            logger.warning(f"[{self.name}] 크롤링 실패: {crawl_run.error_message}")

        return crawl_run.success

    async def _check_instagram_login(self, page: "Page") -> bool:
        """Instagram 로그인 상태 확인.

        Args:
            page: Playwright Page 객체

        Returns:
            로그인 여부
        """
        try:
            login_button = await page.query_selector('a[href="/accounts/login/"]')
            if login_button:
                return False

            login_indicators = [
                'a[href*="/direct/inbox/"]',
                'svg[aria-label="홈"]',
                'svg[aria-label="Home"]',
                'article',
            ]
            for selector in login_indicators:
                elem = await page.query_selector(selector)
                if elem:
                    return True

            return False
        except Exception as e:
            logger.warning(f"[{self.name}] Instagram 로그인 상태 확인 실패: {e}")
            return False

    # =====================================
    # Google 검색 스케줄 처리
    # =====================================

    async def _process_google_search_schedule(
        self,
        db,
        schedule: CrawlSchedule,
        schedule_service: CrawlScheduleService
    ):
        """Google 검색 스케줄 처리.

        Args:
            db: DB 세션
            schedule: 크롤링 스케줄
            schedule_service: 스케줄 서비스
        """
        try:
            config = schedule.get_target_config()
            saved_search_id = config.get("saved_search_id")

            if not saved_search_id:
                logger.warning(f"[{self.name}] saved_search_id 없음: schedule_id={schedule.id}")
                return

            # 타임 윈도우 설정
            time_windows = [
                TimeWindow(**tw) for tw in config.get("time_windows", [])
            ]
            daily_runs = config.get("daily_runs", 1)
            min_interval = config.get("min_interval_hours", 1)

            scheduler = InstagramScheduler(
                daily_runs=daily_runs,
                time_windows=time_windows,
            )

            # 마지막 실행 시간 조회
            last_run = schedule_service.get_latest_run(schedule.id)
            last_run_time = last_run.started_at if last_run else None

            if scheduler.should_run_now(
                last_run=last_run_time,
                min_interval_hours=min_interval,
            ):
                logger.info(f"[{self.name}] Google 검색 스케줄 실행 시간 도래: schedule_id={schedule.id}")

                # 이미 활성 실행이 있는지 확인
                if schedule_service.has_active_run(schedule.id):
                    logger.info(f"[{self.name}] 이미 활성 실행 존재, 스킵")
                    return

                # 실행 시작
                run = schedule_service.start_run(
                    schedule_id=schedule.id,
                    worker_id=self.name,
                    config_snapshot=config
                )

                task_name = f"google_schedule_{schedule.id}_run_{run.id}"
                if not self._is_task_running(task_name):
                    self._create_task(
                        self._execute_google_search(schedule, run, saved_search_id),
                        task_name
                    )
                    logger.info(f"[{self.name}] Google 검색 스케줄 태스크 시작: run_id={run.id}")

        except Exception as e:
            logger.error(f"[{self.name}] Google 검색 스케줄 처리 오류: schedule_id={schedule.id}, error={e}", exc_info=True)

    async def _execute_google_search(
        self,
        schedule: CrawlSchedule,
        run: CrawlScheduleRun,
        saved_search_id: int
    ):
        """Google 검색 실행.

        Args:
            schedule: 크롤링 스케줄
            run: 실행 기록
            saved_search_id: 저장된 검색 ID
        """
        db = SessionLocal()
        try:
            schedule_service = CrawlScheduleService(db)

            # 저장된 검색 조회
            saved_search = db.query(GoogleSavedSearch).filter_by(id=saved_search_id).first()
            if not saved_search:
                schedule_service.fail_run(run.id, "저장된 검색을 찾을 수 없습니다")
                logger.warning(f"[{self.name}] 저장된 검색 없음: saved_search_id={saved_search_id}")
                return

            self._update_worker_state("searching", saved_search.name)

            # GoogleSearchQueue에 추가 (기존 워커가 처리)
            search_id = str(uuid.uuid4())
            queue_item = GoogleSearchQueue(
                search_id=search_id,
                query=saved_search.query,
                date_filter=saved_search.date_filter,
                max_pages=saved_search.max_pages or 1,
                service_account_id=saved_search.service_account_id,
                saved_search_id=saved_search_id,
                status="pending"
            )
            db.add(queue_item)
            db.commit()

            logger.info(
                f"[{self.name}] Google 검색 큐에 추가: "
                f"search_id={search_id}, query={saved_search.query}"
            )

            # 검색 완료 대기 (폴링)
            result = await self._wait_for_search_completion(search_id)

            if result["status"] == "completed":
                schedule_service.complete_run(
                    run.id,
                    collected_count=result["total_results"],
                    saved_count=result["total_results"],
                    stop_reason=CrawlScheduleRun.STOP_REASON_SEARCH_COMPLETED
                )
                schedule_service.update_schedule_after_run(schedule.id)
                logger.info(
                    f"[{self.name}] Google 검색 완료: run_id={run.id}, "
                    f"total_results={result['total_results']}"
                )
            else:
                error_msg = result.get("error_message", "검색 실패")
                if "CAPTCHA" in error_msg:
                    schedule_service.fail_run(run.id, error_msg)
                    logger.warning(f"[{self.name}] Google 검색 실패 (CAPTCHA): {error_msg}")
                else:
                    schedule_service.fail_run(run.id, error_msg)
                    logger.warning(f"[{self.name}] Google 검색 실패: {error_msg}")

        except Exception as e:
            logger.error(f"[{self.name}] Google 검색 실행 실패: run_id={run.id}, error={format_error_message(e)}", exc_info=True)
            try:
                schedule_service = CrawlScheduleService(db)
                schedule_service.fail_run(run.id, format_error_message(e))
            except Exception:
                pass
        finally:
            self._update_worker_state("idle")
            db.close()

    async def _wait_for_search_completion(
        self,
        search_id: str,
        timeout: int = 300
    ) -> dict:
        """검색 완료 대기 (최대 5분).

        Args:
            search_id: 검색 세션 ID
            timeout: 타임아웃 (초)

        Returns:
            dict: {"status": "completed"|"failed", "total_results": int, "error_message": str}
        """
        start = datetime.now()

        while (datetime.now() - start).total_seconds() < timeout:
            db = SessionLocal()
            try:
                # 큐 상태 확인
                queue = db.query(GoogleSearchQueue).filter_by(search_id=search_id).first()

                if queue and queue.status in ["completed", "failed"]:
                    history = db.query(GoogleSearchHistory).filter_by(search_id=search_id).first()
                    return {
                        "status": queue.status,
                        "total_results": history.total_results if history else 0,
                        "error_message": queue.error_message
                    }
            finally:
                db.close()

            await asyncio.sleep(2)

        return {"status": "failed", "error_message": "Timeout"}
