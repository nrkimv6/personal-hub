"""추출기 팩토리."""

import logging
from typing import Optional

from .base import BaseExtractor
from .generic import GenericExtractor
from .google_form import GoogleFormExtractor
from .naver_form import NaverFormExtractor
from .naver_blog import NaverBlogExtractor

logger = logging.getLogger(__name__)


class ExtractorFactory:
    """URL 타입에 따른 추출기 팩토리."""

    # URL 타입별 추출기 매핑
    EXTRACTORS = {
        "google_form": GoogleFormExtractor,
        "naver_form": NaverFormExtractor,
        "naver_blog": NaverBlogExtractor,
        "generic": GenericExtractor,
        "other": GenericExtractor,
    }

    @classmethod
    def get_extractor(cls, url_type: str) -> BaseExtractor:
        """
        URL 타입에 맞는 추출기를 반환합니다.

        Args:
            url_type: URL 타입 (google_form, naver_form, naver_blog, generic, other)

        Returns:
            BaseExtractor: 해당 타입의 추출기 인스턴스
        """
        extractor_class = cls.EXTRACTORS.get(url_type, GenericExtractor)
        extractor = extractor_class()
        logger.debug(f"URL 타입 '{url_type}'에 대해 {extractor.name} 사용")
        return extractor

    @classmethod
    def get_extractor_for_url(cls, url: str) -> BaseExtractor:
        """
        URL을 분석하여 적절한 추출기를 반환합니다.

        Args:
            url: 추출할 URL

        Returns:
            BaseExtractor: 해당 URL에 맞는 추출기 인스턴스
        """
        url_type = cls.detect_url_type(url)
        return cls.get_extractor(url_type)

    @staticmethod
    def detect_url_type(url: str) -> str:
        """
        URL을 분석하여 타입을 반환합니다.

        Args:
            url: 분석할 URL

        Returns:
            str: URL 타입
        """
        url_lower = url.lower()

        # 구글 폼
        if any(pattern in url_lower for pattern in [
            "docs.google.com/forms",
            "forms.gle",
        ]):
            return "google_form"

        # 네이버 폼
        if "form.naver.com" in url_lower or "naver.me" in url_lower:
            return "naver_form"

        # 네이버 블로그
        if "blog.naver.com" in url_lower or "m.blog.naver.com" in url_lower:
            return "naver_blog"

        return "generic"
