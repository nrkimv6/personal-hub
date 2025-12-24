"""Naver Form 페이지 추출기."""

from typing import Any, Dict, List

from playwright.async_api import Page

from .base import BaseExtractor, ExtractedContent


class NaverFormExtractor(BaseExtractor):
    """Naver Form 추출기.

    Naver Form의 .nsv_ 접두사 클래스를 사용하여 구조화된 데이터를 추출합니다.
    Vue.js 기반으로 구조가 일관성 있고 추출이 용이합니다.
    """

    page_type = "naver_form"

    # Naver Form 셀렉터
    SELECTORS = {
        "title": ".nsv_survey_reply_question_title",
        "description": ".nsv_rte.nsv_survey_reply_question_description .ql-editor",
        "image": ".nsv_survey_description_image",
        "period": ".nsv_survey_period_date",
        "questions": ".nsv_survey_item.nsv_survey_question",
        "question_title": ".nsv_survey_reply_question_title",
        "required": ".nsv_survey_question_required",
        "options": ".nsv_survey_question_label_multiple_choice_text",
        "input": ".nsv_survey_question_input",
    }

    def can_extract(self, url: str) -> bool:
        """Naver Form URL인지 확인.

        지원 URL 패턴:
        - https://form.naver.com/...
        - https://naver.me/... (리다이렉트 후)

        Args:
            url: 검사할 URL

        Returns:
            Naver Form URL이면 True
        """
        return "form.naver.com" in url or "survey.naver.com" in url

    async def extract(self, page: Page, url: str) -> ExtractedContent:
        """Naver Form에서 내용 추출.

        Args:
            page: Playwright Page 객체
            url: 페이지 URL

        Returns:
            추출된 내용 (폼 제목, 설명, 기간, 질문 목록)
        """
        try:
            # 동적 로딩 대기
            await page.wait_for_load_state("networkidle")

            # 셀렉터 대기
            try:
                await page.wait_for_selector(
                    self.SELECTORS["title"], timeout=5000
                )
            except Exception:
                # 마감된 폼이거나 로딩 실패
                pass

            # 폼 제목 추출
            title = await self.safe_text(page, self.SELECTORS["title"])

            # 폼 설명 추출
            description = await self.safe_text(page, self.SELECTORS["description"])

            # 기간 정보 추출
            period = await self.safe_text(page, self.SELECTORS["period"])

            # 이미지 추출
            images = []
            image_src = await self.safe_attribute(
                page, self.SELECTORS["image"], "src"
            )
            if image_src:
                images.append(image_src)

            # 질문 목록 추출
            questions = await self._extract_questions(page)

            # 구조화된 데이터
            structured_data = {
                "form_title": title,
                "form_description": description,
                "period": period,
                "questions": questions,
                "question_count": len(questions),
            }

            # 전체 텍스트 내용 (LLM 분석용)
            content_parts = [f"제목: {title}"]
            if description:
                content_parts.append(f"설명: {description}")
            if period:
                content_parts.append(f"기간: {period}")
            content_parts.append(f"\n질문 수: {len(questions)}개")

            for i, q in enumerate(questions, 1):
                q_text = f"\n{i}. {q['text']}"
                if q.get("required"):
                    q_text += " (필수)"
                if q.get("options"):
                    q_text += f"\n   옵션: {', '.join(q['options'])}"
                content_parts.append(q_text)

            return ExtractedContent(
                url=url,
                page_type=self.page_type,
                extraction_method="structured",
                title=title,
                description=description if description else None,
                content="\n".join(content_parts),
                structured_data=structured_data,
                images=images,
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

    async def _extract_questions(self, page: Page) -> List[Dict[str, Any]]:
        """질문 목록 추출.

        Args:
            page: Playwright Page 객체

        Returns:
            질문 정보 리스트
        """
        questions = []

        try:
            question_items = page.locator(self.SELECTORS["questions"])
            count = await question_items.count()

            for i in range(count):
                q = question_items.nth(i)

                # 질문 제목
                question_text = await q.locator(
                    self.SELECTORS["question_title"]
                ).text_content(timeout=2000)

                # 필수 여부
                required_count = await q.locator(self.SELECTORS["required"]).count()
                is_required = required_count > 0

                # 옵션 추출
                options = []
                option_elements = q.locator(self.SELECTORS["options"])
                option_count = await option_elements.count()
                for j in range(option_count):
                    option_text = await option_elements.nth(j).text_content(
                        timeout=1000
                    )
                    if option_text:
                        options.append(option_text.strip())

                if question_text:
                    questions.append(
                        {
                            "index": i,
                            "text": question_text.strip(),
                            "required": is_required,
                            "options": options,
                        }
                    )

        except Exception:
            pass

        return questions
