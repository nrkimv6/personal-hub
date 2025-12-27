"""
온디맨드 크롤링 워커.

사용자 요청에 따라 즉시 크롤링을 수행합니다:
- Instagram 개별 게시물 크롤링 (single_post, single_post_url)
- Universal URL 크롤링 (다양한 사이트 지원)

실행 방법:
    python -m app.worker.ondemand_worker

주요 기능:
    - Instagram 개별 게시물 재크롤링 (post_id 기반)
    - Instagram URL 크롤링 (URL 직접 입력)
    - Universal URL 크롤링 (다양한 사이트 자동 감지)
    - AI 분석 자동 요청 지원
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, TYPE_CHECKING

from app.worker.crawl_worker_base import CrawlWorkerBase
from app.database import SessionLocal
from app.models import Account, InstagramCrawlRequest
from app.models.universal_crawl import UniversalCrawlRequest

from app.modules.instagram.services.request_service import CrawlRequestService
from app.modules.instagram.services.crawl_service import CrawlService
from app.modules.instagram.services.crawler import InstagramCrawler

from app.services.universal_crawl_service import universal_crawl_service
from app.services.page_extractor.factory import get_extractor_factory

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = logging.getLogger(__name__)


class OnDemandCrawlWorker(CrawlWorkerBase):
    """온디맨드 크롤링 워커.

    사용자의 즉시 요청을 처리합니다:
    - Instagram Pending 요청 (single_post, single_post_url, feed)
    - Universal Pending 요청

    Attributes:
        max_concurrent_requests: 동시 처리 가능한 최대 요청 수
    """

    def __init__(self, max_concurrent_requests: int = 5):
        """OnDemandCrawlWorker 초기화.

        Args:
            max_concurrent_requests: 동시 처리 가능한 최대 요청 수. 기본 5.
        """
        super().__init__(name="ondemand_worker", worker_type="ondemand")
        self.max_concurrent_requests = max_concurrent_requests
        self._extractor_factory = get_extractor_factory()

    def _get_loop_interval(self) -> float:
        """메인 루프 간격 반환."""
        return 1.0  # 1초마다 체크 (빠른 반응)

    async def _main_loop_iteration(self):
        """메인 루프 한 사이클.

        Pending 요청들을 확인하고 백그라운드 태스크로 디스패치합니다.
        """
        # 완료된 태스크 정리
        self._cleanup_completed_tasks()

        # Instagram Pending 요청 디스패치
        await self._dispatch_instagram_pending_requests()

        # Universal Pending 요청 디스패치
        await self._dispatch_universal_pending_requests()

    def _cleanup_stale_requests(self):
        """오래된 processing 상태 요청 정리."""
        db = SessionLocal()
        try:
            # Instagram 요청 정리
            request_service = CrawlRequestService(db)
            cleaned = request_service.cleanup_stale_processing_requests(timeout_minutes=30)
            if cleaned > 0:
                logger.info(f"[{self.name}] Instagram: {cleaned}개의 오래된 processing 요청 정리 완료")

            # Universal 요청 정리
            cutoff = datetime.now() - timedelta(minutes=30)
            stale_universal = db.query(UniversalCrawlRequest).filter(
                UniversalCrawlRequest.status == "processing",
                UniversalCrawlRequest.started_at < cutoff
            ).all()

            for req in stale_universal:
                req.status = "failed"
                req.error_message = "워커 재시작으로 인한 타임아웃"
                req.completed_at = datetime.now()

            if stale_universal:
                db.commit()
                logger.info(f"[{self.name}] Universal: {len(stale_universal)}개의 오래된 processing 요청 정리 완료")

        except Exception as e:
            logger.error(f"[{self.name}] Stale request 정리 오류: {e}")
        finally:
            db.close()

    # ========== Instagram 요청 처리 ==========

    async def _dispatch_instagram_pending_requests(self):
        """Instagram Pending 요청을 백그라운드 태스크로 디스패치."""
        db = SessionLocal()
        try:
            request_service = CrawlRequestService(db)

            pending_list = request_service.get_pending_requests(limit=self.max_concurrent_requests) \
                if hasattr(request_service, 'get_pending_requests') else []

            if not pending_list:
                pending = request_service.get_pending_request()
                if pending:
                    pending_list = [pending]

            for pending in pending_list:
                task_name = f"ig_{pending.id}"
                if self._is_task_running(task_name):
                    continue

                request_type = getattr(pending, 'request_type', 'feed') or 'feed'

                # feed 타입은 ScheduledCrawlWorker가 처리 (스킵)
                if request_type == "feed":
                    continue

                task = self._create_task(
                    self._execute_instagram_request(pending),
                    task_name
                )
                logger.info(f"[{self.name}] Instagram 크롤링 태스크 시작: request_id={pending.id}, type={request_type}")

        except Exception as e:
            logger.error(f"[{self.name}] Instagram Pending 요청 디스패치 오류: {e}", exc_info=True)
        finally:
            db.close()

    async def _execute_instagram_request(self, request: InstagramCrawlRequest):
        """Instagram 요청 실행 (타입에 따라 분기).

        Args:
            request: 크롤링 요청 객체
        """
        db = SessionLocal()
        try:
            request_service = CrawlRequestService(db)
            crawl_service = CrawlService(db)

            request_service.mark_processing(request.id)

            request_type = getattr(request, 'request_type', 'feed') or 'feed'
            logger.info(f"[{self.name}] Instagram 크롤링 시작: request_id={request.id}, type={request_type}")

            if request_type == "single_post":
                await self._execute_single_post_recrawl(request, db, request_service, crawl_service)
            elif request_type == "single_post_url":
                await self._execute_url_crawl(request, db, request_service, crawl_service)

        except Exception as e:
            logger.error(f"[{self.name}] Instagram 크롤링 실패: request_id={request.id}, error={e}", exc_info=True)
            try:
                request_service = CrawlRequestService(db)
                request_service.mark_failed(request.id, str(e))
            except Exception:
                pass
        finally:
            db.close()

    async def _execute_single_post_recrawl(
        self,
        request: InstagramCrawlRequest,
        db,
        request_service: CrawlRequestService,
        crawl_service: CrawlService,
    ):
        """Instagram 개별 게시물 재크롤링 실행."""
        max_retries = 3
        retry_count = 0

        while retry_count <= max_retries:
            try:
                target_post_id = getattr(request, 'target_post_id', None)
                if not target_post_id:
                    request_service.mark_failed(request.id, "대상 게시물 ID 없음")
                    logger.warning(f"[{self.name}] 대상 게시물 ID 없음: request_id={request.id}")
                    return

                account = db.query(Account).filter(Account.id == request.service_account_id).first()
                if not account:
                    request_service.mark_failed(request.id, "계정을 찾을 수 없음")
                    logger.warning(f"[{self.name}] 계정 없음: service_account_id={request.service_account_id}")
                    return

                self._update_worker_state("recrawling", account.name)

                # BrowserManager를 통한 탭 획득 및 크롤링 실행
                result = await self.execute_with_tab(
                    callback=self._recrawl_with_tab,
                    service_account_id=account.id,
                    target_post_id=target_post_id,
                    account=account,
                    db=db,
                    crawl_service=crawl_service,
                )

                if result["success"]:
                    request.status = "completed"
                    request.processed_at = datetime.now()
                    db.commit()
                    logger.info(f"[{self.name}] 재크롤링 완료: request_id={request.id}, post_id={target_post_id}")
                else:
                    request_service.mark_failed(request.id, result["message"])
                    logger.warning(f"[{self.name}] 재크롤링 실패: {result['message']}")

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

                request_service.mark_failed(request.id, str(e))
                logger.error(f"[{self.name}] 재크롤링 예외: {e}", exc_info=True)
                return

            finally:
                self._update_worker_state("idle")

    async def _recrawl_with_tab(
        self,
        tab: "Page",
        target_post_id: int,
        account: Account,
        db,
        crawl_service: CrawlService,
    ) -> dict:
        """탭을 사용하여 개별 게시물을 재크롤링합니다."""
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

        crawler = InstagramCrawler(tab)
        logger.info(f"[{self.name}] 개별 게시물 재크롤링 시작: post_id={target_post_id}")

        result = await crawl_service.recrawl_single_post(
            crawler=crawler,
            post_id=target_post_id,
        )

        return result

    async def _execute_url_crawl(
        self,
        request: InstagramCrawlRequest,
        db,
        request_service: CrawlRequestService,
        crawl_service: CrawlService,
    ):
        """Instagram URL로 단일 게시물 수집 실행."""
        max_retries = 3
        retry_count = 0

        while retry_count <= max_retries:
            try:
                target_url = getattr(request, 'target_url', None)
                if not target_url:
                    request_service.mark_failed(request.id, "대상 URL 없음")
                    logger.warning(f"[{self.name}] 대상 URL 없음: request_id={request.id}")
                    return

                account = db.query(Account).filter(Account.id == request.service_account_id).first()
                if not account:
                    request_service.mark_failed(request.id, "계정을 찾을 수 없음")
                    logger.warning(f"[{self.name}] 계정 없음: service_account_id={request.service_account_id}")
                    return

                self._update_worker_state("crawling", account.name)

                # BrowserManager를 통한 탭 획득 및 크롤링 실행
                result = await self.execute_with_tab(
                    callback=self._url_crawl_with_tab,
                    service_account_id=account.id,
                    target_url=target_url,
                    account=account,
                    db=db,
                    crawl_service=crawl_service,
                    request=request,
                )

                if result["success"]:
                    request.status = "completed"
                    request.processed_at = datetime.now()
                    db.commit()

                    is_new = result.get("is_new", False)
                    post = result.get("post")
                    post_id = post.id if post else None
                    logger.info(
                        f"[{self.name}] URL 크롤링 완료: request_id={request.id}, "
                        f"post_id={post_id}, is_new={is_new}"
                    )
                else:
                    request_service.mark_failed(request.id, result["message"])
                    logger.warning(f"[{self.name}] URL 크롤링 실패: {result['message']}")

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

                request_service.mark_failed(request.id, str(e))
                logger.error(f"[{self.name}] URL 크롤링 예외: {e}", exc_info=True)
                return

            finally:
                self._update_worker_state("idle")

    async def _url_crawl_with_tab(
        self,
        tab: "Page",
        target_url: str,
        account: Account,
        db,
        crawl_service: CrawlService,
        request: InstagramCrawlRequest,
    ) -> dict:
        """탭을 사용하여 URL 크롤링을 수행합니다."""
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

        crawler = InstagramCrawler(tab)
        logger.info(f"[{self.name}] URL 크롤링 시작: url={target_url}")

        result = await crawl_service.crawl_by_url(
            crawler=crawler,
            url=target_url,
            service_account_id=request.service_account_id,
        )

        return result

    # ========== Universal 요청 처리 ==========

    async def _dispatch_universal_pending_requests(self):
        """Universal Pending 요청을 백그라운드 태스크로 디스패치."""
        db = SessionLocal()
        try:
            pending_list = universal_crawl_service.get_pending_requests(db, limit=self.max_concurrent_requests)

            for pending in pending_list:
                task_name = f"uni_{pending.id}"
                if self._is_task_running(task_name):
                    continue

                task = self._create_task(
                    self._execute_universal_crawl(pending.id),
                    task_name
                )
                logger.info(
                    f"[{self.name}] Universal 크롤링 태스크 시작: "
                    f"request_id={pending.id}, url_type={pending.url_type}"
                )

        except Exception as e:
            logger.error(f"[{self.name}] Universal Pending 요청 디스패치 오류: {e}", exc_info=True)
        finally:
            db.close()

    async def _execute_universal_crawl(self, request_id: int):
        """Universal 크롤링 실행."""
        db = SessionLocal()
        try:
            request = universal_crawl_service.get_request(db, request_id)
            if not request:
                logger.warning(f"[{self.name}] Universal 요청 없음: request_id={request_id}")
                return

            # processing 상태로 변경
            universal_crawl_service.mark_processing(db, request_id)
            self._update_worker_state("universal_crawling")

            logger.info(f"[{self.name}] Universal 크롤링 시작: request_id={request_id}, url={request.url}")

            # BrowserManager를 통한 탭 획득 및 크롤링 실행
            await self.execute_with_tab(
                callback=self._universal_crawl_with_tab,
                service_account_id=request.service_account_id,
                request=request,
                db=db,
            )

        except Exception as e:
            logger.error(f"[{self.name}] Universal 크롤링 실패: request_id={request_id}, error={e}", exc_info=True)
            try:
                universal_crawl_service.mark_failed(db, request_id, str(e))
            except Exception:
                pass
        finally:
            self._update_worker_state("idle")
            db.close()

    async def _universal_crawl_with_tab(
        self,
        tab: "Page",
        request: UniversalCrawlRequest,
        db,
    ):
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
                universal_crawl_service.mark_failed(db, request.id, extracted.error or "추출 실패")
                logger.warning(f"[{self.name}] Universal 크롤링 추출 실패: {extracted.error}")
                return

            # 결과 저장
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

            # 완료 처리
            universal_crawl_service.mark_completed(db, request.id, crawled_page.id)

            logger.info(
                f"[{self.name}] Universal 크롤링 완료: request_id={request.id}, "
                f"page_id={crawled_page.id}, title={crawled_page.title[:50] if crawled_page.title else None}"
            )

            # auto_analyze가 True이면 AI 분석 요청 생성
            if request.auto_analyze:
                try:
                    from app.services.universal_crawl_analyzer import UniversalCrawlAnalyzerService
                    analyzer = UniversalCrawlAnalyzerService(db)
                    analyzer.create_analysis_request(crawled_page.id, requested_by="worker")
                    logger.info(f"[{self.name}] AI 분석 요청 생성: page_id={crawled_page.id}")
                except Exception as e:
                    logger.warning(f"[{self.name}] AI 분석 요청 생성 실패: {e}")

        except Exception as e:
            logger.error(f"[{self.name}] Universal 크롤링 오류: {e}", exc_info=True)
            universal_crawl_service.mark_failed(db, request.id, str(e))

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
