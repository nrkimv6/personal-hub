"""범용 페이지 추출기."""

from typing import Optional
from .base import BaseExtractor, ExtractedContent


class GenericExtractor(BaseExtractor):
    """범용 웹 페이지 추출기."""

    name = "GenericExtractor"

    async def extract(self, page, url: str) -> ExtractedContent:
        """페이지에서 기본 콘텐츠를 추출합니다."""
        try:
            # 페이지 로드
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)

            # OG 메타 추출
            og_data = await self.extract_og_meta(page)

            # 제목 추출
            title = await self.extract_page_title(page)

            # 본문 추출
            content = await self.extract_text_content(page)

            # 설명 추출 (meta description)
            description = await page.evaluate("""
                () => {
                    const el = document.querySelector('meta[name="description"]');
                    return el ? el.getAttribute('content') : null;
                }
            """)

            return ExtractedContent(
                url=url,
                url_type="generic",
                title=title or og_data.get("og_title"),
                description=description or og_data.get("og_description"),
                content=content,
                og_title=og_data.get("og_title"),
                og_description=og_data.get("og_description"),
                og_image=og_data.get("og_image"),
                extractor_used=self.name,
            )

        except Exception as e:
            return ExtractedContent(
                url=url,
                url_type="generic",
                extractor_used=self.name,
                error=str(e),
            )
