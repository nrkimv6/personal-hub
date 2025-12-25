"""네이버 블로그 추출기."""

from typing import Optional
from .base import BaseExtractor, ExtractedContent


class NaverBlogExtractor(BaseExtractor):
    """네이버 블로그 콘텐츠 추출기."""

    name = "NaverBlogExtractor"

    async def extract(self, page, url: str) -> ExtractedContent:
        """네이버 블로그에서 콘텐츠를 추출합니다."""
        try:
            # 페이지 로드
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)

            # 블로그는 iframe 안에 있을 수 있음
            content_frame = await self._get_content_frame(page)
            target = content_frame if content_frame else page

            # OG 메타 추출 (메인 페이지에서)
            og_data = await self.extract_og_meta(page)

            # 제목 추출
            title = await self._extract_post_title(target)

            # 본문 추출
            content = await self._extract_post_content(target)

            # 이미지 추출
            images = await self._extract_images(target)

            return ExtractedContent(
                url=url,
                url_type="naver_blog",
                title=title or og_data.get("og_title"),
                description=og_data.get("og_description"),
                content=content,
                extracted_data={"images": images} if images else None,
                og_title=og_data.get("og_title"),
                og_description=og_data.get("og_description"),
                og_image=og_data.get("og_image"),
                extractor_used=self.name,
            )

        except Exception as e:
            return ExtractedContent(
                url=url,
                url_type="naver_blog",
                extractor_used=self.name,
                error=str(e),
            )

    async def _get_content_frame(self, page):
        """블로그 콘텐츠가 있는 iframe 찾기."""
        try:
            # 네이버 블로그 iframe 선택자들
            iframe_selectors = [
                'iframe#mainFrame',
                'iframe[name="mainFrame"]',
                '#post-view iframe',
            ]
            for selector in iframe_selectors:
                iframe = await page.query_selector(selector)
                if iframe:
                    return await iframe.content_frame()
            return None
        except Exception:
            return None

    async def _extract_post_title(self, target) -> Optional[str]:
        """게시글 제목 추출."""
        try:
            selectors = [
                '.se-title-text',
                '.se_title',
                '.pcol1',
                '.se-module-text-paragraph',
                '.post-title',
                'h3.se_textarea',
            ]
            for selector in selectors:
                el = await target.query_selector(selector)
                if el:
                    text = await el.inner_text()
                    if text and text.strip():
                        return text.strip()

            # fallback: 페이지 제목
            if hasattr(target, 'title'):
                return await target.title()
            return None
        except Exception:
            return None

    async def _extract_post_content(self, target) -> Optional[str]:
        """게시글 본문 추출."""
        try:
            selectors = [
                '.se-main-container',
                '#postViewArea',
                '.post_ct',
                '.se_component_wrap',
            ]
            for selector in selectors:
                el = await target.query_selector(selector)
                if el:
                    text = await el.inner_text()
                    if text and text.strip():
                        return text.strip()[:10000]  # 최대 10000자
            return None
        except Exception:
            return None

    async def _extract_images(self, target) -> list:
        """게시글 이미지 URL 추출."""
        try:
            images = await target.evaluate("""
                () => {
                    const images = [];
                    const imgElements = document.querySelectorAll('.se-image-resource, .se_mediaImage, img[src*="blogfiles"]');

                    imgElements.forEach((img) => {
                        const src = img.getAttribute('data-lazy-src') || img.getAttribute('src');
                        if (src && !images.includes(src)) {
                            images.push(src);
                        }
                    });

                    return images.slice(0, 10);  // 최대 10개
                }
            """)
            return images
        except Exception:
            return []
