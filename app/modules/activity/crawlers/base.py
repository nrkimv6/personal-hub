"""Activity 크롤러 기본 클래스.

모든 사이트별 크롤러는 BaseCrawler를 상속하여 구현합니다.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable, List, Optional

from playwright.async_api import Page

from app.models.activity import ActivityCenter
from app.modules.activity.models.schemas import CourseImportItem


@dataclass
class CrawlProgress:
    """크롤링 진행 상태."""

    total_pages: int = 0
    current_page: int = 0
    total_items: int = 0
    collected_items: int = 0
    errors: List[str] = field(default_factory=list)


@dataclass
class CrawlConfig:
    """크롤링 설정.

    센터의 crawl_config JSON에서 로드됩니다.
    """

    # 공통 설정
    max_pages: int = 100
    page_size: int = 20
    delay_between_pages: float = 1.0
    timeout: float = 30.0

    # HTML 파싱용
    selectors: dict = field(default_factory=dict)

    # API 호출용
    api_endpoint: Optional[str] = None
    api_headers: dict = field(default_factory=dict)
    api_params: dict = field(default_factory=dict)

    # 센터 특화 설정
    extra: dict = field(default_factory=dict)


@dataclass
class CrawlResult:
    """크롤링 결과."""

    courses: List[CourseImportItem]
    found: int
    status: str  # 'completed', 'partial', 'failed'
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    progress: Optional[CrawlProgress] = None


# 콜백 타입: 강좌 수집 시 호출
OnCourseCollected = Callable[[CourseImportItem], Awaitable[bool]]


class BaseCrawler(ABC):
    """사이트별 크롤러 기본 클래스.

    모든 사이트별 크롤러는 이 클래스를 상속하여 구현합니다.

    Attributes:
        center: 크롤링 대상 센터 모델
        config: 크롤링 설정
        page: Playwright Page (동적 크롤링용, 선택적)
    """

    # 크롤러 식별자 (서브클래스에서 오버라이드)
    CRAWLER_ID: str = "base"

    def __init__(
        self,
        center: ActivityCenter,
        page: Optional[Page] = None,
    ):
        """초기화.

        Args:
            center: ActivityCenter 모델 인스턴스
            page: Playwright Page (동적 크롤링이 필요한 경우)
        """
        self.center = center
        self.page = page
        self.config = self._load_config()
        self._progress = CrawlProgress()

    def _load_config(self) -> CrawlConfig:
        """센터의 crawl_config에서 설정 로드."""
        raw_config = self.center.crawl_config or {}

        # 알려진 키 목록
        known_keys = {
            "max_pages",
            "page_size",
            "delay",
            "timeout",
            "selectors",
            "api_endpoint",
            "api_headers",
            "api_params",
            "extra",
            "crawler_id",  # 크롤러 선택용
        }

        # extra: 명시적 extra + 알려지지 않은 키들 병합
        explicit_extra = raw_config.get("extra", {})
        implicit_extra = {k: v for k, v in raw_config.items() if k not in known_keys}
        merged_extra = {**implicit_extra, **explicit_extra}

        return CrawlConfig(
            max_pages=raw_config.get("max_pages", 100),
            page_size=raw_config.get("page_size", 20),
            delay_between_pages=raw_config.get("delay", 1.0),
            timeout=raw_config.get("timeout", 30.0),
            selectors=raw_config.get("selectors", {}),
            api_endpoint=raw_config.get("api_endpoint"),
            api_headers=raw_config.get("api_headers", {}),
            api_params=raw_config.get("api_params", {}),
            extra=merged_extra,
        )

    @abstractmethod
    async def crawl(
        self,
        on_course_collected: Optional[OnCourseCollected] = None,
    ) -> CrawlResult:
        """크롤링 실행.

        Args:
            on_course_collected: 강좌 수집 시 호출되는 콜백 (실시간 저장용)

        Returns:
            CrawlResult: 크롤링 결과
        """
        pass

    @abstractmethod
    def _parse_course(self, raw_data: Any) -> Optional[CourseImportItem]:
        """원시 데이터를 CourseImportItem으로 변환.

        Args:
            raw_data: 파싱할 원시 데이터 (HTML element, dict 등)

        Returns:
            CourseImportItem 또는 파싱 실패 시 None
        """
        pass

    def get_progress(self) -> CrawlProgress:
        """현재 진행 상태 반환."""
        return self._progress

    def _update_progress(
        self,
        current_page: int = None,
        total_pages: int = None,
        collected: int = None,
        error: str = None,
    ):
        """진행 상태 업데이트."""
        if current_page is not None:
            self._progress.current_page = current_page
        if total_pages is not None:
            self._progress.total_pages = total_pages
        if collected is not None:
            self._progress.collected_items = collected
        if error is not None:
            self._progress.errors.append(error)
