"""Page Extractor 기본 클래스 및 데이터 구조."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from playwright.async_api import Page


@dataclass
class ExtractedContent:
    """추출된 페이지 내용."""

    url: str
    page_type: str
    extraction_method: str  # "structured" | "generic" | "fallback"

    # 기본 정보
    title: Optional[str] = None
    description: Optional[str] = None
    content: Optional[str] = None

    # 구조화된 데이터 (페이지 유형별)
    structured_data: Optional[Dict[str, Any]] = None

    # 이미지
    images: List[str] = field(default_factory=list)

    # 메타데이터 (OG 태그 등)
    metadata: Dict[str, str] = field(default_factory=dict)

    # 추출 성공 여부
    success: bool = True
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환."""
        return {
            "url": self.url,
            "page_type": self.page_type,
            "extraction_method": self.extraction_method,
            "title": self.title,
            "description": self.description,
            "content": self.content,
            "structured_data": self.structured_data,
            "images": self.images,
            "metadata": self.metadata,
            "success": self.success,
            "error": self.error,
        }


class BaseExtractor(ABC):
    """페이지 추출기 베이스 클래스."""

    # 페이지 유형 식별자 (서브클래스에서 오버라이드)
    page_type: str = "unknown"

    @abstractmethod
    def can_extract(self, url: str) -> bool:
        """이 추출기가 해당 URL을 처리할 수 있는지 확인.

        Args:
            url: 검사할 URL

        Returns:
            처리 가능하면 True
        """
        pass

    @abstractmethod
    async def extract(self, page: Page, url: str) -> ExtractedContent:
        """페이지에서 내용 추출.

        Args:
            page: Playwright Page 객체
            url: 페이지 URL

        Returns:
            추출된 내용
        """
        pass

    async def safe_text(
        self,
        page: Page,
        selector: str,
        default: str = "",
        timeout: int = 3000,
    ) -> str:
        """안전하게 텍스트 추출.

        Args:
            page: Playwright Page 객체
            selector: CSS 셀렉터
            default: 실패 시 기본값
            timeout: 대기 시간 (ms)

        Returns:
            추출된 텍스트 또는 기본값
        """
        try:
            element = page.locator(selector).first
            text = await element.text_content(timeout=timeout)
            return text.strip() if text else default
        except Exception:
            return default

    async def safe_attribute(
        self,
        page: Page,
        selector: str,
        attribute: str,
        default: str = "",
        timeout: int = 3000,
    ) -> str:
        """안전하게 속성 추출.

        Args:
            page: Playwright Page 객체
            selector: CSS 셀렉터
            attribute: 속성명
            default: 실패 시 기본값
            timeout: 대기 시간 (ms)

        Returns:
            추출된 속성값 또는 기본값
        """
        try:
            element = page.locator(selector).first
            value = await element.get_attribute(attribute, timeout=timeout)
            return value.strip() if value else default
        except Exception:
            return default

    async def safe_all_texts(
        self,
        page: Page,
        selector: str,
        timeout: int = 3000,
    ) -> List[str]:
        """안전하게 여러 요소의 텍스트 추출.

        Args:
            page: Playwright Page 객체
            selector: CSS 셀렉터
            timeout: 대기 시간 (ms)

        Returns:
            추출된 텍스트 리스트
        """
        try:
            elements = page.locator(selector)
            count = await elements.count()
            texts = []
            for i in range(count):
                text = await elements.nth(i).text_content(timeout=timeout)
                if text:
                    texts.append(text.strip())
            return texts
        except Exception:
            return []

    async def get_og_metadata(self, page: Page) -> Dict[str, str]:
        """Open Graph 메타데이터 추출.

        Args:
            page: Playwright Page 객체

        Returns:
            OG 메타데이터 딕셔너리
        """
        metadata = {}
        og_properties = [
            "og:title",
            "og:description",
            "og:image",
            "og:url",
            "og:type",
            "og:site_name",
        ]

        for prop in og_properties:
            value = await self.safe_attribute(
                page, f'meta[property="{prop}"]', "content"
            )
            if value:
                # "og:" 접두사 제거
                key = prop.replace("og:", "")
                metadata[key] = value

        # Twitter Card도 추가
        twitter_properties = ["twitter:title", "twitter:description", "twitter:image"]
        for prop in twitter_properties:
            if prop.replace("twitter:", "") not in metadata:
                value = await self.safe_attribute(
                    page, f'meta[name="{prop}"]', "content"
                )
                if value:
                    key = prop.replace("twitter:", "")
                    metadata[key] = value

        return metadata
