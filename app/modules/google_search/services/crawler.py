"""
Google 검색 크롤러 서비스

Playwright를 사용하여 Google 검색 결과를 수집합니다.
"""

import asyncio
import logging
import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any
from urllib.parse import quote

from playwright.async_api import Page
from sqlalchemy.orm import Session

from app.modules.google_search.utils.selectors import (
    SELECTORS,
    DATE_FILTERS,
    SCRAPE_RESULTS_JS,
)

logger = logging.getLogger("google_search.crawler")


@dataclass
class CrawlOptions:
    """크롤링 옵션."""
    max_pages: int = 1          # 수집할 페이지 수 (1-10)
    date_filter: Optional[str] = None  # 1h, 24h, 1w, 1m, 1y
    min_delay: float = 2.0      # 최소 대기 시간 (초)
    max_delay: float = 5.0      # 최대 대기 시간 (초)
    search_params: Optional[Dict[str, Any]] = None  # 추가 파라미터 (lr, cr, as_sitesearch, num)


@dataclass
class SearchResultData:
    """검색 결과 데이터."""
    rank: int
    title: str
    url: str
    display_url: Optional[str] = None
    snippet: Optional[str] = None
    publish_date: Optional[str] = None
    page_number: int = 1


@dataclass
class CrawlResult:
    """크롤링 결과."""
    search_id: str
    query: str
    results: List[SearchResultData]
    total_results: int
    status: str  # completed, failed, captcha
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class CaptchaDetectedError(Exception):
    """CAPTCHA 감지 예외."""
    pass


