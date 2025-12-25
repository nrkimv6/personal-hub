"""각 Extractor의 can_extract 메서드 테스트."""

import pytest

from app.services.page_extractor import (
    GoogleFormsExtractor,
    NaverFormExtractor,
    NaverBlogPCExtractor,
    NaverBlogMobileExtractor,
    GenericExtractor,
)


class TestGoogleFormsExtractor:
    """GoogleFormsExtractor 테스트."""

    def setup_method(self):
        self.extractor = GoogleFormsExtractor()

    def test_page_type(self):
        """Right: page_type 확인."""
        assert self.extractor.page_type == "google_forms"

    def test_can_extract_docs_url(self):
        """Right: docs.google.com/forms URL."""
        assert self.extractor.can_extract(
            "https://docs.google.com/forms/d/e/1FAIpQLSf/viewform"
        )

    def test_can_extract_forms_gle(self):
        """Right: forms.gle 단축 URL."""
        assert self.extractor.can_extract("https://forms.gle/ABC123")

    def test_cannot_extract_google_docs(self):
        """Inverse: Google Docs URL은 매칭 안됨."""
        assert not self.extractor.can_extract(
            "https://docs.google.com/document/d/xxx"
        )

    def test_cannot_extract_google_sheets(self):
        """Inverse: Google Sheets URL은 매칭 안됨."""
        assert not self.extractor.can_extract(
            "https://docs.google.com/spreadsheets/d/xxx"
        )

    def test_cannot_extract_random_url(self):
        """Inverse: 일반 URL은 매칭 안됨."""
        assert not self.extractor.can_extract("https://example.com/form")


class TestNaverFormExtractor:
    """NaverFormExtractor 테스트."""

    def setup_method(self):
        self.extractor = NaverFormExtractor()

    def test_page_type(self):
        """Right: page_type 확인."""
        assert self.extractor.page_type == "naver_form"

    def test_can_extract_form_naver(self):
        """Right: form.naver.com URL."""
        assert self.extractor.can_extract(
            "https://form.naver.com/response/abcd1234"
        )

    def test_can_extract_survey_naver(self):
        """Right: survey.naver.com URL."""
        assert self.extractor.can_extract("https://survey.naver.com/v/xxx")

    def test_cannot_extract_naver_me(self):
        """Boundary: naver.me는 리다이렉트 전 URL이므로 매칭 안됨."""
        # naver.me는 can_extract에서 처리하지 않음 (리다이렉트 후 form.naver.com으로 변경됨)
        assert not self.extractor.can_extract("https://naver.me/ABC123")

    def test_cannot_extract_naver_blog(self):
        """Inverse: Naver Blog URL은 매칭 안됨."""
        assert not self.extractor.can_extract("https://blog.naver.com/xxx")


class TestNaverBlogPCExtractor:
    """NaverBlogPCExtractor 테스트."""

    def setup_method(self):
        self.extractor = NaverBlogPCExtractor()

    def test_page_type(self):
        """Right: page_type 확인."""
        assert self.extractor.page_type == "naver_blog_pc"

    def test_can_extract_blog_url(self):
        """Right: blog.naver.com URL."""
        assert self.extractor.can_extract("https://blog.naver.com/username/123")

    def test_can_extract_post_view(self):
        """Right: PostView.nhn URL."""
        assert self.extractor.can_extract(
            "https://blog.naver.com/PostView.nhn?blogId=xxx&logNo=123"
        )

    def test_cannot_extract_mobile_blog(self):
        """Inverse: m.blog.naver.com은 매칭 안됨."""
        assert not self.extractor.can_extract("https://m.blog.naver.com/xxx/123")

    def test_cannot_extract_naver_form(self):
        """Inverse: Naver Form URL은 매칭 안됨."""
        assert not self.extractor.can_extract("https://form.naver.com/xxx")


class TestNaverBlogMobileExtractor:
    """NaverBlogMobileExtractor 테스트."""

    def setup_method(self):
        self.extractor = NaverBlogMobileExtractor()

    def test_page_type(self):
        """Right: page_type 확인."""
        assert self.extractor.page_type == "naver_blog_mobile"

    def test_can_extract_mobile_blog(self):
        """Right: m.blog.naver.com URL."""
        assert self.extractor.can_extract("https://m.blog.naver.com/xxx/123")

    def test_cannot_extract_pc_blog(self):
        """Inverse: blog.naver.com (PC)은 매칭 안됨."""
        assert not self.extractor.can_extract("https://blog.naver.com/xxx/123")


class TestGenericExtractor:
    """GenericExtractor 테스트."""

    def setup_method(self):
        self.extractor = GenericExtractor()

    def test_page_type(self):
        """Right: page_type 확인."""
        assert self.extractor.page_type == "generic"

    def test_can_extract_any_url(self):
        """Right: 모든 URL에 대해 True 반환."""
        assert self.extractor.can_extract("https://example.com")
        assert self.extractor.can_extract("https://random-site.io/event")
        assert self.extractor.can_extract("https://www.instagram.com/p/xxx")
        assert self.extractor.can_extract("https://twitter.com/xxx/status/123")

    def test_can_extract_empty_url(self):
        """Boundary: 빈 URL도 True 반환."""
        assert self.extractor.can_extract("")

    def test_can_extract_invalid_url(self):
        """Boundary: 유효하지 않은 URL도 True 반환."""
        assert self.extractor.can_extract("not-a-valid-url")

    def test_always_fallback(self):
        """Right: Fallback으로서 항상 사용 가능."""
        # 다른 추출기가 처리하지 못하는 URL도 처리
        assert self.extractor.can_extract(
            "https://unknown-event-site.com/promotion"
        )
