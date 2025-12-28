"""
스케줄 기반 크롤링 워커.

Instagram 스케줄 설정(InstagramScheduleConfig)에 따라
정해진 시간에 피드 크롤링을 자동으로 수행합니다.

실행 방법:
    python -m app.worker.scheduled_worker

주요 기능:
    - 스케줄 설정에 따른 자동 피드 크롤링
    - TimeWindow 기반 실행 시간 관리
    - 최소 간격 제한 준수
"""
import asyncio
import logging
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from app.worker.crawl_worker_base import CrawlWorkerBase
from app.database import SessionLocal
from app.models import ServiceAccount, InstagramCrawlRequest

from app.modules.instagram.services.request_service import CrawlRequestService
from app.modules.instagram.services.crawl_service import CrawlService
from app.modules.instagram.services.scheduler import InstagramScheduler
from app.modules.instagram.services.crawler import InstagramCrawler
from app.modules.instagram.models.schemas import TimeWindow

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = logging.getLogger(__name__)


class ScheduledCrawlWorker(CrawlWorkerBase):
    """스케줄 기반 Instagram 피드 크롤링 워커.

    InstagramScheduleConfig 설정에 따라 정해진 시간에
    자동으로 Instagram 피드를 크롤링합니다.

    Attributes:
        check_interval: 스케줄 확인 간격 (초)
    """

    def __init__(self, check_interval: int = 30):
        """ScheduledCrawlWorker 초기화.

        Args:
            check_interval: 스케줄 확인 간격 (초). 기본 30초.
        """
        super().__init__(name="scheduled_worker", worker_type="scheduled")
        self.check_interval = check_interval

    def _get_loop_interval(self) -> float:
        """메인 루프 간격 반환."""
        return 1.0  # 1초마다 체크 (shutdown 빠른 반응)

    async def _main_loop_iteration(self):
        """메인 루프 한 사이클.

        스케줄 설정을 확인하고, 실행 시간이 되면 크롤링을 시작합니다.
        수동으로 생성된 feed 요청도 처리합니다.
        """
        # 완료된 태스크 정리
        self._cleanup_completed_tasks()

        # 수동으로 생성된 pending feed 요청 처리
        await self._dispatch_manual_feed_requests()

        # 스케줄 기반 실행 디스패치
        await self._dispatch_scheduled_runs()

    async def _dispatch_manual_feed_requests(self):
        """수동으로 생성된 pending feed 요청을 처리합니다."""
        db = SessionLocal()
        try:
            request_service = CrawlRequestService(db)

            # feed 타입의 pending 요청 조회 (manual로 생성된 것)
            pending_requests = (
                db.query(InstagramCrawlRequest)
                .filter(
                    InstagramCrawlRequest.status == "pending",
                    InstagramCrawlRequest.request_type.in_(["feed", None]),
                    InstagramCrawlRequest.requested_by == "manual",
                )
                .order_by(InstagramCrawlRequest.requested_at)
                .limit(1)
                .all()
            )

            for request in pending_requests:
                task_name = f"feed_{request.id}"
                if self._is_task_running(task_name):
                    continue

                task = self._create_task(
                    self._execute_feed_crawl(request),
                    task_name
                )
                logger.info(f"[{self.name}] 수동 피드 크롤링 태스크 시작: request_id={request.id}")

        except Exception as e:
            logger.error(f"[{self.name}] 수동 feed 요청 디스패치 오류: {e}", exc_info=True)
        finally:
            db.close()

    def _cleanup_stale_requests(self):
        """오래된 processing/pending 상태 요청 정리."""
        db = SessionLocal()
        try:
            request_service = CrawlRequestService(db)
            cleaned_processing = request_service.cleanup_stale_processing_requests(timeout_minutes=30)
            cleaned_pending = request_service.cleanup_stale_pending_requests(timeout_minutes=60)
            if cleaned_processing > 0:
                logger.info(f"[{self.name}] {cleaned_processing}개의 오래된 processing 요청 정리 완료")
            if cleaned_pending > 0:
                logger.info(f"[{self.name}] {cleaned_pending}개의 오래된 pending 요청 정리 완료")
        except Exception as e:
            logger.error(f"[{self.name}] Stale request 정리 오류: {e}")
        finally:
            db.close()

    async def _dispatch_scheduled_runs(self):
        """스케줄 설정을 확인하고 실행 시간이면 크롤링을 시작합니다."""
        db = SessionLocal()
        try:
            crawl_service = CrawlService(db)
            config = crawl_service.get_schedule_config()

            if not config or not config.enabled:
                return

            if not config.service_account_id:
                return

            time_windows = [
                TimeWindow(**tw) for tw in (config.time_windows or [])
            ]

            scheduler = InstagramScheduler(
                daily_runs=config.daily_runs,
                time_windows=time_windows,
            )

            last_run = crawl_service.get_last_run(service_account_id=config.service_account_id)
            last_run_time = last_run.started_at if last_run else None

            min_interval = getattr(config, 'min_interval_hours', 2) or 2
            if scheduler.should_run_now(
                last_run=last_run_time,
                min_interval_hours=min_interval,
            ):
                logger.info(f"[{self.name}] 스케줄 실행 시간 도래: service_account_id={config.service_account_id}")

                request_service = CrawlRequestService(db)
                if request_service.has_active_request(config.service_account_id):
                    logger.info(f"[{self.name}] 이미 활성 요청 존재, 스킵")
                    return

                request = request_service.create_request(
                    service_account_id=config.service_account_id,
                    requested_by="scheduler",
                )

                if not self._is_task_running(f"feed_{request.id}"):
                    task = self._create_task(
                        self._execute_feed_crawl(request),
                        f"feed_{request.id}"
                    )
                    logger.info(f"[{self.name}] 스케줄 피드 크롤링 태스크 시작: request_id={request.id}")

        except Exception as e:
            logger.error(f"[{self.name}] 스케줄 디스패치 오류: {e}", exc_info=True)
        finally:
            db.close()

    async def _execute_feed_crawl(self, request: InstagramCrawlRequest):
        """Instagram 피드 크롤링 실행.

        Args:
            request: 크롤링 요청 객체
        """
        db = SessionLocal()
        max_retries = 3
        retry_count = 0

        try:
            request_service = CrawlRequestService(db)
            crawl_service = CrawlService(db)

            request_service.mark_processing(request.id)

            while retry_count <= max_retries:
                try:
                    account = db.query(ServiceAccount).filter(ServiceAccount.id == request.service_account_id).first()
                    if not account:
                        request_service.mark_failed(request.id, "계정을 찾을 수 없음")
                        logger.warning(f"[{self.name}] 계정 없음: service_account_id={request.service_account_id}")
                        return

                    self._update_worker_state("crawling", account.identifier)

                    # BrowserManager를 통한 탭 획득 및 크롤링 실행
                    result = await self.execute_with_tab(
                        callback=self._crawl_with_tab,
                        service_account_id=account.id,
                        request=request,
                        account=account,
                        db=db,
                        request_service=request_service,
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

                    request_service.mark_failed(request.id, str(e))
                    logger.error(f"[{self.name}] 크롤링 예외: {e}", exc_info=True)
                    return

        except Exception as e:
            logger.error(f"[{self.name}] 피드 크롤링 실패: request_id={request.id}, error={e}", exc_info=True)
            try:
                request_service = CrawlRequestService(db)
                request_service.mark_failed(request.id, str(e))
            except Exception:
                pass
        finally:
            self._update_worker_state("idle")
            db.close()

    async def _crawl_with_tab(
        self,
        tab: "Page",
        request: InstagramCrawlRequest,
        account: ServiceAccount,
        db,
        request_service: CrawlRequestService,
        crawl_service: CrawlService,
    ) -> bool:
        """탭을 사용하여 피드 크롤링을 수행합니다.

        Args:
            tab: Playwright Page 객체
            request: 크롤링 요청
            account: 계정 정보
            db: DB 세션
            request_service: 요청 서비스
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
            request_service.mark_failed(request.id, "Instagram 로그인 필요")
            logger.warning(f"[{self.name}] Instagram 로그인 필요: account={account.name}")
            return False
        else:
            account.is_logged_in = True
            db.commit()

        crawler = InstagramCrawler(tab)
        logger.info(f"[{self.name}] InstagramCrawler 생성 완료, 크롤링 시작...")

        crawl_run = await crawl_service.run_crawl(
            crawler=crawler,
            service_account_id=request.service_account_id,
        )

        self._update_worker_state("crawling", account.name, crawl_run.id)

        logger.info(
            f"[{self.name}] 크롤링 완료: success={crawl_run.success}, "
            f"collected={crawl_run.total_collected}, new={crawl_run.new_saved}"
        )

        if crawl_run.success:
            request_service.mark_completed(request.id, crawl_run.id)
            logger.info(
                f"[{self.name}] 크롤링 완료: request_id={request.id}, "
                f"collected={crawl_run.total_collected}, new={crawl_run.new_saved}"
            )
        else:
            request_service.mark_failed(request.id, crawl_run.error_message or "크롤링 실패")
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