class GoogleSearchCrawler:
    """Google 검색 크롤러.

    Playwright Page 객체를 사용하여 Google 검색을 수행하고
    결과를 수집합니다.
    """

    def __init__(self, page: Page, db: Optional[Session] = None):
        """
        Args:
            page: Playwright Page 객체
            db: SQLAlchemy 세션 (결과 저장용)
        """
        self.page = page
        self.db = db

    async def search(
        self,
        query: str,
        options: Optional[CrawlOptions] = None
    ) -> CrawlResult:
        """Google 검색 수행 및 결과 수집.

        Args:
            query: 검색 키워드
            options: 크롤링 옵션

        Returns:
            CrawlResult: 검색 결과

        Raises:
            CaptchaDetectedError: CAPTCHA 감지 시
        """
        if options is None:
            options = CrawlOptions()

        search_id = str(uuid.uuid4())
        started_at = datetime.now()
        all_results: List[SearchResultData] = []

        # 날짜 필터 변환
        tbs = DATE_FILTERS.get(options.date_filter) if options.date_filter else None

        logger.info(
            f"Starting Google search: query='{query}', "
            f"max_pages={options.max_pages}, date_filter={options.date_filter}"
        )

        try:
            for page_num in range(options.max_pages):
                start = page_num * 10

                # URL 생성 및 페이지 이동
                url = self._build_url(query, start, tbs, options.search_params)
                logger.debug(f"Navigating to page {page_num + 1}: {url}")

                await self.page.goto(url, wait_until="domcontentloaded")

                # 페이지 로드 대기
                await asyncio.sleep(1.5)

                # 검색 영역 대기
                try:
                    await self.page.wait_for_selector(
                        SELECTORS["search_area"],
                        timeout=10000
                    )
                except Exception:
                    logger.warning(f"Search area not found on page {page_num + 1}")

                # CAPTCHA 체크
                if await self._check_captcha():
                    logger.error("CAPTCHA detected!")
                    raise CaptchaDetectedError("CAPTCHA 감지됨. 수동 해결 필요.")

                # 결과 수집
                results = await self._scrape_results(page_num + 1)

                if not results:
                    logger.info(f"No results on page {page_num + 1}, stopping")
                    break

                all_results.extend(results)
                logger.debug(f"Page {page_num + 1}: collected {len(results)} results")

                # 다음 페이지 존재 확인
                if page_num < options.max_pages - 1:
                    has_next = await self._has_next_page()
                    if not has_next:
                        logger.info("No more pages available")
                        break

                    # 속도 제한 (랜덤 딜레이)
                    delay = random.uniform(options.min_delay, options.max_delay)
                    logger.debug(f"Waiting {delay:.1f}s before next page")
                    await asyncio.sleep(delay)

            completed_at = datetime.now()

            # DB 저장 (세션이 있는 경우)
            if self.db:
                self._save_results(
                    search_id=search_id,
                    query=query,
                    date_filter=options.date_filter,
                    results=all_results,
                    started_at=started_at,
                    completed_at=completed_at,
                    max_pages=options.max_pages,
                )

            logger.info(
                f"Search completed: query='{query}', "
                f"total_results={len(all_results)}"
            )

            return CrawlResult(
                search_id=search_id,
                query=query,
                results=all_results,
                total_results=len(all_results),
                status="completed",
                started_at=started_at,
                completed_at=completed_at,
            )

        except CaptchaDetectedError:
            raise

        except Exception as e:
            logger.error(f"Search failed: {e}")
            return CrawlResult(
                search_id=search_id,
                query=query,
                results=all_results,
                total_results=len(all_results),
                status="failed",
                error_message=str(e),
                started_at=started_at,
                completed_at=datetime.now(),
            )

    def _build_url(
        self,
        query: str,
        start: int = 0,
        tbs: Optional[str] = None,
        search_params: Optional[Dict[str, Any]] = None,
    ) -> str:
        """검색 URL 생성.

        Args:
            query: 검색 키워드
            start: 시작 위치 (0, 10, 20, ...)
            tbs: 날짜 필터 (qdr:h, qdr:d, qdr:w, qdr:m, qdr:y)
            search_params: 추가 파라미터 (lr, cr, as_sitesearch, num)

        Returns:
            Google 검색 URL
        """
        from app.modules.google_search.utils.selectors import ALLOWED_SEARCH_PARAMS

        # as_sitesearch가 있으면 site: 연산자를 쿼리에 prepend (URL 파라미터보다 엄격하게 필터됨)
        effective_query = query
        if search_params and search_params.get("as_sitesearch"):
            site = search_params["as_sitesearch"]
            effective_query = f"site:{site} {query}"

        # exclude_keywords가 있으면 - 연산자로 쿼리에 append
        if search_params and search_params.get("exclude_keywords"):
            for kw in search_params["exclude_keywords"]:
                if kw and kw.strip():
                    effective_query += f" -{kw.strip()}"

        # hl=ko로 한국어 결과 요청
        url = f"https://www.google.com/search?q={quote(effective_query)}&hl=ko"

        if start > 0:
            url += f"&start={start}"

        if tbs:
            url += f"&tbs={tbs}"

        # 추가 검색 파라미터 (허용 키만, as_sitesearch/exclude_keywords는 쿼리에 반영됐으므로 스킵)
        if search_params:
            for key, value in search_params.items():
                if key in ("as_sitesearch", "exclude_keywords"):
                    continue
                if key in ALLOWED_SEARCH_PARAMS and value:
                    url += f"&{quote(str(key))}={quote(str(value))}"

        return url

    async def _check_captcha(self) -> bool:
        """CAPTCHA 감지.

        Returns:
            CAPTCHA가 감지되면 True
        """
        try:
            captcha = await self.page.locator(SELECTORS["captcha"]).count()
            return captcha > 0
        except Exception:
            return False

    async def _has_next_page(self) -> bool:
        """다음 페이지 존재 확인.

        Returns:
            다음 페이지가 있으면 True
        """
        try:
            next_button = await self.page.locator(SELECTORS["next_button"]).count()
            return next_button > 0
        except Exception:
            return False

    async def _scrape_results(self, page_number: int) -> List[SearchResultData]:
        """페이지에서 검색 결과 추출.

        Args:
            page_number: 현재 페이지 번호 (1부터 시작)

        Returns:
            검색 결과 리스트
        """
        try:
            # JavaScript로 결과 추출
            raw_results = await self.page.evaluate(SCRAPE_RESULTS_JS)

            if not raw_results:
                return []

            # 페이지 번호 기준으로 rank 조정
            results = []
            for i, result in enumerate(raw_results):
                adjusted_rank = (page_number - 1) * 10 + result.get("rank", i + 1)

                results.append(SearchResultData(
                    rank=adjusted_rank,
                    title=result.get("title", ""),
                    url=result.get("url", ""),
                    display_url=result.get("display_url"),
                    snippet=result.get("snippet"),
                    publish_date=result.get("publish_date"),
                    page_number=page_number,
                ))

            return results

        except Exception as e:
            logger.error(f"Failed to scrape results: {e}")
            return []

    def _save_results(
        self,
        search_id: str,
        query: str,
        date_filter: Optional[str],
        results: List[SearchResultData],
        started_at: datetime,
        completed_at: datetime,
        max_pages: int,
    ) -> None:
        """결과를 DB에 저장.

        Args:
            search_id: 검색 세션 ID
            query: 검색 키워드
            date_filter: 날짜 필터
            results: 검색 결과 리스트
            started_at: 검색 시작 시간
            completed_at: 검색 완료 시간
            max_pages: 요청한 최대 페이지 수
        """
        if not self.db:
            return

        from app.models.google_search import GoogleSearchHistory, GoogleSearchResult

        try:
            # 히스토리 저장
            history = GoogleSearchHistory(
                search_id=search_id,
                query=query,
                date_filter=date_filter,
                max_pages=max_pages,
                status="completed",
                total_results=len(results),
                started_at=started_at,
                completed_at=completed_at,
            )
            self.db.add(history)

            # 결과 저장
            for result in results:
                record = GoogleSearchResult(
                    search_id=search_id,
                    query=query,
                    rank=result.rank,
                    title=result.title,
                    url=result.url,
                    display_url=result.display_url,
                    snippet=result.snippet,
                    publish_date=result.publish_date,
                    date_filter=date_filter,
                    page_number=result.page_number,
                )
                self.db.add(record)

            self.db.commit()
            logger.debug(f"Saved {len(results)} results to DB")

        except Exception as e:
            logger.error(f"Failed to save results: {e}")
            self.db.rollback()
            raise


