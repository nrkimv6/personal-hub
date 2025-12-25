"""
Extractor 유닛 테스트
"""

import pytest
from app.services.extractors import (
    ExtractorFactory,
    GenericExtractor,
    GoogleFormExtractor,
    NaverFormExtractor,
    NaverBlogExtractor,
)


class TestExtractorFactory:
    """ExtractorFactory 테스트"""

    def test_get_extractor_google_form(self):
        """구글 폼 추출기 반환"""
        extractor = ExtractorFactory.get_extractor("google_form")
        assert isinstance(extractor, GoogleFormExtractor)
        assert extractor.name == "GoogleFormExtractor"

    def test_get_extractor_naver_form(self):
        """네이버 폼 추출기 반환"""
        extractor = ExtractorFactory.get_extractor("naver_form")
        assert isinstance(extractor, NaverFormExtractor)
        assert extractor.name == "NaverFormExtractor"

    def test_get_extractor_naver_blog(self):
        """네이버 블로그 추출기 반환"""
        extractor = ExtractorFactory.get_extractor("naver_blog")
        assert isinstance(extractor, NaverBlogExtractor)
        assert extractor.name == "NaverBlogExtractor"

    def test_get_extractor_generic(self):
        """범용 추출기 반환"""
        extractor = ExtractorFactory.get_extractor("generic")
        assert isinstance(extractor, GenericExtractor)
        assert extractor.name == "GenericExtractor"

    def test_get_extractor_unknown_type(self):
        """알 수 없는 타입은 범용 추출기 반환"""
        extractor = ExtractorFactory.get_extractor("unknown_type")
        assert isinstance(extractor, GenericExtractor)

    def test_detect_url_type_google_form(self):
        """구글 폼 URL 감지"""
        urls = [
            "https://docs.google.com/forms/d/e/123456/viewform",
            "https://forms.gle/abcDEF123",
        ]
        for url in urls:
            assert ExtractorFactory.detect_url_type(url) == "google_form"

    def test_detect_url_type_naver_form(self):
        """네이버 폼 URL 감지"""
        urls = [
            "https://form.naver.com/response/test123",
            "https://naver.me/xyzABC",
        ]
        for url in urls:
            assert ExtractorFactory.detect_url_type(url) == "naver_form"

    def test_detect_url_type_naver_blog(self):
        """네이버 블로그 URL 감지"""
        urls = [
            "https://blog.naver.com/testuser/12345",
            "https://m.blog.naver.com/testuser/12345",
        ]
        for url in urls:
            assert ExtractorFactory.detect_url_type(url) == "naver_blog"

    def test_detect_url_type_generic(self):
        """일반 URL은 generic 반환"""
        urls = [
            "https://example.com",
            "https://github.com/user/repo",
        ]
        for url in urls:
            assert ExtractorFactory.detect_url_type(url) == "generic"

    def test_get_extractor_for_url(self):
        """URL에서 직접 추출기 가져오기"""
        extractor = ExtractorFactory.get_extractor_for_url("https://forms.gle/test123")
        assert isinstance(extractor, GoogleFormExtractor)

        extractor = ExtractorFactory.get_extractor_for_url("https://blog.naver.com/test")
        assert isinstance(extractor, NaverBlogExtractor)
