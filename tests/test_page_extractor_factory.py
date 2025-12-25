"""ExtractorFactory URL 매칭 테스트."""

import pytest

from app.services.page_extractor import (
    ExtractorFactory,
    get_extractor_factory,
    GoogleFormsExtractor,
    NaverFormExtractor,
    NaverBlogPCExtractor,
    NaverBlogMobileExtractor,
    GenericExtractor,
)


class TestExtractorFactory:
    """ExtractorFactory 테스트."""

    def setup_method(self):
        """각 테스트 전 팩토리 초기화."""
        self.factory = ExtractorFactory()

    # ========== Google Forms ==========

    def test_google_forms_docs_url(self):
        """Right: Google Forms docs.google.com URL 매칭."""
        url = "https://docs.google.com/forms/d/e/1FAIpQLSf.../viewform"
        extractor = self.factory.get_extractor(url)

        assert isinstance(extractor, GoogleFormsExtractor)
        assert extractor.page_type == "google_forms"

    def test_google_forms_short_url(self):
        """Right: Google Forms forms.gle 단축 URL 매칭."""
        url = "https://forms.gle/ABC123xyz"
        extractor = self.factory.get_extractor(url)

        assert isinstance(extractor, GoogleFormsExtractor)

    def test_detect_page_type_google_forms(self):
        """Right: detect_page_type 메서드 테스트."""
        url = "https://docs.google.com/forms/d/e/xxx/viewform"
        page_type = self.factory.detect_page_type(url)

        assert page_type == "google_forms"

    # ========== Naver Form ==========

    def test_naver_form_url(self):
        """Right: Naver Form URL 매칭."""
        url = "https://form.naver.com/response/abcd1234"
        extractor = self.factory.get_extractor(url)

        assert isinstance(extractor, NaverFormExtractor)
        assert extractor.page_type == "naver_form"

    def test_naver_survey_url(self):
        """Right: Naver Survey URL 매칭."""
        url = "https://survey.naver.com/v/xxxx"
        extractor = self.factory.get_extractor(url)

        assert isinstance(extractor, NaverFormExtractor)

    # ========== Naver Blog ==========

    def test_naver_blog_mobile_url(self):
        """Right: Naver Blog Mobile URL 매칭 (m.blog)."""
        url = "https://m.blog.naver.com/username/12345"
        extractor = self.factory.get_extractor(url)

        assert isinstance(extractor, NaverBlogMobileExtractor)
        assert extractor.page_type == "naver_blog_mobile"

    def test_naver_blog_pc_url(self):
        """Right: Naver Blog PC URL 매칭."""
        url = "https://blog.naver.com/username/12345"
        extractor = self.factory.get_extractor(url)

        assert isinstance(extractor, NaverBlogPCExtractor)
        assert extractor.page_type == "naver_blog_pc"

    def test_naver_blog_mobile_priority(self):
        """Right: Mobile URL이 PC보다 우선 매칭."""
        # m.blog는 blog도 포함하므로 순서가 중요
        url = "https://m.blog.naver.com/PostView.nhn?blogId=xxx"
        extractor = self.factory.get_extractor(url)

        assert isinstance(extractor, NaverBlogMobileExtractor)

    # ========== Generic (Fallback) ==========

    def test_generic_fallback(self):
        """Right: 알 수 없는 URL은 GenericExtractor 사용."""
        url = "https://random-website.com/event/123"
        extractor = self.factory.get_extractor(url)

        assert isinstance(extractor, GenericExtractor)
        assert extractor.page_type == "generic"

    def test_generic_for_instagram(self):
        """Right: Instagram URL도 Generic으로 처리."""
        url = "https://www.instagram.com/p/ABC123/"
        extractor = self.factory.get_extractor(url)

        assert isinstance(extractor, GenericExtractor)

    def test_generic_for_facebook(self):
        """Right: Facebook URL도 Generic으로 처리."""
        url = "https://www.facebook.com/events/123456"
        extractor = self.factory.get_extractor(url)

        assert isinstance(extractor, GenericExtractor)

    # ========== Edge Cases ==========

    def test_empty_url(self):
        """Boundary: 빈 URL 처리."""
        url = ""
        extractor = self.factory.get_extractor(url)

        # GenericExtractor는 모든 URL에 대해 True 반환
        assert isinstance(extractor, GenericExtractor)

    def test_url_with_query_params(self):
        """Boundary: 쿼리 파라미터가 있는 URL."""
        url = "https://docs.google.com/forms/d/e/xxx/viewform?usp=sf_link"
        extractor = self.factory.get_extractor(url)

        assert isinstance(extractor, GoogleFormsExtractor)

    def test_url_with_fragment(self):
        """Boundary: 프래그먼트가 있는 URL."""
        url = "https://blog.naver.com/username/12345#comment"
        extractor = self.factory.get_extractor(url)

        assert isinstance(extractor, NaverBlogPCExtractor)

    def test_http_url(self):
        """Boundary: http URL (https 아님)."""
        url = "http://form.naver.com/response/xyz"
        extractor = self.factory.get_extractor(url)

        assert isinstance(extractor, NaverFormExtractor)


class TestGetExtractorFactory:
    """get_extractor_factory 싱글톤 테스트."""

    def test_returns_factory_instance(self):
        """Right: ExtractorFactory 인스턴스 반환."""
        factory = get_extractor_factory()

        assert isinstance(factory, ExtractorFactory)

    def test_singleton_same_instance(self):
        """Right: 동일한 인스턴스 반환 (싱글톤)."""
        factory1 = get_extractor_factory()
        factory2 = get_extractor_factory()

        assert factory1 is factory2


class TestExtractorRegistration:
    """추출기 등록 테스트."""

    def test_extractors_list(self):
        """Right: 등록된 추출기 목록 확인."""
        factory = ExtractorFactory()
        extractors = factory.extractors

        assert len(extractors) == 5  # Google, Naver Form, Blog Mobile, Blog PC, Generic
        assert isinstance(extractors[-1], GenericExtractor)  # 마지막은 항상 Generic

    def test_register_custom_extractor(self):
        """Right: 커스텀 추출기 등록."""
        factory = ExtractorFactory()
        initial_count = len(factory.extractors)

        # 더미 추출기 생성
        class DummyExtractor(GenericExtractor):
            page_type = "dummy"

            def can_extract(self, url: str) -> bool:
                return "dummy.com" in url

        dummy = DummyExtractor()
        factory.register(dummy)

        assert len(factory.extractors) == initial_count + 1

    def test_register_with_priority(self):
        """Right: 우선순위를 지정하여 등록."""
        factory = ExtractorFactory()

        class HighPriorityExtractor(GenericExtractor):
            page_type = "high_priority"

            def can_extract(self, url: str) -> bool:
                return "priority.com" in url

        factory.register(HighPriorityExtractor(), priority=0)

        # 첫 번째 위치에 등록되어야 함
        assert factory.extractors[0].page_type == "high_priority"
