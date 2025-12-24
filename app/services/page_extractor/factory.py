"""추출기 팩토리 - URL 기반 추출기 선택."""

from typing import List

from .base import BaseExtractor
from .generic import GenericExtractor
from .google_forms import GoogleFormsExtractor
from .naver_blog import NaverBlogMobileExtractor, NaverBlogPCExtractor
from .naver_form import NaverFormExtractor


class ExtractorFactory:
    """추출기 팩토리.

    URL 패턴에 따라 적절한 추출기를 선택합니다.
    추출기는 우선순위 순서대로 검사되며, 첫 번째로 매칭되는 추출기가 사용됩니다.
    GenericExtractor는 항상 마지막에 위치하여 Fallback으로 동작합니다.
    """

    def __init__(self):
        """추출기 목록 초기화."""
        # 우선순위 순서대로 등록
        # 더 구체적인 패턴이 먼저 오도록 정렬
        self._extractors: List[BaseExtractor] = [
            GoogleFormsExtractor(),
            NaverFormExtractor(),
            NaverBlogMobileExtractor(),  # Mobile 먼저 (더 구체적인 URL 패턴)
            NaverBlogPCExtractor(),
            GenericExtractor(),  # 항상 마지막 (Fallback)
        ]

    @property
    def extractors(self) -> List[BaseExtractor]:
        """등록된 추출기 목록."""
        return self._extractors

    def register(self, extractor: BaseExtractor, priority: int = -1) -> None:
        """추출기 등록.

        Args:
            extractor: 등록할 추출기
            priority: 우선순위 (0이 가장 높음, -1이면 GenericExtractor 직전에 추가)
        """
        if priority == -1:
            # GenericExtractor 직전에 삽입
            self._extractors.insert(-1, extractor)
        else:
            self._extractors.insert(priority, extractor)

    def get_extractor(self, url: str) -> BaseExtractor:
        """URL에 맞는 추출기 반환.

        Args:
            url: 추출할 페이지 URL

        Returns:
            적합한 추출기 (매칭되는 것이 없으면 GenericExtractor)
        """
        for extractor in self._extractors:
            if extractor.can_extract(url):
                return extractor

        # GenericExtractor는 항상 True를 반환하므로 여기 도달하지 않음
        # 하지만 안전을 위해 마지막 추출기 반환
        return self._extractors[-1]

    def detect_page_type(self, url: str) -> str:
        """URL의 페이지 유형 감지.

        Args:
            url: 검사할 URL

        Returns:
            페이지 유형 문자열
        """
        extractor = self.get_extractor(url)
        return extractor.page_type


# 싱글톤 인스턴스
_factory_instance: ExtractorFactory | None = None


def get_extractor_factory() -> ExtractorFactory:
    """ExtractorFactory 싱글톤 인스턴스 반환."""
    global _factory_instance
    if _factory_instance is None:
        _factory_instance = ExtractorFactory()
    return _factory_instance