class GoogleSearchService:
    """Google 검색 서비스.

    ContextManager와 연동하여 검색을 수행합니다.
    """

    def __init__(self, context_manager, db: Session):
        """
        Args:
            context_manager: 브라우저 컨텍스트 매니저
            db: SQLAlchemy 세션
        """
        self.context_manager = context_manager
        self.db = db

    async def search(
        self,
        query: str,
        date_filter: Optional[str] = None,
        max_pages: int = 1,
        service_account_id: Optional[int] = None,
    ) -> CrawlResult:
        """검색 수행.

        Args:
            query: 검색 키워드
            date_filter: 날짜 필터 (1h, 24h, 1w, 1m, 1y)
            max_pages: 수집할 페이지 수 (최대 10)
            service_account_id: 브라우저 프로필 ID

        Returns:
            CrawlResult: 검색 결과
        """
        # 페이지 수 제한
        max_pages = min(max(1, max_pages), 10)

        # 브라우저 컨텍스트 획득 (account_id가 None이면 기본 계정 사용)
        context = await self.context_manager.get_or_create_context(service_account_id)
        page = await context.new_page()

        try:
            crawler = GoogleSearchCrawler(page, self.db)
            options = CrawlOptions(
                max_pages=max_pages,
                date_filter=date_filter,
            )
            return await crawler.search(query, options)

        finally:
            await page.close()

    async def run_saved_search(self, saved_id: int) -> CrawlResult:
        """저장된 검색 조건으로 검색 실행.

        Args:
            saved_id: 저장된 검색 조건 ID

        Returns:
            CrawlResult: 검색 결과

        Raises:
            ValueError: 저장된 검색을 찾을 수 없는 경우
        """
        from app.models.google_search import GoogleSavedSearch

        saved = self.db.query(GoogleSavedSearch).filter_by(id=saved_id).first()
        if not saved:
            raise ValueError(f"Saved search not found: {saved_id}")

        # 검색 실행
        result = await self.search(
            query=saved.query,
            date_filter=saved.date_filter,
            max_pages=saved.max_pages,
            service_account_id=saved.service_account_id,
        )

        # 저장된 검색 조건 업데이트
        if result.status == "completed":
            saved.last_search_id = result.search_id
            saved.last_run_at = datetime.now()
            saved.last_result_count = result.total_results
            saved.updated_at = datetime.now()
            self.db.commit()

        return result
