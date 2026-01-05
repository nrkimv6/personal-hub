"""홈플러스 문화센터 크롤러.

Svelte SSR 페이지에서 강좌 목록을 수집합니다.
동적 렌더링이 필요 없으므로 httpx로 직접 요청합니다.
"""

import asyncio
import logging
import re
from datetime import date, datetime
from typing import Any, List, Optional

import httpx
from bs4 import BeautifulSoup, Tag

from app.models.activity import ActivityCenter
from app.modules.activity.crawlers.base import (
    BaseCrawler,
    CrawlResult,
    OnCourseCollected,
)
from app.modules.activity.models.schemas import CourseImportItem

logger = logging.getLogger("activity.crawler.homeplus")


class HomeplusCrawler(BaseCrawler):
    """홈플러스 문화센터 크롤러 (SSR HTML 파싱).

    Svelte SSR 페이지에서 강좌 목록을 수집합니다.
    """

    CRAWLER_ID = "homeplus"

    # 기본 URL
    BASE_URL = "https://mschool.homeplus.co.kr"
    SEARCH_URL = f"{BASE_URL}/Lecture/SearchResult"

    # 기본 선택자 (crawl_config로 오버라이드 가능)
    DEFAULT_SELECTORS = {
        "list_container": ".search_result_list",
        "item": 'li[id^="liLecture_"]',
        "branch": ".office_name",
        "category": ".lecture_sybtype",
        "open_date": ".title_1",
        "name": ".title_2:first-of-type",
        "subtitle": ".title_2:nth-of-type(2)",
        "info_items": ".sub_info_wrap .sub_txt",
        "total_count": ".total_count",
    }

    # 카테고리 매핑 (홈플러스 → 표준)
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
        page=None,
    ):
        super().__init__(center, page)
        self._selectors = {**self.DEFAULT_SELECTORS, **self.config.selectors}
        self._client: Optional[httpx.AsyncClient] = None

    async def crawl(
        self,
        on_course_collected: Optional[OnCourseCollected] = None,
    ) -> CrawlResult:
        """홈플러스 강좌 크롤링 실행."""
        started_at = datetime.now()
        all_courses: List[CourseImportItem] = []

        logger.info(f"[HomeplusCrawler] 크롤링 시작: {self.center.name}")

        async with httpx.AsyncClient(
            timeout=self.config.timeout,
            follow_redirects=True,
        ) as client:
            self._client = client

            try:
                # 1. 첫 페이지에서 총 개수 파악
                first_page_html = await self._fetch_page(1)
                total_count = self._extract_total_count(first_page_html)
                total_pages = (total_count // self.config.page_size) + 1

                self._update_progress(total_pages=total_pages, current_page=0)
                logger.info(
                    f"[HomeplusCrawler] 총 {total_count}개 강좌, {total_pages}페이지"
                )

                # 2. 페이지별 크롤링
                max_pages = min(total_pages + 1, self.config.max_pages + 1)
                for page_num in range(1, max_pages):
                    self._update_progress(current_page=page_num)

                    try:
                        if page_num > 1:
                            html = await self._fetch_page(page_num)
                        else:
                            html = first_page_html

                        courses = self._parse_page(html)

                        for course in courses:
                            all_courses.append(course)
                            self._update_progress(collected=len(all_courses))

                            # 실시간 저장 콜백
                            if on_course_collected:
                                try:
                                    await on_course_collected(course)
                                except Exception as e:
                                    logger.error(
                                        f"[HomeplusCrawler] 저장 콜백 오류: {e}"
                                    )

                        logger.debug(
                            f"[HomeplusCrawler] 페이지 {page_num}/{total_pages}: "
                            f"{len(courses)}개 수집 (누적: {len(all_courses)})"
                        )

                        # 페이지 간 딜레이
                        if page_num < total_pages:
                            await asyncio.sleep(self.config.delay_between_pages)

                    except Exception as e:
                        error_msg = f"페이지 {page_num} 크롤링 실패: {e}"
                        logger.error(f"[HomeplusCrawler] {error_msg}")
                        self._update_progress(error=error_msg)
                        continue

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

        logger.info(f"[HomeplusCrawler] 크롤링 완료: {len(all_courses)}개 수집")

        return CrawlResult(
            courses=all_courses,
            found=len(all_courses),
            status=status,
            started_at=started_at,
            completed_at=datetime.now(),
            progress=self._progress,
        )

    async def _fetch_page(self, page_num: int) -> str:
        """페이지 HTML 가져오기."""
        params = {
            "hdnPSortType": "A",  # 개강일 빠른 순
        }

        # crawl_config에서 추가 파라미터 병합
        if self.config.api_params:
            params.update(self.config.api_params)

        # 페이지네이션 파라미터 추가 (홈플러스 특화)
        if page_num > 1:
            params["page"] = page_num

        response = await self._client.get(self.SEARCH_URL, params=params)
        response.raise_for_status()
        return response.text

    def _extract_total_count(self, html: str) -> int:
        """HTML에서 총 강좌 수 추출."""
        soup = BeautifulSoup(html, "html.parser")

        # 총 개수 텍스트 찾기
        count_elem = soup.select_one(self._selectors["total_count"])
        if count_elem:
            text = count_elem.get_text(strip=True)
            match = re.search(r"[\d,]+", text)
            if match:
                return int(match.group().replace(",", ""))

        # 대안: 아이템 개수로 추정
        items = soup.select(self._selectors["item"])
        return len(items) if items else 0

    def _parse_page(self, html: str) -> List[CourseImportItem]:
        """HTML 페이지에서 강좌 목록 파싱."""
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

            # 강좌 ID 추출
            item_id = item.get("id", "")
            source_id = item_id.replace("liLecture_", "") if item_id else None

            # 지점명
            branch_elem = item.select_one(self._selectors["branch"])
            branch_name = (
                branch_elem.get_text(strip=True) if branch_elem else "홈플러스"
            )

            # 카테고리 (강좌 타입)
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
            name_elems = item.select(".title_2")
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
                if idx == 0:  # 시간
                    time_text = text
                elif idx == 1:  # 회차/가격
                    fee = self._parse_fee(text)
                elif idx == 2:  # 기간
                    date_range_text = text
                elif idx == 3:  # 강사
                    if "강사" in text or not re.search(r"\d", text):
                        instructor = text.replace("강사", "").strip()

            # 시간 파싱
            day_of_week, time_start, time_end = self._parse_schedule(time_text)

            # 개강일 파싱
            course_start = self._parse_open_date(open_date_text)

            # 기간에서 날짜 추출
            course_start_from_range, course_end = self._parse_date_range(
                date_range_text
            )
            if not course_start and course_start_from_range:
                course_start = course_start_from_range

            # 회차 추출
            total_sessions = self._parse_sessions(
                info_elems[1].get_text(strip=True) if len(info_elems) > 1 else None
            )

            return CourseImportItem(
                # 센터 정보
                center_name=f"홈플러스 {branch_name}",
                center_type="mart",
                center_website=self.BASE_URL,
                # 강좌 정보
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
                # 비용
                fee=fee,
                # 일정
                course_start=course_start,
                course_end=course_end,
                day_of_week=day_of_week,
                time_start=time_start,
                time_end=time_end,
                total_sessions=total_sessions,
                # 강사
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
        """가격 파싱. '120,000원' -> 120000"""
        if not text:
            return None
        match = re.search(r"([\d,]+)\s*원", text)
        if match:
            return int(match.group(1).replace(",", ""))
        return None

    def _parse_schedule(self, text: str) -> tuple:
        """시간 파싱. '화 09:10 ~ 10:00' -> ('화', '09:10', '10:00')"""
        if not text:
            return (None, None, None)

        # 요일 추출
        day_match = re.search(r"([월화수목금토일,\s]+)", text)
        day_of_week = day_match.group(1).strip() if day_match else None

        # 시간 추출
        time_match = re.search(r"(\d{1,2}:\d{2})\s*[~\-]\s*(\d{1,2}:\d{2})", text)
        if time_match:
            return (day_of_week, time_match.group(1), time_match.group(2))

        return (day_of_week, None, None)

    def _parse_open_date(self, text: str) -> Optional[date]:
        """개강일 파싱. '01/06 개강' -> date(2026, 1, 6)"""
        if not text:
            return None

        # MM/DD 형식
        match = re.search(r"(\d{1,2})[/.](\d{1,2})", text)
        if match:
            month = int(match.group(1))
            day = int(match.group(2))
            year = datetime.now().year

            # 현재 월보다 이전이면 내년으로 간주
            if month < datetime.now().month - 1:
                year += 1

            try:
                return date(year, month, day)
            except ValueError:
                return None

        return None

    def _parse_date_range(self, text: str) -> tuple:
        """기간 파싱. '2026.01.06 ~ 2026.02.24' -> (date, date)"""
        if not text:
            return (None, None)

        # YYYY.MM.DD 형식
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
        """회차 파싱. '8회' -> 8"""
        if not text:
            return None
        match = re.search(r"(\d+)\s*회", text)
        if match:
            return int(match.group(1))
        return None
