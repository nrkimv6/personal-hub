"""Naver Blog 페이지 추출기 (PC/Mobile)."""

from typing import List

from playwright.async_api import Page

from .base import BaseExtractor, ExtractedContent


class NaverBlogPCExtractor(BaseExtractor):
    """Naver Blog PC 버전 추출기.

    PC 버전 네이버 블로그는 iframe 구조를 사용하므로
    #mainFrame iframe 내부에서 콘텐츠를 추출합니다.
    """

    page_type = "naver_blog_pc"

    # Naver Blog PC 셀렉터
    SELECTORS = {
        "iframe": "#mainFrame",
        "title": ".se-title-text, .pcol1",
        "content": ".se-main-container",
        "author": ".nick, .blog_author",
        "date": ".se_publishDate, .date",
        "images": ".se-image-resource, img[src*='blogfiles']",
    }

    def can_extract(self, url: str) -> bool:
        """Naver Blog PC URL인지 확인.

        지원 URL 패턴:
        - https://blog.naver.com/... (m.blog 제외)

        Args:
            url: 검사할 URL

        Returns:
            Naver Blog PC URL이면 True
        """
        return "blog.naver.com" in url and "m.blog" not in url

    async def extract(self, page: Page, url: str) -> ExtractedContent:
        """Naver Blog PC에서 내용 추출.

        Args:
            page: Playwright Page 객체
            url: 페이지 URL

        Returns:
            추출된 내용
        """
        try:
            # 동적 로딩 대기
            await page.wait_for_load_state("networkidle")

            # iframe 접근
            frame = page.frame_locator(self.SELECTORS["iframe"])

            # iframe 내부 콘텐츠 로딩 대기
            try:
                await frame.locator(self.SELECTORS["title"]).first.wait_for(
                    timeout=5000
                )
            except Exception:
                pass

            # 제목 추출
            title = ""
            try:
                title = await frame.locator(self.SELECTORS["title"]).first.text_content(
                    timeout=3000
                )
                title = title.strip() if title else ""
            except Exception:
                pass

            # 본문 추출
            content = ""
            try:
                content = await frame.locator(
                    self.SELECTORS["content"]
                ).first.text_content(timeout=5000)
                content = content.strip() if content else ""
            except Exception:
                pass

            # 작성자 추출
            author = ""
            try:
                author = await frame.locator(self.SELECTORS["author"]).first.text_content(
                    timeout=2000
                )
                author = author.strip() if author else ""
            except Exception:
                pass

            # 날짜 추출
            date = ""
            try:
                date = await frame.locator(self.SELECTORS["date"]).first.text_content(
                    timeout=2000
                )
                date = date.strip() if date else ""
            except Exception:
                pass

            # 이미지 추출
            images = await self._extract_images(frame)

            # OG 메타데이터 (메인 페이지에서)
            metadata = await self.get_og_metadata(page)

            # 구조화된 데이터
            structured_data = {
                "author": author,
                "date": date,
                "image_count": len(images),
            }

            return ExtractedContent(
                url=url,
                page_type=self.page_type,
                extraction_method="structured",
                title=title or metadata.get("title", ""),
                description=metadata.get("description", ""),
                content=content,
                structured_data=structured_data,
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

    async def _extract_images(self, frame) -> List[str]:
        """이미지 URL 추출.

        Args:
            frame: iframe FrameLocator

        Returns:
            이미지 URL 리스트
        """
        images = []
        try:
            img_elements = frame.locator(self.SELECTORS["images"])
            count = await img_elements.count()

            for i in range(min(count, 10)):  # 최대 10개
                src = await img_elements.nth(i).get_attribute("src", timeout=1000)
                if src and src not in images:
                    images.append(src)
        except Exception:
            pass

        return images


class NaverBlogMobileExtractor(BaseExtractor):
    """Naver Blog Mobile 버전 추출기.

    Mobile 버전은 iframe 없이 직접 접근 가능하며,
    .__se_ 접두사 클래스를 사용합니다.
    """

    page_type = "naver_blog_mobile"

    # Naver Blog Mobile 셀렉터
    SELECTORS = {
        "title": ".se_title, .tit_h3, .se-title-text",
        "content": ".se_component_wrap, .post_ct, .se-main-container",
        "images": "img[src*='blogfiles'], img.__se_image_link",
    }

    def can_extract(self, url: str) -> bool:
        """Naver Blog Mobile URL인지 확인.

        지원 URL 패턴:
        - https://m.blog.naver.com/...

        Args:
            url: 검사할 URL

        Returns:
            Naver Blog Mobile URL이면 True
        """
        return "m.blog.naver.com" in url

    async def extract(self, page: Page, url: str) -> ExtractedContent:
        """Naver Blog Mobile에서 내용 추출.

        Args:
            page: Playwright Page 객체
            url: 페이지 URL

        Returns:
            추출된 내용
        """
        try:
            # 동적 로딩 대기
            await page.wait_for_load_state("networkidle")

            # 셀렉터 대기
            try:
                await page.wait_for_selector(self.SELECTORS["title"], timeout=5000)
            except Exception:
                pass

            # 제목 추출
            title = await self.safe_text(page, self.SELECTORS["title"])

            # 본문 추출
            content = await self.safe_text(page, self.SELECTORS["content"])

            # 이미지 추출
            images = await self._extract_images(page)

            # OG 메타데이터
            metadata = await self.get_og_metadata(page)

            return ExtractedContent(
                url=url,
                page_type=self.page_type,
                extraction_method="structured",
                title=title or metadata.get("title", ""),
                description=metadata.get("description", ""),
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

    async def _extract_images(self, page: Page) -> List[str]:
        """이미지 URL 추출.

        Args:
            page: Playwright Page 객체

        Returns:
            이미지 URL 리스트
        """
        images = []
        try:
            img_elements = page.locator(self.SELECTORS["images"])
            count = await img_elements.count()

            for i in range(min(count, 10)):  # 최대 10개
                src = await img_elements.nth(i).get_attribute("src", timeout=1000)
                if src and src not in images:
                    images.append(src)
        except Exception:
            pass

        return images
