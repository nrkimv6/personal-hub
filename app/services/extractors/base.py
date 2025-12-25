"""추출기 기본 클래스."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Any


@dataclass
class ExtractedContent:
    """추출된 콘텐츠 데이터 클래스."""

    url: str
    url_type: str
    title: Optional[str] = None
    description: Optional[str] = None
    content: Optional[str] = None
    extracted_data: Optional[dict] = None
    og_title: Optional[str] = None
    og_description: Optional[str] = None
    og_image: Optional[str] = None
    extractor_used: Optional[str] = None
    raw_html: Optional[str] = None
    error: Optional[str] = None


class BaseExtractor(ABC):
    """콘텐츠 추출기 기본 클래스."""

    name: str = "base"

    @abstractmethod
    async def extract(self, page, url: str) -> ExtractedContent:
        """
        페이지에서 콘텐츠를 추출합니다.

        Args:
            page: Playwright Page 객체
            url: 추출할 URL

        Returns:
            ExtractedContent: 추출된 콘텐츠
        """
        pass

    async def extract_og_meta(self, page) -> dict:
        """Open Graph 메타데이터 추출."""
        try:
            og_data = await page.evaluate("""
                () => {
                    const getMeta = (property) => {
                        const el = document.querySelector(`meta[property="${property}"]`) ||
                                   document.querySelector(`meta[name="${property}"]`);
                        return el ? el.getAttribute('content') : null;
                    };
                    return {
                        og_title: getMeta('og:title'),
                        og_description: getMeta('og:description'),
                        og_image: getMeta('og:image'),
                    };
                }
            """)
            return og_data
        except Exception:
            return {}

    async def extract_page_title(self, page) -> Optional[str]:
        """페이지 제목 추출."""
        try:
            return await page.title()
        except Exception:
            return None

    async def extract_text_content(self, page) -> Optional[str]:
        """페이지 본문 텍스트 추출."""
        try:
            # body 내 텍스트 추출 (스크립트, 스타일 제외)
            content = await page.evaluate("""
                () => {
                    const body = document.body.cloneNode(true);
                    // 불필요한 요소 제거
                    body.querySelectorAll('script, style, noscript, iframe').forEach(el => el.remove());
                    return body.innerText.trim().substring(0, 10000);
                }
            """)
            return content
        except Exception:
            return None
