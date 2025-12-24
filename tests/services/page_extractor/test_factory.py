"""ExtractorFactory 테스트."""

import pytest

from app.services.page_extractor.base import BaseExtractor, ExtractedContent
from app.services.page_extractor.factory import ExtractorFactory, get_extractor_factory
from app.services.page_extractor.generic import GenericExtractor


class MockExtractor(BaseExtractor):
    """테스트용 Mock 추출기."""

    def __init__(self, page_type: str, url_pattern: str):
        self.page_type = page_type
        self._url_pattern = url_pattern

    def can_extract(self, url: str) -> bool:
        return self._url_pattern in url

    async def extract(self, page, url: str) -> ExtractedContent:
        return ExtractedContent(
            url=url,
            page_type=self.page_type,
            extraction_method="structured",
        )


class TestExtractorFactory:
    """ExtractorFactory 테스트."""

    def test_default_extractors(self):
        """Right: 기본 추출기 목록 확인."""
        factory = ExtractorFactory()

        # GenericExtractor가 마지막에 있어야 함
        assert len(factory.extractors) >= 1
        assert isinstance(factory.extractors[-1], GenericExtractor)

    def test_get_extractor_returns_generic_for_unknown_url(self):
        """Right: 알 수 없는 URL에 대해 GenericExtractor 반환."""
        factory = ExtractorFactory()

        extractor = factory.get_extractor("https://unknown-site.com/page")

        assert isinstance(extractor, GenericExtractor)
        assert extractor.page_type == "generic"

    def test_detect_page_type(self):
        """Right: 페이지 유형 감지."""
        factory = ExtractorFactory()

        # 현재는 모두 generic으로 반환 (페이지별 추출기 미등록)
        assert factory.detect_page_type("https://unknown.com") == "generic"

    def test_register_extractor(self):
        """Right: 추출기 등록."""
        factory = ExtractorFactory()
        mock = MockExtractor("test_type", "test-site.com")

        factory.register(mock)

        # 등록된 추출기가 우선 선택됨
        extractor = factory.get_extractor("https://test-site.com/page")
        assert extractor.page_type == "test_type"

    def test_register_with_priority(self):
        """Right: 우선순위를 지정한 추출기 등록."""
        factory = ExtractorFactory()
        mock1 = MockExtractor("type1", "site.com")
        mock2 = MockExtractor("type2", "site.com")

        # mock1을 먼저 등록
        factory.register(mock1)
        # mock2를 더 높은 우선순위로 등록
        factory.register(mock2, priority=0)

        # mock2가 먼저 매칭됨
        extractor = factory.get_extractor("https://site.com/page")
        assert extractor.page_type == "type2"

    def test_generic_always_last(self):
        """Boundary: GenericExtractor는 항상 마지막."""
        factory = ExtractorFactory()
        mock = MockExtractor("test", "test.com")

        factory.register(mock)

        # GenericExtractor가 여전히 마지막
        assert isinstance(factory.extractors[-1], GenericExtractor)

    def test_first_matching_extractor_wins(self):
        """Right: 첫 번째 매칭 추출기가 선택됨."""
        factory = ExtractorFactory()
        mock1 = MockExtractor("type1", "example")  # 넓은 패턴
        mock2 = MockExtractor("type2", "example.com")  # 구체적인 패턴

        # mock1을 먼저 등록 (더 높은 우선순위)
        factory.register(mock1, priority=0)
        factory.register(mock2, priority=1)

        # mock1이 먼저 매칭됨 (더 넓은 패턴이지만 우선순위가 높음)
        extractor = factory.get_extractor("https://example.com/page")
        assert extractor.page_type == "type1"


class TestGetExtractorFactory:
    """get_extractor_factory 싱글톤 테스트."""

    def test_returns_same_instance(self):
        """Right: 동일한 인스턴스 반환."""
        # 싱글톤 초기화 (이전 테스트 영향 제거)
        import app.services.page_extractor.factory as factory_module

        factory_module._factory_instance = None

        factory1 = get_extractor_factory()
        factory2 = get_extractor_factory()

        assert factory1 is factory2

    def test_returns_extractor_factory_instance(self):
        """Right: ExtractorFactory 인스턴스 반환."""
        factory = get_extractor_factory()

        assert isinstance(factory, ExtractorFactory)
