"""신세계 문화센터 크롤러.

신세계백화점 문화센터 API를 통해 강좌 목록을 수집합니다.
"""

import asyncio
import logging
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional

import httpx

from app.models.activity import ActivityCenter
from app.modules.activity.crawlers.base import (
    BaseCrawler,
    CrawlResult,
    OnCourseCollected,
)
from app.modules.activity.models.schemas import CourseImportItem

logger = logging.getLogger("activity.crawler.shinsegae")


class ShinsegaeCrawler(BaseCrawler):
    """신세계 문화센터 크롤러 (API 호출).

    신세계백화점 문화센터 API를 통해 강좌 목록을 수집합니다.
    """

    CRAWLER_ID = "shinsegae"

    # API 설정
    BASE_URL = "https://sacademy.shinsegae.com"
    API_ENDPOINT = "/sdotcom/web/HP0010P0/getLectList.do"
    SEMESTER_API = "/sdotcom/cmmn/code/getLectSmstCode.do"

    # 기본 헤더
    DEFAULT_HEADERS = {
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": "https://sacademy.shinsegae.com",
        "Referer": "https://sacademy.shinsegae.com/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }

    # 지점 코드 매핑
    STORE_CODES = {
        "ON": "온라인",
        "01": "본점",
        "03": "타임스퀘어",
        "14": "강남점",
        "15": "마산점",
        "16": "사우스시티",
        "18": "센텀시티",
        "19": "의정부점",
        "37": "김해점",
        "40": "스타필드하남점",
        "70": "천안아산점",
        "90": "대구신세계",
        "D1": "대전신세계",
    }

    # 지점별 지역 정보
    STORE_REGIONS = {
        "01": ("서울특별시", "중구"),
        "03": ("서울특별시", "영등포구"),
        "14": ("서울특별시", "서초구"),
        "15": ("경상남도", "창원시"),
        "16": ("경기도", "용인시"),
        "18": ("부산광역시", "해운대구"),
        "19": ("경기도", "의정부시"),
        "37": ("경상남도", "김해시"),
        "40": ("경기도", "하남시"),
        "70": ("충청남도", "천안시"),
        "90": ("대구광역시", "동구"),
        "D1": ("대전광역시", "유성구"),
    }

    # 카테고리 매핑
    CATEGORY_MAP = {
        "운동": "exercise",
        "건강": "exercise",
        "웰니스": "exercise",
        "미술": "art",
        "공예": "art",
        "크래프트": "art",
        "음악": "music",
        "악기": "music",
        "뮤직": "music",
        "요리": "cooking",
        "쿠킹": "cooking",
        "어학": "language",
        "취미": "hobby",
        "교양": "hobby",
        "자격증": "certificate",
    }

    def __init__(
        self,
        center: ActivityCenter,
        page=None,
    ):
        super().__init__(center, page)
        self._client: Optional[httpx.AsyncClient] = None

        # crawl_config에서 크롤링할 지점 목록
        self._store_codes = self.config.extra.get(
            "store_codes", list(self.STORE_CODES.keys())
        )

    async def crawl(
        self,
        on_course_collected: Optional[OnCourseCollected] = None,
    ) -> CrawlResult:
        """신세계 문화센터 크롤링 실행."""
        started_at = datetime.now()
        all_courses: List[CourseImportItem] = []

        logger.info(
            f"[ShinsegaeCrawler] 크롤링 시작: {len(self._store_codes)}개 지점"
        )

        headers = {**self.DEFAULT_HEADERS, **self.config.api_headers}

        async with httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers=headers,
            timeout=self.config.timeout,
            follow_redirects=True,
        ) as client:
            self._client = client

            total_stores = len(self._store_codes)

            for store_idx, store_code in enumerate(self._store_codes):
                store_name = self.STORE_CODES.get(store_code, store_code)
                logger.info(
                    f"[ShinsegaeCrawler] 지점 {store_idx + 1}/{total_stores}: "
                    f"{store_name} ({store_code})"
                )

                try:
                    # 학기 코드 조회
                    semester_code = await self._get_semester_code(store_code)
                    if not semester_code:
                        logger.warning(
                            f"[ShinsegaeCrawler] {store_name}: 학기 코드 없음"
                        )
                        continue

                    courses = await self._crawl_store(
                        store_code,
                        semester_code,
                        on_course_collected,
                    )
                    all_courses.extend(courses)

                    logger.debug(
                        f"[ShinsegaeCrawler] {store_name}: {len(courses)}개 수집"
                    )

                    # 지점 간 딜레이
                    if store_idx < total_stores - 1:
                        await asyncio.sleep(self.config.delay_between_pages)

                except Exception as e:
                    error_msg = f"지점 {store_name} 크롤링 실패: {e}"
                    logger.error(f"[ShinsegaeCrawler] {error_msg}", exc_info=True)
                    self._update_progress(error=error_msg)
                    continue

        status = "completed" if not self._progress.errors else "partial"

        logger.info(f"[ShinsegaeCrawler] 크롤링 완료: {len(all_courses)}개 수집")

        return CrawlResult(
            courses=all_courses,
            found=len(all_courses),
            status=status,
            started_at=started_at,
            completed_at=datetime.now(),
            progress=self._progress,
        )

    async def _get_semester_code(self, store_code: str) -> Optional[str]:
        """지점의 현재 학기 코드 조회."""
        try:
            params = {
                "comboTagId": "schSmstCode",
                "userdefHeaderCode": "smstCode",
                "topText": "",
                "chcVal": "",
                "successCallbackFunc": "",
                "storeCode": store_code,
            }

            response = await self._client.post(self.SEMESTER_API, data=params)
            response.raise_for_status()
            data = response.json()

            if data.get("result") == "SUCCESS" and data.get("resultList"):
                # 첫 번째 학기 코드 반환
                return data["resultList"][0].get("detailCode")

        except Exception as e:
            logger.warning(
                f"[ShinsegaeCrawler] 학기 코드 조회 실패 ({store_code}): {e}"
            )

        return None

    async def _crawl_store(
        self,
        store_code: str,
        semester_code: str,
        on_course_collected: Optional[OnCourseCollected],
    ) -> List[CourseImportItem]:
        """단일 지점 크롤링."""
        courses: List[CourseImportItem] = []
        page_num = 1

        while page_num <= self.config.max_pages:
            try:
                data = await self._fetch_page(store_code, semester_code, page_num)

                if not data or data.get("result") != "SUCCESS":
                    break

                lect_list = data.get("lectList", [])
                if not lect_list:
                    break

                # 총 개수 파악 (첫 페이지)
                if page_num == 1:
                    param = data.get("param", {})
                    total_count = int(param.get("totalCount", 0))
                    page_size = int(param.get("pageSize", 10))
                    total_pages = (total_count // page_size) + 1 if total_count else 1
                    logger.debug(
                        f"[ShinsegaeCrawler] {store_code}: "
                        f"총 {total_count}개, {total_pages}페이지"
                    )

                for item in lect_list:
                    course = self._parse_course(item, store_code)
                    if course:
                        courses.append(course)

                        if on_course_collected:
                            try:
                                await on_course_collected(course)
                            except Exception as e:
                                logger.error(
                                    f"[ShinsegaeCrawler] 저장 콜백 오류: {e}"
                                )

                # 다음 페이지 확인
                if len(lect_list) < self.config.page_size:
                    break

                page_num += 1
                await asyncio.sleep(0.5)

            except Exception as e:
                logger.warning(
                    f"[ShinsegaeCrawler] {store_code} 페이지 {page_num} 실패: {e}"
                )
                break

        return courses

    async def _fetch_page(
        self,
        store_code: str,
        semester_code: str,
        page_num: int,
    ) -> Optional[Dict[str, Any]]:
        """API 호출하여 페이지 데이터 가져오기."""
        params = {
            "curPage": page_num,
            "search": "Y",
            "storeCode": store_code,
            "schSmstCode": semester_code,
            "autoSeachYn": "Y",
            "sttlmBtnYn": "Y",
            "srchCndCd": "01",
            "ordKey": "",
            "vipUseFlag": "",
            "onOffCode": "",
            "onlineStoreCode": "",
            "lectGrType": "",
            "lectGrCode": "",
            "rcptStat": "",
            "dayCode": "",
            "lectTimeCode": "",
            "targetCode": "",
            "srchWrd": "",
        }

        # crawl_config에서 추가 파라미터 병합
        if self.config.api_params:
            params.update(self.config.api_params)

        response = await self._client.post(self.API_ENDPOINT, data=params)
        response.raise_for_status()

        return response.json()

    def _parse_course(
        self,
        raw_data: Any,
        store_code: str = None,
    ) -> Optional[CourseImportItem]:
        """API 응답 데이터를 CourseImportItem으로 변환."""
        if not isinstance(raw_data, dict):
            return None

        try:
            data = raw_data

            # 기본 정보
            source_id = data.get("lectCode")
            name = data.get("lectName", "알 수 없음")

            # 지점 정보
            store_name = self.STORE_CODES.get(store_code, store_code)
            region_info = self.STORE_REGIONS.get(store_code, (None, None))

            # 카테고리 추론
            category = self._map_category(name)

            # 비용
            fee = self._parse_int(data.get("lectAmt"))

            # 요일
            day_name = data.get("dayCodeName")

            # 시간
            lect_hm = data.get("lectHm", "")
            time_start, time_end = self._parse_time_range(lect_hm)

            # 강좌 기간
            course_start, course_end = self._parse_lect_period(
                data.get("lectPeriod")
            )

            # 접수 기간
            reg_start, reg_end = self._parse_inet_period(
                data.get("inetLectPeriod")
            )

            # 강사
            instructor = data.get("tchName")

            # 회차
            total_sessions = self._parse_int(data.get("lectCnt"))

            # 상세 URL
            detail_url = None
            if source_id:
                year_code = data.get("yearCode", datetime.now().year)
                smst_code = data.get("smstCode", "")
                detail_url = (
                    f"{self.BASE_URL}/sdotcom/web/HP0010P0/HP0010P1.do?"
                    f"yearCode={year_code}&smstCode={smst_code}&"
                    f"storeCode={store_code}&lectCode={source_id}"
                )

            # 대상 연령
            target_age = self._map_target_age(data.get("tlectTargetMemCodeName"))

            return CourseImportItem(
                # 센터 정보
                center_name=f"신세계 {store_name}",
                center_type="department",
                center_region_sido=region_info[0],
                center_region_sigungu=region_info[1],
                center_website=self.BASE_URL,
                # 강좌 정보
                source_id=source_id,
                name=name,
                source_url=detail_url,
                category=category,
                target_age=target_age,
                # 비용
                fee=fee,
                # 일정
                registration_start=reg_start,
                registration_end=reg_end,
                course_start=course_start,
                course_end=course_end,
                day_of_week=day_name,
                time_start=time_start,
                time_end=time_end,
                total_sessions=total_sessions,
                # 강사
                instructor_name=instructor,
            )

        except Exception as e:
            logger.warning(f"[ShinsegaeCrawler] 강좌 파싱 실패: {e}")
            return None

    def _map_category(self, text: str) -> str:
        """텍스트에서 카테고리 추론."""
        if not text:
            return "other"
        text_lower = text.lower()
        for key, mapped in self.CATEGORY_MAP.items():
            if key in text_lower:
                return mapped
        return "other"

    def _parse_int(self, value: Any) -> Optional[int]:
        """정수 파싱."""
        if value is None:
            return None
        try:
            if isinstance(value, str):
                value = value.replace(",", "")
            return int(value)
        except (ValueError, TypeError):
            return None

    def _parse_time_range(self, text: str) -> tuple:
        """시간 범위 파싱. '15:40~17:00' -> ('15:40', '17:00')"""
        if not text:
            return (None, None)

        match = re.search(r"(\d{1,2}:\d{2})\s*[~\-]\s*(\d{1,2}:\d{2})", text)
        if match:
            return (match.group(1), match.group(2))

        return (None, None)

    def _parse_lect_period(self, text: str) -> tuple:
        """강좌 기간 파싱. '2026.01.10~2026.01.10' -> (date, date)"""
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
                d = date(int(matches[0][0]), int(matches[0][1]), int(matches[0][2]))
                return (d, d)
            except ValueError:
                pass

        return (None, None)

    def _parse_inet_period(self, text: str) -> tuple:
        """접수 기간 파싱. datetime 반환."""
        if not text:
            return (None, None)

        matches = re.findall(r"(\d{4})[./](\d{1,2})[./](\d{1,2})", text)
        if len(matches) >= 2:
            try:
                start = datetime(
                    int(matches[0][0]), int(matches[0][1]), int(matches[0][2])
                )
                end = datetime(
                    int(matches[1][0]), int(matches[1][1]), int(matches[1][2]),
                    23, 59, 59
                )
                return (start, end)
            except ValueError:
                pass

        return (None, None)

    def _map_target_age(self, value: Any) -> Optional[str]:
        """대상 연령 매핑."""
        if not value:
            return None

        value_str = str(value)
        mapping = {
            "유아": "infant",
            "어린이": "child",
            "키즈": "child",
            "청소년": "youth",
            "성인": "adult",
            "대중": "adult",
            "시니어": "senior",
            "임산부": "adult",
            "남성": "adult",
            "패밀리": "all",
            "커플": "adult",
        }

        for key, mapped in mapping.items():
            if key in value_str:
                return mapped

        return None
