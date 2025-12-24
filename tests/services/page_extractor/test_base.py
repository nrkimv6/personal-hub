"""BaseExtractor 및 ExtractedContent 테스트."""

import pytest

from app.services.page_extractor.base import BaseExtractor, ExtractedContent


class TestExtractedContent:
    """ExtractedContent 데이터클래스 테스트."""

    def test_create_with_required_fields(self):
        """Right: 필수 필드만으로 생성."""
        content = ExtractedContent(
            url="https://example.com",
            page_type="generic",
            extraction_method="structured",
        )

        assert content.url == "https://example.com"
        assert content.page_type == "generic"
        assert content.extraction_method == "structured"
        assert content.title is None
        assert content.success is True

    def test_create_with_all_fields(self):
        """Right: 모든 필드로 생성."""
        content = ExtractedContent(
            url="https://example.com",
            page_type="google_forms",
            extraction_method="structured",
            title="Test Title",
            description="Test Description",
            content="Test Content",
            structured_data={"key": "value"},
            images=["img1.jpg", "img2.jpg"],
            metadata={"og_title": "OG Title"},
            success=True,
            error=None,
        )

        assert content.title == "Test Title"
        assert content.description == "Test Description"
        assert content.structured_data == {"key": "value"}
        assert len(content.images) == 2

    def test_to_dict(self):
        """Right: 딕셔너리 변환."""
        content = ExtractedContent(
            url="https://example.com",
            page_type="generic",
            extraction_method="structured",
            title="Test",
        )

        result = content.to_dict()

        assert isinstance(result, dict)
        assert result["url"] == "https://example.com"
        assert result["page_type"] == "generic"
        assert result["title"] == "Test"

    def test_failed_extraction(self):
        """Error: 실패한 추출 표현."""
        content = ExtractedContent(
            url="https://example.com",
            page_type="generic",
            extraction_method="failed",
            success=False,
            error="Timeout error",
        )

        assert content.success is False
        assert content.error == "Timeout error"

    def test_default_lists_are_independent(self):
        """Boundary: 기본 리스트가 독립적임."""
        content1 = ExtractedContent(
            url="https://example1.com",
            page_type="generic",
            extraction_method="structured",
        )
        content2 = ExtractedContent(
            url="https://example2.com",
            page_type="generic",
            extraction_method="structured",
        )

        content1.images.append("img1.jpg")

        # content2의 images는 영향받지 않아야 함
        assert len(content2.images) == 0


class TestBaseExtractor:
    """BaseExtractor 추상 클래스 테스트."""

    def test_cannot_instantiate_directly(self):
        """Error: 직접 인스턴스화 불가."""
        with pytest.raises(TypeError):
            BaseExtractor()

    def test_subclass_must_implement_abstract_methods(self):
        """Error: 추상 메서드 미구현 시 에러."""

        class IncompleteExtractor(BaseExtractor):
            pass

        with pytest.raises(TypeError):
            IncompleteExtractor()

    def test_valid_subclass(self):
        """Right: 올바른 서브클래스 구현."""
        from playwright.async_api import Page

        class ValidExtractor(BaseExtractor):
            page_type = "test"

            def can_extract(self, url: str) -> bool:
                return "test" in url

            async def extract(self, page: Page, url: str) -> ExtractedContent:
                return ExtractedContent(
                    url=url,
                    page_type=self.page_type,
                    extraction_method="structured",
                )

        extractor = ValidExtractor()
        assert extractor.page_type == "test"
        assert extractor.can_extract("https://test.com") is True
        assert extractor.can_extract("https://other.com") is False
