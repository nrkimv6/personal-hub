"""범용 페이지 추출기 (Fallback)."""

from playwright.async_api import Page

from .base import BaseExtractor, ExtractedContent


class GenericExtractor(BaseExtractor):
    """범용 페이지 추출기.

    시맨틱 태그와 OG 메타데이터를 기반으로 페이지 내용을 추출합니다.
    다른 추출기가 처리하지 못하는 모든 URL에 대한 Fallback으로 사용됩니다.
    """

    page_type = "generic"

    def can_extract(self, url: str) -> bool:
        """모든 URL을 처리할 수 있음 (Fallback).

        Returns:
            항상 True
        """
        return True

    async def extract(self, page: Page, url: str) -> ExtractedContent:
        """페이지에서 내용 추출.

        추출 우선순위:
        1. 시맨틱 태그 (h1, article, main)
        2. OG 메타데이터
        3. 전체 body 텍스트 (최후의 수단)

        Args:
            page: Playwright Page 객체
            url: 페이지 URL

        Returns:
            추출된 내용
        """
        try:
            # OG 메타데이터 추출
            metadata = await self.get_og_metadata(page)

            # Level 1: 시맨틱 태그에서 제목 추출
            title = await self.safe_text(page, "h1")
            if not title:
                title = await self.safe_text(page, '[role="heading"]')
            if not title:
                title = metadata.get("title", "")
            if not title:
                # 페이지 타이틀 사용
                title = await page.title()

            # Level 2: 시맨틱 태그에서 본문 추출
            content = await self.safe_text(page, "article")
            if not content:
                content = await self.safe_text(page, "main")
            if not content:
                content = await self.safe_text(page, '[role="main"]')

            # Level 3: 전체 body 텍스트 (최후의 수단)
            extraction_method = "structured"
            if not content:
                extraction_method = "fallback"
                try:
                    body_text = await page.locator("body").text_content(timeout=5000)
                    if body_text:
                        # 너무 긴 텍스트는 잘라냄
                        content = body_text.strip()[:10000]
                except Exception:
                    content = ""

            # 설명 추출
            description = metadata.get("description", "")
            if not description:
                description = await self.safe_attribute(
                    page, 'meta[name="description"]', "content"
                )

            # 이미지 추출 (OG 이미지 우선)
            images = []
            og_image = metadata.get("image", "")
            if og_image:
                images.append(og_image)

            # 추가 이미지 (최대 5개)
            try:
                img_elements = page.locator("article img, main img, .content img")
                count = await img_elements.count()
                for i in range(min(count, 5)):
                    src = await img_elements.nth(i).get_attribute("src", timeout=1000)
                    if src and src not in images:
                        images.append(src)
            except Exception:
                pass

            return ExtractedContent(
                url=url,
                page_type=self.page_type,
                extraction_method=extraction_method,
                title=title,
                description=description,
                content=content,
                images=images,
                metadata=metadata,
                success=True,
            )

        except Exception as e:
            return ExtractedContent(
                url=url,
                page_type=self.page_type,
                extraction_method="failed",
                success=False,
                error=str(e),
            )
