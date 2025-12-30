"""
Google 검색 큐 처리 워커.

API 서버에서 추가된 검색 요청을 큐에서 가져와 처리합니다.
Session 0 (NSSM 서비스)에서는 브라우저 사용이 불가하므로
사용자 세션의 워커에서 처리합니다.

실행 방법:
    WorkerOrchestrator에서 등록하여 실행
    (app/worker/main.py 참조)

주요 기능:
    - google_search_queue 테이블에서 pending 요청 조회
    - GoogleSearchCrawler를 사용하여 검색 수행
    - 결과를 google_search_history, google_search_results에 저장
    - saved_search 연결 시 마지막 실행 정보 업데이트
"""
import asyncio
import logging
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from app.shared.worker.base_worker import BaseWorker
from app.database import SessionLocal
from app.models.google_search import (
    GoogleSearchQueue,
    GoogleSearchHistory,
    GoogleSearchResult,
    GoogleSavedSearch,
)
from app.modules.google_search.services.crawler import (
    GoogleSearchCrawler,
    CrawlOptions,
    CaptchaDetectedError,
)

if TYPE_CHECKING:
    from playwright.async_api import Page
    from app.shared.browser.browser_manager import BrowserManager

logger = logging.getLogger(__name__)


class GoogleSearchWorker(BaseWorker):
    """Google 검색 큐 처리 워커.

    큐에서 pending 상태의 검색 요청을 가져와 처리합니다.
    BrowserManager를 통해 브라우저 탭을 획득하여 검색을 수행합니다.

    Attributes:
        browser_manager: BrowserManager 참조
    """

    def __init__(self, browser_manager: Optional["BrowserManager"] = None):
        """GoogleSearchWorker 초기화.

        Args:
            browser_manager: 외부에서 주입받을 BrowserManager
        """
        super().__init__(
            name="google_search_worker",
            browser_manager=browser_manager
        )

    def _get_loop_interval(self) -> float:
        """메인 루프 간격 반환.

        Returns:
            float: 1초 (빠른 반응)
        """
        return 1.0

    async def _main_loop_iteration(self):
        """메인 루프 한 사이클.

        큐에서 pending 요청을 조회하고 처리합니다.
        """
        await self._safe_execute("process_pending_queue", self._process_pending_queue)

    async def _process_pending_queue(self):
        """pending 상태의 검색 요청을 처리."""
        db = SessionLocal()
        try:
            # pending 요청 조회 (한 번에 하나씩 처리)
            pending = (
                db.query(GoogleSearchQueue)
                .filter(GoogleSearchQueue.status == "pending")
                .order_by(GoogleSearchQueue.created_at)
                .first()
            )

            if not pending:
                return

            logger.info(
                f"[{self.name}] Processing search request: "
                f"search_id={pending.search_id}, query={pending.query}"
            )

            # processing 상태로 변경
            pending.status = "processing"
            pending.started_at = datetime.now()
            db.commit()

            # 검색 실행
            await self._execute_search(pending, db)

        except Exception as e:
            logger.error(f"[{self.name}] Error processing queue: {e}", exc_info=True)
        finally:
            db.close()

    async def _execute_search(self, queue_item: GoogleSearchQueue, db):
        """검색 요청 실행.

        Args:
            queue_item: 큐 아이템
            db: DB 세션
        """
        try:
            # BrowserManager를 통해 탭 획득
            if not self.browser or not self.browser.is_initialized:
                raise RuntimeError("BrowserManager가 초기화되지 않았습니다.")

            # 컨텍스트 획득
            context = await self.browser.get_context(queue_item.service_account_id)
            page = await context.new_page()

            try:
                # 크롤러 생성 및 검색 실행
                crawler = GoogleSearchCrawler(page, db)
                options = CrawlOptions(
                    max_pages=queue_item.max_pages or 1,
                    date_filter=queue_item.date_filter,
                )

                # 기존 검색 실행 (히스토리, 결과 저장은 크롤러 내부에서 처리)
                # 단, search_id를 queue_item의 것으로 사용해야 함
                result = await self._search_with_queue_id(
                    crawler, queue_item, options, db
                )

                # 완료 처리
                queue_item.status = "completed"
                queue_item.completed_at = datetime.now()
                db.commit()

                # saved_search 연결 시 업데이트
                if queue_item.saved_search_id:
                    self._update_saved_search(
                        db,
                        queue_item.saved_search_id,
                        queue_item.search_id,
                        result.total_results,
                    )

                logger.info(
                    f"[{self.name}] Search completed: "
                    f"search_id={queue_item.search_id}, "
                    f"total_results={result.total_results}"
                )

            finally:
                await page.close()

        except CaptchaDetectedError as e:
            logger.warning(
                f"[{self.name}] CAPTCHA detected: search_id={queue_item.search_id}"
            )
            queue_item.status = "failed"
            queue_item.error_message = "CAPTCHA 감지됨. 수동 해결이 필요합니다."
            queue_item.completed_at = datetime.now()
            db.commit()

        except Exception as e:
            logger.error(
                f"[{self.name}] Search failed: search_id={queue_item.search_id}, error={e}",
                exc_info=True
            )
            queue_item.status = "failed"
            queue_item.error_message = str(e)
            queue_item.completed_at = datetime.now()
            db.commit()

    async def _search_with_queue_id(
        self,
        crawler: GoogleSearchCrawler,
        queue_item: GoogleSearchQueue,
        options: CrawlOptions,
        db,
    ):
        """큐 아이템의 search_id를 사용하여 검색 수행.

        크롤러의 기본 search() 메서드는 새 UUID를 생성하므로,
        큐의 search_id를 사용하도록 직접 구현합니다.

        Args:
            crawler: GoogleSearchCrawler 인스턴스
            queue_item: 큐 아이템
            options: 크롤링 옵션
            db: DB 세션

        Returns:
            CrawlResult: 검색 결과
        """
        from app.modules.google_search.services.crawler import (
            SearchResultData,
            CrawlResult,
            DATE_FILTERS,
        )

        search_id = queue_item.search_id
        query = queue_item.query
        started_at = datetime.now()
        all_results = []

        # 날짜 필터 변환
        tbs = DATE_FILTERS.get(options.date_filter) if options.date_filter else None

        logger.info(
            f"[{self.name}] Starting search: query='{query}', "
            f"max_pages={options.max_pages}, date_filter={options.date_filter}"
        )

        for page_num in range(options.max_pages):
            start = page_num * 10

            # URL 생성 및 페이지 이동
            url = crawler._build_url(query, start, tbs)

            await crawler.page.goto(url, wait_until="domcontentloaded")
            await asyncio.sleep(1.5)

            # 검색 영역 대기
            try:
                from app.modules.google_search.utils.selectors import SELECTORS
                await crawler.page.wait_for_selector(
                    SELECTORS["search_area"],
                    timeout=10000
                )
            except Exception:
                logger.warning(f"[{self.name}] Search area not found on page {page_num + 1}")

            # CAPTCHA 체크
            if await crawler._check_captcha():
                raise CaptchaDetectedError("CAPTCHA 감지됨")

            # 결과 수집
            results = await crawler._scrape_results(page_num + 1)

            if not results:
                logger.info(f"[{self.name}] No results on page {page_num + 1}, stopping")
                break

            all_results.extend(results)

            # 다음 페이지 확인
            if page_num < options.max_pages - 1:
                has_next = await crawler._has_next_page()
                if not has_next:
                    break

                # 딜레이
                import random
                delay = random.uniform(options.min_delay, options.max_delay)
                await asyncio.sleep(delay)

        completed_at = datetime.now()

        # 히스토리 저장
        history = GoogleSearchHistory(
            search_id=search_id,
            query=query,
            date_filter=options.date_filter,
            max_pages=options.max_pages,
            status="completed",
            total_results=len(all_results),
            started_at=started_at,
            completed_at=completed_at,
        )
        db.add(history)

        # 결과 저장
        for result in all_results:
            record = GoogleSearchResult(
                search_id=search_id,
                query=query,
                rank=result.rank,
                title=result.title,
                url=result.url,
                display_url=result.display_url,
                snippet=result.snippet,
                publish_date=result.publish_date,
                date_filter=options.date_filter,
                page_number=result.page_number,
            )
            db.add(record)

        db.commit()

        return CrawlResult(
            search_id=search_id,
            query=query,
            results=all_results,
            total_results=len(all_results),
            status="completed",
            started_at=started_at,
            completed_at=completed_at,
        )

    def _update_saved_search(
        self,
        db,
        saved_search_id: int,
        search_id: str,
        total_results: int,
    ):
        """저장된 검색 조건 업데이트.

        Args:
            db: DB 세션
            saved_search_id: 저장된 검색 ID
            search_id: 검색 세션 ID
            total_results: 결과 수
        """
        try:
            saved = db.query(GoogleSavedSearch).filter_by(id=saved_search_id).first()
            if saved:
                saved.last_search_id = search_id
                saved.last_run_at = datetime.now()
                saved.last_result_count = total_results
                saved.updated_at = datetime.now()
                db.commit()
                logger.debug(
                    f"[{self.name}] Updated saved search: id={saved_search_id}"
                )
        except Exception as e:
            logger.warning(
                f"[{self.name}] Failed to update saved search: {e}"
            )
