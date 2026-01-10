"""
온디맨드 크롤링 워커.

사용자 요청에 따라 즉시 크롤링을 수행합니다:
- 단건 URL 크롤링 (CrawlRequest 기반)
- 다양한 사이트 자동 감지 (Instagram, 네이버, Google Form 등)

실행 방법:
    python -m app.worker.ondemand_worker

주요 기능:
    - Instagram 피드 크롤링 (수동 요청)
    - Instagram URL 크롤링 (게시물/릴스)
    - Universal URL 크롤링 (다양한 사이트 자동 감지)
    - AI 분석 자동 요청 지원

Redis 큐 지원:
    - Redis 연결 시: Redis 큐에서 작업 수신 (BRPOP)
    - Redis 미연결 시: SQLite 폴링 fallback
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, TYPE_CHECKING

from app.worker.crawl_worker_base import CrawlWorkerBase
from app.database import SessionLocal
from app.models import ServiceAccount, CrawlRequest, TaskScheduleRun

from app.services.crawl_request_service import CrawlRequestService
from app.modules.instagram.services.crawl_service import CrawlService
from app.modules.instagram.services.crawler import InstagramCrawler
from app.utils.error_utils import format_error_message

from app.services.page_extractor.factory import get_extractor_factory
from app.shared.redis import RedisClient, RedisQueue
from app.shared.redis.queue import CRAWL_REQUEST_QUEUE

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = logging.getLogger(__name__)


class OnDemandCrawlWorker(CrawlWorkerBase):
    """온디맨드 크롤링 워커.

    사용자의 즉시 요청(CrawlRequest)을 처리합니다:
    - Instagram URL 크롤링
    - 네이버 블로그/폼 크롤링
    - Google Form 크롤링
    - 기타 URL 크롤링

    Redis 큐 지원:
    - Redis 연결 시: Redis 큐에서 작업 수신 (즉각 반응)
    - Redis 미연결 시: SQLite 폴링 fallback (1초 간격)

    Attributes:
        max_concurrent_requests: 동시 처리 가능한 최대 요청 수
        use_redis: Redis 큐 사용 여부
        redis_queue: Redis 큐 인스턴스
    """

    def __init__(self, max_concurrent_requests: int = 5, browser_manager=None):
        """OnDemandCrawlWorker 초기화.

        Args:
            max_concurrent_requests: 동시 처리 가능한 최대 요청 수. 기본 5.
            browser_manager: 외부에서 주입받을 BrowserManager (None이면 자체 생성)
        """
        super().__init__(
            name="ondemand_worker",
            worker_type="ondemand",
            browser_manager=browser_manager
        )
        self.max_concurrent_requests = max_concurrent_requests
        self._extractor_factory = get_extractor_factory()

        # Redis 큐 관련
        self.use_redis = False
        self.redis_queue: Optional[RedisQueue] = None
        self._redis_initialized = False

    async def _setup_redis(self):
        """Redis 큐 초기화."""
        if self._redis_initialized:
            return

        redis_client = await RedisClient.get_client()
        if redis_client:
            self.redis_queue = RedisQueue(redis_client, CRAWL_REQUEST_QUEUE)
            self.use_redis = True
            logger.info(f"[{self.name}] Redis 큐 모드 활성화")

            # 워커 시작 시 pending 요청을 Redis 큐에 푸시
            await self._recover_pending_requests()
        else:
            self.use_redis = False
            logger.info(f"[{self.name}] SQLite 폴링 모드 (Redis 미연결)")

        self._redis_initialized = True

    async def _recover_pending_requests(self):
        """워커 시작 시 pending 요청을 Redis 큐에 복구.

        이전에 Redis 큐에 푸시되지 않은 pending 요청을 감지하여 큐에 추가합니다.
        이는 API가 재시작되거나 Redis 푸시가 누락된 경우를 대비한 복구 메커니즘입니다.
        """
        if not self.redis_queue:
            logger.debug(f"[{self.name}] Redis 큐가 없어 pending 복구 스킵")
            return

        db = SessionLocal()
        try:
            request_service = CrawlRequestService(db)

            # pending 상태인 요청 조회 (최대 100개)
            pending_requests = request_service.get_pending_requests(limit=100)
            logger.debug(f"[{self.name}] Pending 요청 조회: {len(pending_requests)}개")

            recovered = 0
            skipped_activity = 0
            failed_push = 0

            for request in pending_requests:
                # Activity 요청은 ActivityWorker가 처리
                if request.url_type == CrawlRequest.URL_TYPE_ACTIVITY:
                    skipped_activity += 1
                    logger.debug(f"[{self.name}] Activity 요청 스킵: id={request.id}")
                    continue

                # Redis 큐에 푸시
                logger.debug(f"[{self.name}] Redis 푸시 시도: id={request.id}, type={request.url_type}")
                success = await self.redis_queue.push({
                    "id": request.id,
                    "url": request.url,
                    "url_type": request.url_type,
                    "requested_by": request.requested_by,
                    "created_at": request.requested_at,
                })

                if success:
                    # 상태를 queued로 변경
                    request.status = CrawlRequest.STATUS_QUEUED
                    recovered += 1
                    logger.debug(f"[{self.name}] Redis 푸시 성공: id={request.id}")
                else:
                    failed_push += 1
                    logger.warning(f"[{self.name}] Redis 푸시 실패: id={request.id}")

            if recovered > 0:
                db.commit()
                logger.info(f"[{self.name}] {recovered}개의 pending 요청을 Redis 큐에 복구 (Activity 스킵: {skipped_activity}, 푸시 실패: {failed_push})")
            else:
                logger.info(f"[{self.name}] 복구할 pending 요청 없음 (전체: {len(pending_requests)}, Activity 스킵: {skipped_activity}, 푸시 실패: {failed_push})")

        except Exception as e:
            logger.error(f"[{self.name}] Pending 요청 복구 오류: {e}", exc_info=True)
        finally:
            db.close()

    def _get_loop_interval(self) -> float:
        """메인 루프 간격 반환."""
        # Redis 모드: 짧은 간격 (큐가 비어있을 때만 대기)
        # SQLite 모드: 1초 간격 폴링
        return 0.1 if self.use_redis else 1.0

    async def _main_loop_iteration(self):
        """메인 루프 한 사이클.

        Redis 큐 또는 SQLite에서 요청을 가져와 처리합니다.
        """
        # Redis 초기화 (첫 번째 호출 시)
        await self._setup_redis()

        # 완료된 태스크 정리
        self._cleanup_completed_tasks()

        # Redis 큐 또는 SQLite 폴링
        if self.use_redis:
            await self._process_redis_queue()
        else:
            await self._dispatch_pending_requests()

    def _cleanup_stale_requests(self):
        """오래된 processing 상태 요청 정리."""
        db = SessionLocal()
        try:
            request_service = CrawlRequestService(db)
            cleaned = request_service.cleanup_stale_processing(timeout_minutes=30)
            if cleaned > 0:
                logger.info(f"[{self.name}] {cleaned}개의 오래된 processing 요청 정리 완료")
        except Exception as e:
            logger.error(f"[{self.name}] Stale request 정리 오류: {e}")
        finally:
            db.close()

    # ========== Redis 큐 처리 ==========

    async def _process_redis_queue(self):
        """Redis 큐에서 작업을 가져와 처리.

        동시 처리 슬롯이 있을 때만 큐에서 작업을 가져옵니다.
        """
        if not self.redis_queue:
            return

        # 동시 처리 슬롯 확인
        active_count = len(self._running_tasks)
        available_slots = self.max_concurrent_requests - active_count

        if available_slots <= 0:
            return

        # 사용 가능한 슬롯 수만큼 작업 가져오기
        for _ in range(available_slots):
            job = await self.redis_queue.pop_nowait()
            if not job:
                break  # 큐가 비어있음

            request_id = job.get("id")
            if not request_id:
                logger.warning(f"[{self.name}] Redis 큐 메시지에 id 없음: {job}")
                continue

            task_name = f"req_{request_id}"
            if self._is_task_running(task_name):
                logger.debug(f"[{self.name}] 이미 실행 중인 요청: {request_id}")
                continue

            # DB에서 요청 조회 및 상태 업데이트
            db = SessionLocal()
            try:
                request = db.query(CrawlRequest).filter(
                    CrawlRequest.id == request_id
                ).first()

                if not request:
                    logger.warning(f"[{self.name}] Redis 큐의 요청이 DB에 없음: id={request_id}")
                    continue

                # 취소된 요청 스킵
                if request.status == CrawlRequest.STATUS_CANCELLED:
                    logger.info(f"[{self.name}] 취소된 요청 스킵: id={request_id}")
                    continue

                # Activity 요청은 ActivityWorker가 처리
                if request.url_type == CrawlRequest.URL_TYPE_ACTIVITY:
                    logger.debug(f"[{self.name}] Activity 요청 스킵: id={request_id}")
                    continue

                # 이미 처리된 요청인지 확인
                if request.status not in (CrawlRequest.STATUS_QUEUED, CrawlRequest.STATUS_PENDING):
                    logger.debug(f"[{self.name}] 이미 처리된 요청: id={request_id}, status={request.status}")
                    continue

                # picked 상태로 변경
                request.status = CrawlRequest.STATUS_PICKED
                request.picked_at = datetime.now()
                request.worker_id = self.name
                db.commit()

                # 태스크 시작 (request 객체는 _execute_request에서 새로 조회)
                self._create_task(
                    self._execute_request(request),
                    task_name
                )
                logger.info(
                    f"[{self.name}] Redis 큐에서 태스크 시작: request_id={request_id}, "
                    f"url_type={request.url_type}"
                )

            except Exception as e:
                logger.error(f"[{self.name}] Redis 큐 처리 오류: {e}", exc_info=True)
            finally:
                db.close()

    # ========== SQLite 폴링 (Fallback) ==========

    async def _dispatch_pending_requests(self):
        """Pending 요청을 백그라운드 태스크로 디스패치."""
        db = SessionLocal()
        try:
            request_service = CrawlRequestService(db)

            # pending 상태의 요청 조회
            pending_list = request_service.get_pending_requests(
                limit=self.max_concurrent_requests
            )

            for pending in pending_list:
                # Activity 요청은 ActivityWorker가 처리
                if pending.url_type == CrawlRequest.URL_TYPE_ACTIVITY:
                    continue

                task_name = f"req_{pending.id}"
                if self._is_task_running(task_name):
                    continue

                # 요청을 picked 상태로 변경
                picked = request_service.pick_request(pending.id, self.name)
                if not picked:
                    continue  # 다른 워커가 먼저 가져감

                self._create_task(
                    self._execute_request(picked),
                    task_name
                )
                logger.info(
                    f"[{self.name}] 크롤링 태스크 시작: request_id={picked.id}, "
                    f"url_type={picked.url_type}"
                )

        except Exception as e:
            logger.error(f"[{self.name}] Pending 요청 디스패치 오류: {e}", exc_info=True)
        finally:
            db.close()

    async def _execute_request(self, request: CrawlRequest):
        """요청 실행 (url_type에 따라 분기).

        Args:
            request: 크롤링 요청 객체
        """
        db = SessionLocal()
        try:
            request_service = CrawlRequestService(db)

            # processing 상태로 변경
            request_service.start_processing(request.id)

            logger.info(
                f"[{self.name}] 크롤링 시작: request_id={request.id}, "
                f"url_type={request.url_type}, url={request.url}"
            )

            url_type = request.url_type

            # Activity 타입은 ActivityWorker가 처리 (스킵 - 상태 유지)
            if url_type == CrawlRequest.URL_TYPE_ACTIVITY:
                logger.warning(
                    f"[{self.name}] Activity 요청이 잘못 전달됨 (ActivityWorker가 처리해야 함): id={request.id}"
                )
                # 실패 처리하여 재시도 없이 종료
                request_service.fail_request(
                    request.id,
                    "Activity 요청은 ActivityWorker가 처리해야 합니다"
                )
                return

            # Instagram 관련 타입 처리
            if url_type == CrawlRequest.URL_TYPE_INSTAGRAM:
                await self._execute_instagram_crawl(request, db, request_service)
            elif url_type == "instagram_feed":
                # 수동 피드 크롤링 요청
                await self._execute_instagram_feed_crawl(request, db, request_service)
            elif url_type in ("instagram_post", "instagram_account", "instagram_hashtag", "instagram_reels"):
                # Instagram URL 크롤링 (게시물/계정/해시태그/릴스)
                await self._execute_instagram_crawl(request, db, request_service)
            else:
                # 기타 URL은 범용 추출기 사용
                await self._execute_universal_crawl(request, db, request_service)

        except Exception as e:
            logger.error(
                f"[{self.name}] 크롤링 실패: request_id={request.id}, error={e}",
                exc_info=True
            )
            try:
                request_service = CrawlRequestService(db)
                request_service.fail_request(request.id, format_error_message(e))
            except Exception:
                pass
        finally:
            db.close()

    # ========== Instagram 크롤링 ==========

    async def _execute_instagram_crawl(
        self,
        request: CrawlRequest,
        db,
        request_service: CrawlRequestService,
    ):
        """Instagram URL 크롤링 실행."""
        max_retries = 3
        retry_count = 0

        while retry_count <= max_retries:
            try:
                # Instagram 계정 조회 (활성 프로필의 첫 번째 계정 사용)
                from app.models.browser_profile import BrowserProfile
                account = db.query(ServiceAccount).join(
                    BrowserProfile
                ).filter(
                    ServiceAccount.service_type == "instagram",
                    BrowserProfile.is_active == True
                ).first()

                if not account:
                    request_service.fail_request(request.id, "Instagram 계정 없음")
                    logger.warning(f"[{self.name}] Instagram 계정 없음")
                    return

                self._update_worker_state("crawling", account.identifier)

                # BrowserManager를 통한 탭 획득 및 크롤링 실행
                result = await self.execute_with_tab(
                    callback=self._instagram_crawl_with_tab,
                    service_account_id=account.id,
                    request=request,
                    account=account,
                    db=db,
                    request_service=request_service,
                )

                if result.get("success"):
                    post = result.get("post")
                    request_service.complete_request(
                        request.id,
                        result_type="instagram_post",
                        result_id=post.id if post else 0
                    )
                    logger.info(
                        f"[{self.name}] Instagram 크롤링 완료: request_id={request.id}, "
                        f"post_id={post.id if post else None}"
                    )
                else:
                    request_service.fail_request(request.id, result.get("message", "크롤링 실패"))
                    logger.warning(f"[{self.name}] Instagram 크롤링 실패: {result.get('message')}")

                return

            except Exception as e:
                if self.is_browser_closed_error(e) and retry_count < max_retries:
                    retry_count += 1
                    logger.warning(
                        f"[{self.name}] 브라우저 closed 에러 감지, 재시도 ({retry_count}/{max_retries}): {e}"
                    )
                    if self.browser and self.browser.is_initialized:
                        await self.browser.cleanup()
                        self._browser_initialized = False
                    continue

                request_service.fail_request(request.id, format_error_message(e))
                logger.error(f"[{self.name}] Instagram 크롤링 예외: {e}", exc_info=True)
                return

            finally:
                self._update_worker_state("idle")

    async def _instagram_crawl_with_tab(
        self,
        tab: "Page",
        request: CrawlRequest,
        account: ServiceAccount,
        db,
        request_service: CrawlRequestService,
    ) -> dict:
        """탭을 사용하여 Instagram URL 크롤링을 수행합니다."""
        await tab.goto("https://www.instagram.com/", wait_until="domcontentloaded")
        await tab.wait_for_timeout(1000)

        is_logged_in = await self._check_instagram_login(tab)
        if not is_logged_in:
            account.is_logged_in = False
            db.commit()
            return {"success": False, "message": "Instagram 로그인 필요"}
        else:
            account.is_logged_in = True
            db.commit()

        crawl_service = CrawlService(db)
        crawler = InstagramCrawler(tab)
        logger.info(f"[{self.name}] Instagram URL 크롤링 시작: url={request.url}")

        result = await crawl_service.crawl_by_url(
            crawler=crawler,
            url=request.url,
            service_account_id=account.id,
        )

        return result

    # ========== Instagram 피드 크롤링 ==========

    def _extract_account_id_from_url(self, url: str) -> Optional[int]:
        """URL에서 account_id 추출.

        instagram://feed?account_id=6 형식에서 account_id 추출
        """
        if url and url.startswith("instagram://feed?account_id="):
            try:
                return int(url.split("=")[1])
            except (ValueError, IndexError):
                return None
        return None

    async def _execute_instagram_feed_crawl(
        self,
        request: CrawlRequest,
        db,
        request_service: CrawlRequestService,
    ):
        """Instagram 피드 크롤링 실행 (수동 요청).

        instagram://feed?account_id=X 형식의 요청을 처리합니다.
        """
        max_retries = 3
        retry_count = 0

        # URL에서 account_id 추출
        service_account_id = self._extract_account_id_from_url(request.url)
        if not service_account_id:
            request_service.fail_request(request.id, "URL에서 account_id를 추출할 수 없음")
            logger.warning(f"[{self.name}] account_id 추출 실패: url={request.url}")
            return

        while retry_count <= max_retries:
            try:
                # 계정 조회
                account = db.query(ServiceAccount).filter(
                    ServiceAccount.id == service_account_id
                ).first()

                if not account:
                    request_service.fail_request(request.id, f"계정을 찾을 수 없음: id={service_account_id}")
                    logger.warning(f"[{self.name}] 계정 없음: service_account_id={service_account_id}")
                    return

                self._update_worker_state("crawling", account.identifier)

                # BrowserManager를 통한 탭 획득 및 크롤링 실행
                # Instagram 피드 크롤링은 최대 500개까지 수집 가능하므로 충분한 시간 필요
                result = await self.execute_with_tab(
                    callback=self._instagram_feed_crawl_with_tab,
                    service_account_id=account.id,
                    operation_timeout=3600.0,  # 1시간 타임아웃
                    request=request,
                    account=account,
                    db=db,
                    request_service=request_service,
                )

                if result.get("success"):
                    crawl_run_id = result.get("crawl_run_id")
                    request_service.complete_request(
                        request.id,
                        result_type="crawl_schedule_run",
                        result_id=crawl_run_id or 0
                    )
                    logger.info(
                        f"[{self.name}] Instagram 피드 크롤링 완료: request_id={request.id}, "
                        f"crawl_run_id={crawl_run_id}, collected={result.get('total_collected', 0)}, "
                        f"new={result.get('new_saved', 0)}"
                    )
                else:
                    request_service.fail_request(request.id, result.get("message", "피드 크롤링 실패"))
                    logger.warning(f"[{self.name}] Instagram 피드 크롤링 실패: {result.get('message')}")

                return

            except Exception as e:
                if self.is_browser_closed_error(e) and retry_count < max_retries:
                    retry_count += 1
                    logger.warning(
                        f"[{self.name}] 브라우저 closed 에러 감지, 재시도 ({retry_count}/{max_retries}): {e}"
                    )
                    if self.browser and self.browser.is_initialized:
                        await self.browser.cleanup()
                        self._browser_initialized = False
                    continue

                request_service.fail_request(request.id, format_error_message(e))
                logger.error(f"[{self.name}] Instagram 피드 크롤링 예외: {e}", exc_info=True)
                return

            finally:
                self._update_worker_state("idle")

    async def _instagram_feed_crawl_with_tab(
        self,
        tab: "Page",
        request: CrawlRequest,
        account: ServiceAccount,
        db,
        request_service: CrawlRequestService,
    ) -> dict:
        """탭을 사용하여 Instagram 피드 크롤링을 수행합니다."""
        logger.info(f"[{self.name}] Instagram 피드 페이지로 이동 중...")
        await tab.goto("https://www.instagram.com/", wait_until="domcontentloaded")
        await tab.wait_for_timeout(2000)
        logger.info(f"[{self.name}] Instagram 페이지 로드 완료: {tab.url}")

        # 로그인 상태 확인
        is_logged_in = await self._check_instagram_login(tab)
        if not is_logged_in:
            account.is_logged_in = False
            db.commit()
            return {"success": False, "message": "Instagram 로그인 필요"}
        else:
            account.is_logged_in = True
            db.commit()

        # 피드 크롤링 실행
        crawl_service = CrawlService(db)
        crawler = InstagramCrawler(tab)
        logger.info(f"[{self.name}] InstagramCrawler 생성 완료, 피드 크롤링 시작...")

        # run_crawl은 TaskScheduleRun을 생성하고 피드 크롤링 수행
        crawl_run = await crawl_service.run_crawl(
            crawler=crawler,
            service_account_id=account.id,
        )

        is_success = crawl_run.status == TaskScheduleRun.STATUS_COMPLETED
        logger.info(
            f"[{self.name}] 피드 크롤링 완료: status={crawl_run.status}, "
            f"collected={crawl_run.collected_count}, new={crawl_run.saved_count}"
        )

        if is_success:
            return {
                "success": True,
                "crawl_run_id": crawl_run.id,
                "total_collected": crawl_run.collected_count or 0,
                "new_saved": crawl_run.saved_count or 0,
            }
        else:
            return {
                "success": False,
                "message": crawl_run.error_message or "피드 크롤링 실패",
            }

    # ========== Universal 크롤링 ==========

    async def _execute_universal_crawl(
        self,
        request: CrawlRequest,
        db,
        request_service: CrawlRequestService,
    ):
        """범용 URL 크롤링 실행."""
        max_retries = 3
        retry_count = 0

        while retry_count <= max_retries:
            try:
                self._update_worker_state("crawling")

                # BrowserManager를 통한 탭 획득 및 크롤링 실행
                result = await self.execute_with_tab(
                    callback=self._universal_crawl_with_tab,
                    service_account_id=None,  # Universal은 계정 불필요
                    request=request,
                    db=db,
                    request_service=request_service,
                )

                if result.get("success"):
                    page_id = result.get("page_id")
                    request_service.complete_request(
                        request.id,
                        result_type="crawled_page",
                        result_id=page_id or 0
                    )
                    logger.info(
                        f"[{self.name}] Universal 크롤링 완료: request_id={request.id}, "
                        f"page_id={page_id}"
                    )
                else:
                    request_service.fail_request(request.id, result.get("message", "크롤링 실패"))
                    logger.warning(f"[{self.name}] Universal 크롤링 실패: {result.get('message')}")

                return

            except Exception as e:
                if self.is_browser_closed_error(e) and retry_count < max_retries:
                    retry_count += 1
                    logger.warning(
                        f"[{self.name}] 브라우저 closed 에러 감지, 재시도 ({retry_count}/{max_retries}): {e}"
                    )
                    if self.browser and self.browser.is_initialized:
                        await self.browser.cleanup()
                        self._browser_initialized = False
                    continue

                request_service.fail_request(request.id, format_error_message(e))
                logger.error(f"[{self.name}] Universal 크롤링 예외: {e}", exc_info=True)
                return

            finally:
                self._update_worker_state("idle")

    async def _universal_crawl_with_tab(
        self,
        tab: "Page",
        request: CrawlRequest,
        db,
        request_service: CrawlRequestService,
    ) -> dict:
        """탭을 사용하여 Universal 크롤링을 수행합니다."""
        try:
            # 페이지 로드
            await tab.goto(request.url, wait_until="domcontentloaded", timeout=30000)
            await tab.wait_for_timeout(2000)  # 동적 콘텐츠 로딩 대기

            # 추출기 선택 및 추출 실행
            extractor = self._extractor_factory.get_extractor(request.url)
            logger.info(f"[{self.name}] 추출기 선택: {extractor.__class__.__name__}")

            extracted = await extractor.extract(tab, request.url)

            if not extracted.success:
                return {"success": False, "message": extracted.error or "추출 실패"}

            # 결과 저장
            from app.services.universal_crawl_service import universal_crawl_service
            crawled_page = universal_crawl_service.create_crawled_page(
                db=db,
                url=request.url,
                url_type=request.url_type,
                title=extracted.title,
                description=extracted.description,
                content=extracted.content,
                extracted_data=extracted.structured_data,
                og_title=extracted.metadata.get("title"),
                og_description=extracted.metadata.get("description"),
                og_image=extracted.metadata.get("image"),
                extractor_used=extractor.__class__.__name__,
            )

            logger.info(
                f"[{self.name}] Universal 크롤링 완료: request_id={request.id}, "
                f"page_id={crawled_page.id}, title={crawled_page.title[:50] if crawled_page.title else None}"
            )

            return {"success": True, "page_id": crawled_page.id}

        except Exception as e:
            logger.error(f"[{self.name}] Universal 크롤링 오류: {e}", exc_info=True)
            return {"success": False, "message": str(e)}

    # ========== 공통 유틸리티 ==========

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
