"""네이버 폼 추출기."""

from typing import Optional
from .base import BaseExtractor, ExtractedContent


class NaverFormExtractor(BaseExtractor):
    """네이버 폼 콘텐츠 추출기."""

    name = "NaverFormExtractor"

    async def extract(self, page, url: str) -> ExtractedContent:
        """네이버 폼에서 콘텐츠를 추출합니다."""
        try:
            # 페이지 로드
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)

            # OG 메타 추출
            og_data = await self.extract_og_meta(page)

            # 폼 제목 추출
            title = await self._extract_form_title(page)

            # 폼 설명 추출
            description = await self._extract_form_description(page)

            # 폼 질문들 추출
            questions = await self._extract_questions(page)

            # 전체 텍스트 콘텐츠
            content = await self.extract_text_content(page)

            return ExtractedContent(
                url=url,
                url_type="naver_form",
                title=title or og_data.get("og_title"),
                description=description or og_data.get("og_description"),
                content=content,
                extracted_data={"questions": questions} if questions else None,
                og_title=og_data.get("og_title"),
                og_description=og_data.get("og_description"),
                og_image=og_data.get("og_image"),
                extractor_used=self.name,
            )

        except Exception as e:
            return ExtractedContent(
                url=url,
                url_type="naver_form",
                extractor_used=self.name,
                error=str(e),
            )

    async def _extract_form_title(self, page) -> Optional[str]:
        """폼 제목 추출."""
        try:
            selectors = [
                '.form_title',
                '.FormTitle',
                'h1.title',
                '.survey_title',
            ]
            for selector in selectors:
                el = await page.query_selector(selector)
                if el:
                    text = await el.inner_text()
                    if text and text.strip():
                        return text.strip()
            return await self.extract_page_title(page)
        except Exception:
            return None

    async def _extract_form_description(self, page) -> Optional[str]:
        """폼 설명 추출."""
        try:
            selectors = [
                '.form_description',
                '.FormDescription',
                '.survey_description',
            ]
            for selector in selectors:
                el = await page.query_selector(selector)
                if el:
                    text = await el.inner_text()
                    if text and text.strip():
                        return text.strip()
            return None
        except Exception:
            return None

    async def _extract_questions(self, page) -> list:
        """폼 질문 목록 추출."""
        try:
            questions = await page.evaluate("""
                () => {
                    const questions = [];
                    const containers = document.querySelectorAll('.question_item, .QuestionItem, .survey_question');

                    containers.forEach((container, index) => {
                        const titleEl = container.querySelector('.question_title, .QuestionTitle, .q_title');
                        const title = titleEl ? titleEl.innerText.trim() : null;

                        if (title) {
                            questions.push({
                                index: index + 1,
                                question: title,
                            });
                        }
                    });

                    return questions;
                }
            """)
            return questions
        except Exception:
            return []
