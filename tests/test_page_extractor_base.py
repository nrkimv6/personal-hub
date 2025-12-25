"""ExtractedContent 데이터클래스 테스트."""

import pytest

from app.services.page_extractor.base import ExtractedContent


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
        assert content.success is True  # 기본값
        assert content.error is None

    def test_create_with_all_fields(self):
        """Right: 모든 필드로 생성."""
        content = ExtractedContent(
            url="https://example.com/event",
            page_type="google_forms",
            extraction_method="structured",
            title="이벤트 제목",
            description="이벤트 설명",
            content="본문 내용...",
            structured_data={"questions": []},
            images=["https://example.com/image.jpg"],
            metadata={"og:title": "OG 제목"},
            success=True,
            error=None,
        )

        assert content.title == "이벤트 제목"
        assert content.description == "이벤트 설명"
        assert content.structured_data == {"questions": []}
        assert len(content.images) == 1
        assert content.metadata["og:title"] == "OG 제목"

    def test_default_values(self):
        """Boundary: 기본값 확인."""
        content = ExtractedContent(
            url="https://example.com",
            page_type="generic",
            extraction_method="fallback",
        )

        assert content.title is None
        assert content.description is None
        assert content.content is None
        assert content.structured_data is None
        assert content.images == []
        assert content.metadata == {}
        assert content.success is True
        assert content.error is None

    def test_failed_extraction(self):
        """Error: 추출 실패 상태."""
        content = ExtractedContent(
            url="https://example.com",
            page_type="google_forms",
            extraction_method="failed",
            success=False,
            error="Timeout waiting for element",
        )

        assert content.success is False
        assert content.error == "Timeout waiting for element"
        assert content.extraction_method == "failed"

    def test_to_dict(self):
        """Right: to_dict 메서드 테스트."""
        content = ExtractedContent(
            url="https://example.com",
            page_type="generic",
            extraction_method="structured",
            title="테스트 제목",
            images=["img1.jpg", "img2.jpg"],
        )

        result = content.to_dict()

        assert isinstance(result, dict)
        assert result["url"] == "https://example.com"
        assert result["page_type"] == "generic"
        assert result["title"] == "테스트 제목"
        assert result["images"] == ["img1.jpg", "img2.jpg"]
        assert result["success"] is True

    def test_to_dict_with_none_values(self):
        """Boundary: None 값이 포함된 to_dict."""
        content = ExtractedContent(
            url="https://example.com",
            page_type="generic",
            extraction_method="fallback",
        )

        result = content.to_dict()

        assert result["title"] is None
        assert result["description"] is None
        assert result["content"] is None
        assert result["structured_data"] is None

    def test_images_list_isolation(self):
        """Boundary: images 기본값 리스트 격리 확인."""
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

        content1.images.append("test.jpg")

        # content2의 images는 영향받지 않아야 함
        assert len(content2.images) == 0

    def test_metadata_dict_isolation(self):
        """Boundary: metadata 기본값 딕셔너리 격리 확인."""
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

        content1.metadata["key"] = "value"

        # content2의 metadata는 영향받지 않아야 함
        assert "key" not in content2.metadata
