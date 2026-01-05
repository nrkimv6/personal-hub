"""홈플러스 문화센터 크롤러.

JavaScript 렌더링이 필요한 페이지이므로 Playwright를 사용합니다.
"""

import asyncio
import logging
import re
from datetime import date, datetime
from typing import Any, List, Optional

from bs4 import BeautifulSoup, Tag
from playwright.async_api import Page, async_playwright

from app.models.activity import ActivityCenter
from app.modules.activity.crawlers.base import (
    BaseCrawler,
    CrawlResult,
    OnCourseCollected,
)
from app.modules.activity.models.schemas import CourseImportItem

logger = logging.getLogger("activity.crawler.homeplus")


class HomeplusCrawler(BaseCrawler):
    """홈플러스 문화센터 크롤러 (Playwright 기반).

    JavaScript로 렌더링되는 페이지에서 강좌 목록을 수집합니다.
    """

    CRAWLER_ID = "homeplus"

    # 기본 URL
    BASE_URL = "https://mschool.homeplus.co.kr"
    SEARCH_URL = f"{BASE_URL}/Lecture/SearchResult"

    # 기본 선택자
    DEFAULT_SELECTORS = {
        "item": 'li[id^="liLecture_"]',
        "branch": ".office_name",
        "category": ".lecture_sybtype",
        "open_date": ".title_1",
        "name": ".title_2",
        "info_items": ".sub_info_wrap .sub_txt",
        "next_page": ".pagination .next",
        "page_numbers": ".pagination a[data-page]",
    }

    # 카테고리 매핑
    CATEGORY_MAP = {
        "요리": "cooking",
        "미술": "art",
        "음악": "music",
        "운동": "exercise",
        "건강": "exercise",
        "어학": "language",
        "자격증": "certificate",
        "취미": "hobby",
        "교양": "hobby",
        "정규": "other",
        "단기": "other",
    }

    def __init__(
        self,
        center: ActivityCenter,
        page: Optional[Page] = None,
    ):
        super().__init__(center, page)
        self._selectors = {**self.DEFAULT_SELECTORS, **self.config.selectors}
        self._own_browser = False  # 자체 브라우저 생성 여부

    async def crawl(
        self,
        on_course_collected: Optional[OnCourseCollected] = None,
    ) -> CrawlResult:
        """홈플러스 강좌 크롤링 실행."""
        started_at = datetime.now()
        all_courses: List[CourseImportItem] = []

        logger.info(f"[HomeplusCrawler] 크롤링 시작: {self.center.name}")

        # Playwright 페이지 준비
        playwright_ctx = None
        browser = None

        try:
            if self.page is None:
                # 자체 브라우저 생성
                playwright_ctx = await async_playwright().start()
                browser = await playwright_ctx.chromium.launch(headless=True)
                self.page = await browser.new_page()
                self._own_browser = True

            # 페이지 로드
            logger.info("[HomeplusCrawler] 페이지 로드 중...")
            await self.page.goto(
                self.SEARCH_URL,
                wait_until="networkidle",
                timeout=60000,
            )
            await self.page.wait_for_timeout(3000)

            # 첫 페이지 파싱
            page_num = 1
            max_pages = self.config.max_pages

            while page_num <= max_pages:
                self._update_progress(current_page=page_num)

                try:
                    # 현재 페이지 HTML 가져오기
                    html = await self.page.content()
                    courses = self._parse_page(html)

                    if not courses:
                        logger.info(
                            f"[HomeplusCrawler] 페이지 {page_num}: 강좌 없음, 종료"
                        )
                        break

                    for course in courses:
                        all_courses.append(course)
                        self._update_progress(collected=len(all_courses))

                        if on_course_collected:
                            try:
                                await on_course_collected(course)
                            except Exception as e:
                                logger.error(
                                    f"[HomeplusCrawler] 저장 콜백 오류: {e}"
                                )

                    logger.info(
                        f"[HomeplusCrawler] 페이지 {page_num}: "
                        f"{len(courses)}개 수집 (누적: {len(all_courses)})"
                    )

                    # 다음 페이지로 이동
                    has_next = await self._go_to_next_page()
                    if not has_next:
                        logger.info("[HomeplusCrawler] 마지막 페이지 도달")
                        break

                    page_num += 1
                    await asyncio.sleep(self.config.delay_between_pages)

                except Exception as e:
                    error_msg = f"페이지 {page_num} 크롤링 실패: {e}"
                    logger.error(f"[HomeplusCrawler] {error_msg}")
                    self._update_progress(error=error_msg)
                    break

            status = "completed" if not self._progress.errors else "partial"

        except Exception as e:
            logger.error(f"[HomeplusCrawler] 크롤링 실패: {e}", exc_info=True)
            return CrawlResult(
                courses=all_courses,
                found=len(all_courses),
                status="failed",
                error_message=str(e),
                started_at=started_at,
                completed_at=datetime.now(),
                progress=self._progress,
            )

        finally:
            # 자체 생성한 브라우저 정리
            if self._own_browser:
                if browser:
                    await browser.close()
                if playwright_ctx:
                    await playwright_ctx.stop()
                self.page = None

        logger.info(f"[HomeplusCrawler] 크롤링 완료: {len(all_courses)}개 수집")

        return CrawlResult(
            courses=all_courses,
            found=len(all_courses),
            status=status,
            started_at=started_at,
            completed_at=datetime.now(),
            progress=self._progress,
        )

    async def _go_to_next_page(self) -> bool:
        """다음 페이지로 이동. 성공 시 True 반환."""
        try:
            # 다음 페이지 버튼 찾기
            next_btn = await self.page.query_selector(self._selectors["next_page"])
            if next_btn:
                is_disabled = await next_btn.get_attribute("disabled")
                if not is_disabled:
                    await next_btn.click()
                    await self.page.wait_for_timeout(2000)
                    return True

            # 또는 페이지네이션 스크롤 (무한 스크롤 방식인 경우)
            # 스크롤 후 새 아이템이 로드되는지 확인
            current_count = len(
                await self.page.query_selector_all(self._selectors["item"])
            )

            await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await self.page.wait_for_timeout(2000)

            new_count = len(
                await self.page.query_selector_all(self._selectors["item"])
            )

            return new_count > current_count

        except Exception as e:
            logger.warning(f"[HomeplusCrawler] 다음 페이지 이동 실패: {e}")
            return False

    def _parse_page(self, html: str) -> List[CourseImportItem]:
        """HTML에서 강좌 목록 파싱."""
        soup = BeautifulSoup(html, "html.parser")
        items = soup.select(self._selectors["item"])

        courses = []
        for item in items:
            course = self._parse_course(item)
            if course:
                courses.append(course)

        return courses

    def _parse_course(self, raw_data: Any) -> Optional[CourseImportItem]:
        """HTML 요소에서 CourseImportItem 추출."""
        if not isinstance(raw_data, Tag):
            return None

        try:
            item = raw_data

            # 강좌 ID
            item_id = item.get("id", "")
            source_id = item_id.replace("liLecture_", "") if item_id else None

            # 지점명
            branch_elem = item.select_one(self._selectors["branch"])
            branch_name = (
                branch_elem.get_text(strip=True) if branch_elem else "홈플러스"
            )

            # 카테고리
            category_elem = item.select_one(self._selectors["category"])
            raw_category = (
                category_elem.get_text(strip=True) if category_elem else None
            )
            category = self._map_category(raw_category)

            # 개강일
            open_date_elem = item.select_one(self._selectors["open_date"])
            open_date_text = (
                open_date_elem.get_text(strip=True) if open_date_elem else None
            )

            # 강좌명
            name_elems = item.select(self._selectors["name"])
            name = name_elems[0].get_text(strip=True) if name_elems else "알 수 없음"
            subtitle = (
                name_elems[1].get_text(strip=True) if len(name_elems) > 1 else None
            )

            # 부가 정보 (시간, 가격, 기간, 강사)
            info_elems = item.select(self._selectors["info_items"])
            time_text = None
            fee = None
            date_range_text = None
            instructor = None

            for idx, info in enumerate(info_elems):
                text = info.get_text(strip=True)
                if idx == 0:
                    time_text = text
                elif idx == 1:
                    fee = self._parse_fee(text)
                elif idx == 2:
                    date_range_text = text
                elif idx == 3:
                    instructor = text.replace("강사", "").strip()

            # 시간 파싱
            day_of_week, time_start, time_end = self._parse_schedule(time_text)

            # 날짜 파싱
            course_start = self._parse_open_date(open_date_text)
            course_start_from_range, course_end = self._parse_date_range(
                date_range_text
            )
            if not course_start and course_start_from_range:
                course_start = course_start_from_range

            # 회차
            total_sessions = self._parse_sessions(
                info_elems[1].get_text(strip=True) if len(info_elems) > 1 else None
            )

            return CourseImportItem(
                center_name=f"홈플러스 {branch_name}",
                center_type="mart",
                center_website=self.BASE_URL,
                source_id=source_id,
                name=name,
                description=subtitle,
                source_url=(
                    f"{self.BASE_URL}/Lecture/Detail/{source_id}"
                    if source_id
                    else None
                ),
                category=category,
                subcategory=raw_category,
                fee=fee,
                course_start=course_start,
                course_end=course_end,
                day_of_week=day_of_week,
                time_start=time_start,
                time_end=time_end,
                total_sessions=total_sessions,
                instructor_name=instructor,
            )

        except Exception as e:
            logger.warning(f"[HomeplusCrawler] 강좌 파싱 실패: {e}")
            return None

    def _map_category(self, raw: str) -> str:
        """카테고리 매핑."""
        if not raw:
            return "other"
        for key, mapped in self.CATEGORY_MAP.items():
            if key in raw:
                return mapped
        return "other"

    def _parse_fee(self, text: str) -> Optional[int]:
        """가격 파싱."""
        if not text:
            return None
        match = re.search(r"([\d,]+)\s*원", text)
        if match:
            return int(match.group(1).replace(",", ""))
        return None

    def _parse_schedule(self, text: str) -> tuple:
        """시간 파싱."""
        if not text:
            return (None, None, None)

        day_match = re.search(r"([월화수목금토일,\s]+)", text)
        day_of_week = day_match.group(1).strip() if day_match else None

        time_match = re.search(r"(\d{1,2}:\d{2})\s*[~\-]\s*(\d{1,2}:\d{2})", text)
        if time_match:
            return (day_of_week, time_match.group(1), time_match.group(2))

        return (day_of_week, None, None)

    def _parse_open_date(self, text: str) -> Optional[date]:
        """개강일 파싱."""
        if not text:
            return None

        match = re.search(r"(\d{1,2})[/.](\d{1,2})", text)
        if match:
            month = int(match.group(1))
            day = int(match.group(2))
            year = datetime.now().year

            if month < datetime.now().month - 1:
                year += 1

            try:
                return date(year, month, day)
            except ValueError:
                return None

        return None

    def _parse_date_range(self, text: str) -> tuple:
        """기간 파싱."""
        if not text:
            return (None, None)

        matches = re.findall(r"(\d{4})[./](\d{1,2})[./](\d{1,2})", text)
        if len(matches) >= 2:
            try:
                start = date(int(matches[0][0]), int(matches[0][1]), int(matches[0][2]))
                end = date(int(matches[1][0]), int(matches[1][1]), int(matches[1][2]))
                return (start, end)
            except ValueError:
                pass
        elif len(matches) == 1:
            try:
                start = date(int(matches[0][0]), int(matches[0][1]), int(matches[0][2]))
                return (start, None)
            except ValueError:
                pass

        return (None, None)

    def _parse_sessions(self, text: str) -> Optional[int]:
        """회차 파싱."""
        if not text:
            return None
        match = re.search(r"(\d+)\s*회", text)
        if match:
            return int(match.group(1))
        return None
