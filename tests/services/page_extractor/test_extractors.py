"""페이지별 추출기 테스트."""

import pytest

from app.services.page_extractor import (
    ExtractorFactory,
    GoogleFormsExtractor,
    NaverBlogMobileExtractor,
    NaverBlogPCExtractor,
    NaverFormExtractor,
)


class TestGoogleFormsExtractor:
    """GoogleFormsExtractor 테스트."""

    def test_can_extract_docs_google_forms(self):
        """Right: docs.google.com/forms URL 인식."""
        extractor = GoogleFormsExtractor()

        assert extractor.can_extract(
            "https://docs.google.com/forms/d/e/xxx/viewform"
        )
        assert extractor.can_extract(
            "https://docs.google.com/forms/d/1abc123/edit"
        )

    def test_can_extract_forms_gle(self):
        """Right: forms.gle 단축 URL 인식."""
        extractor = GoogleFormsExtractor()

        assert extractor.can_extract("https://forms.gle/abc123")

    def test_cannot_extract_other_urls(self):
        """Boundary: 다른 URL 거부."""
        extractor = GoogleFormsExtractor()

        assert not extractor.can_extract("https://google.com/search")
        assert not extractor.can_extract("https://docs.google.com/document")
        assert not extractor.can_extract("https://naver.com")

    def test_page_type(self):
        """Right: 페이지 타입 확인."""
        extractor = GoogleFormsExtractor()

        assert extractor.page_type == "google_forms"


class TestNaverFormExtractor:
    """NaverFormExtractor 테스트."""

    def test_can_extract_form_naver(self):
        """Right: form.naver.com URL 인식."""
        extractor = NaverFormExtractor()

        assert extractor.can_extract("https://form.naver.com/response/xxx")
        assert extractor.can_extract("https://form.naver.com/form/xxx")

    def test_can_extract_survey_naver(self):
        """Right: survey.naver.com URL 인식."""
        extractor = NaverFormExtractor()

        assert extractor.can_extract("https://survey.naver.com/xxx")

    def test_cannot_extract_other_urls(self):
        """Boundary: 다른 URL 거부."""
        extractor = NaverFormExtractor()

        assert not extractor.can_extract("https://naver.com")
        assert not extractor.can_extract("https://blog.naver.com")
        assert not extractor.can_extract("https://google.com/forms")

    def test_page_type(self):
        """Right: 페이지 타입 확인."""
        extractor = NaverFormExtractor()

        assert extractor.page_type == "naver_form"


class TestNaverBlogPCExtractor:
    """NaverBlogPCExtractor 테스트."""

    def test_can_extract_blog_naver(self):
        """Right: blog.naver.com URL 인식."""
        extractor = NaverBlogPCExtractor()

        assert extractor.can_extract("https://blog.naver.com/username/123")
        assert extractor.can_extract("https://blog.naver.com/PostView.naver?blogId=xxx")

    def test_cannot_extract_mobile_blog(self):
        """Boundary: m.blog.naver.com은 거부 (Mobile용)."""
        extractor = NaverBlogPCExtractor()

        assert not extractor.can_extract("https://m.blog.naver.com/username/123")

    def test_cannot_extract_other_urls(self):
        """Boundary: 다른 URL 거부."""
        extractor = NaverBlogPCExtractor()

        assert not extractor.can_extract("https://naver.com")
        assert not extractor.can_extract("https://cafe.naver.com")

    def test_page_type(self):
        """Right: 페이지 타입 확인."""
        extractor = NaverBlogPCExtractor()

        assert extractor.page_type == "naver_blog_pc"


class TestNaverBlogMobileExtractor:
    """NaverBlogMobileExtractor 테스트."""

    def test_can_extract_m_blog_naver(self):
        """Right: m.blog.naver.com URL 인식."""
        extractor = NaverBlogMobileExtractor()

        assert extractor.can_extract("https://m.blog.naver.com/username/123")
        assert extractor.can_extract(
            "https://m.blog.naver.com/PostView.naver?blogId=xxx"
        )

    def test_cannot_extract_pc_blog(self):
        """Boundary: blog.naver.com (PC)은 거부."""
        extractor = NaverBlogMobileExtractor()

        # "m.blog"이 포함되지 않은 URL
        assert not extractor.can_extract("https://blog.naver.com/username/123")

    def test_page_type(self):
        """Right: 페이지 타입 확인."""
        extractor = NaverBlogMobileExtractor()

        assert extractor.page_type == "naver_blog_mobile"


class TestExtractorFactoryWithAllExtractors:
    """모든 추출기가 등록된 ExtractorFactory 테스트."""

    def test_all_extractors_registered(self):
        """Right: 모든 추출기가 등록됨."""
        factory = ExtractorFactory()

        # 5개 추출기가 등록되어야 함
        assert len(factory.extractors) == 5

    def test_google_forms_url_detection(self):
        """Right: Google Forms URL 감지."""
        factory = ExtractorFactory()

        assert factory.detect_page_type("https://docs.google.com/forms/d/e/xxx") == "google_forms"
        assert factory.detect_page_type("https://forms.gle/abc") == "google_forms"

    def test_naver_form_url_detection(self):
        """Right: Naver Form URL 감지."""
        factory = ExtractorFactory()

        assert factory.detect_page_type("https://form.naver.com/response/xxx") == "naver_form"

    def test_naver_blog_mobile_url_detection(self):
        """Right: Naver Blog Mobile URL 감지."""
        factory = ExtractorFactory()

        assert factory.detect_page_type("https://m.blog.naver.com/xxx") == "naver_blog_mobile"

    def test_naver_blog_pc_url_detection(self):
        """Right: Naver Blog PC URL 감지."""
        factory = ExtractorFactory()

        assert factory.detect_page_type("https://blog.naver.com/xxx") == "naver_blog_pc"

    def test_generic_fallback(self):
        """Right: 알 수 없는 URL은 generic으로 처리."""
        factory = ExtractorFactory()

        assert factory.detect_page_type("https://example.com") == "generic"
        assert factory.detect_page_type("https://instagram.com/p/xxx") == "generic"

    def test_mobile_before_pc(self):
        """Boundary: Mobile 추출기가 PC보다 우선."""
        factory = ExtractorFactory()

        # Mobile URL은 Mobile 추출기가 처리
        extractor = factory.get_extractor("https://m.blog.naver.com/xxx")
        assert isinstance(extractor, NaverBlogMobileExtractor)

        # PC URL은 PC 추출기가 처리 (Mobile이 거부하므로)
        extractor = factory.get_extractor("https://blog.naver.com/xxx")
        assert isinstance(extractor, NaverBlogPCExtractor)
