"""Activity 크롤러 모듈.

사이트별 크롤러를 등록하고 센터 설정에 따라 적절한 크롤러를 반환합니다.
"""

from typing import Dict, Optional, Type

from playwright.async_api import Page

from app.models.activity import ActivityCenter
from app.modules.activity.crawlers.base import (
    BaseCrawler,
    CrawlConfig,
    CrawlProgress,
    CrawlResult,
    OnCourseCollected,
)

# 순환 import 방지를 위해 지연 import
_CRAWLER_REGISTRY: Optional[Dict[str, Type[BaseCrawler]]] = None


def _get_registry() -> Dict[str, Type[BaseCrawler]]:
    """크롤러 레지스트리 로드 (지연 초기화)."""
    global _CRAWLER_REGISTRY
    if _CRAWLER_REGISTRY is None:
        from app.modules.activity.crawlers.homeplus import HomeplusCrawler
        from app.modules.activity.crawlers.shinsegae import ShinsegaeCrawler

        _CRAWLER_REGISTRY = {
            "homeplus": HomeplusCrawler,
            "shinsegae": ShinsegaeCrawler,
        }
    return _CRAWLER_REGISTRY


def get_crawler(
    center: ActivityCenter,
    page: Optional[Page] = None,
) -> Optional[BaseCrawler]:
    """센터 설정에 맞는 크롤러 인스턴스 반환.

    Args:
        center: ActivityCenter 모델
        page: Playwright Page (동적 크롤링용)

    Returns:
        BaseCrawler 인스턴스 또는 None
    """
    registry = _get_registry()

    # 1. crawl_config에서 crawler_id 확인
    crawler_id = None
    if center.crawl_config:
        crawler_id = center.crawl_config.get("crawler_id")

    # 2. crawl_url에서 추론
    if not crawler_id and center.crawl_url:
        url_lower = center.crawl_url.lower()
        if "homeplus" in url_lower or "mschool.homeplus" in url_lower:
            crawler_id = "homeplus"
        elif "shinsegae" in url_lower or "sacademy" in url_lower:
            crawler_id = "shinsegae"

    # 3. 레지스트리에서 크롤러 클래스 조회
    if crawler_id and crawler_id in registry:
        crawler_class = registry[crawler_id]
        return crawler_class(center=center, page=page)

    return None


def register_crawler(crawler_id: str, crawler_class: Type[BaseCrawler]):
    """새 크롤러 등록.

    Args:
        crawler_id: 크롤러 식별자
        crawler_class: BaseCrawler 서브클래스
    """
    registry = _get_registry()
    registry[crawler_id] = crawler_class


def get_available_crawlers() -> list[str]:
    """사용 가능한 크롤러 ID 목록."""
    return list(_get_registry().keys())


__all__ = [
    "BaseCrawler",
    "CrawlConfig",
    "CrawlProgress",
    "CrawlResult",
    "OnCourseCollected",
    "get_crawler",
    "register_crawler",
    "get_available_crawlers",
]
