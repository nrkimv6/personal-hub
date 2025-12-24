"""Google Forms 페이지 추출기."""

from typing import Any, Dict, List

from playwright.async_api import Page

from .base import BaseExtractor, ExtractedContent


class GoogleFormsExtractor(BaseExtractor):
    """Google Forms 추출기.

    Google Forms의 role 속성 기반 셀렉터를 사용하여 구조화된 데이터를 추출합니다.
    난독화된 클래스명 대신 role 속성을 사용하여 안정적인 추출이 가능합니다.
    """

    page_type = "google_forms"

    # Google Forms 셀렉터 (role 속성 기반)
    SELECTORS = {
        "title": 'div[role="heading"]',
        "questions": 'div[role="listitem"]',
        "question_title": 'div[role="heading"]',
        "required": '[aria-label*="필수"]',
        "text_input": 'input[type="text"]',
        "textarea": "textarea",
        "radio": '[role="radio"]',
        "checkbox": '[role="checkbox"]',
        "listbox": '[role="listbox"]',
    }

    def can_extract(self, url: str) -> bool:
        """Google Forms URL인지 확인.

        지원 URL 패턴:
        - https://docs.google.com/forms/...
        - https://forms.gle/...

        Args:
            url: 검사할 URL

        Returns:
            Google Forms URL이면 True
        """
        return "docs.google.com/forms" in url or "forms.gle/" in url

    async def extract(self, page: Page, url: str) -> ExtractedContent:
        """Google Forms에서 내용 추출.

        Args:
            page: Playwright Page 객체
            url: 페이지 URL

        Returns:
            추출된 내용 (폼 제목, 설명, 질문 목록)
        """
        try:
            # 동적 로딩 대기
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(2000)

            # 마감된 폼 체크
            closed_message = await self.safe_text(
                page, 'div:has-text("더 이상 응답을 받지 않습니다")'
            )
            if closed_message:
                return ExtractedContent(
                    url=url,
                    page_type=self.page_type,
                    extraction_method="structured",
                    title="마감된 폼",
                    description="이 폼은 더 이상 응답을 받지 않습니다.",
                    success=True,
                )

            # 폼 제목 추출 (첫 번째 heading)
            title = await self.safe_text(page, self.SELECTORS["title"])

            # 폼 설명 추출 (제목 다음 요소)
            description = await page.evaluate("""
                () => {
                    const heading = document.querySelector('div[role="heading"]');
                    if (heading && heading.nextElementSibling) {
                        return heading.nextElementSibling.textContent || '';
                    }
                    return '';
                }
            """)

            # 질문 목록 추출
            questions = await self._extract_questions(page)

            # 구조화된 데이터
            structured_data = {
                "form_title": title,
                "form_description": description.strip() if description else "",
                "questions": questions,
                "question_count": len(questions),
            }

            # 전체 텍스트 내용 (LLM 분석용)
            content_parts = [f"제목: {title}"]
            if description:
                content_parts.append(f"설명: {description}")
            content_parts.append(f"\n질문 수: {len(questions)}개")

            for i, q in enumerate(questions, 1):
                q_text = f"\n{i}. {q['text']}"
                if q.get("required"):
                    q_text += " (필수)"
                if q.get("description"):
                    q_text += f"\n   {q['description']}"
                if q.get("options"):
                    q_text += f"\n   옵션: {', '.join(q['options'])}"
                content_parts.append(q_text)

            return ExtractedContent(
                url=url,
                page_type=self.page_type,
                extraction_method="structured",
                title=title,
                description=description.strip() if description else None,
                content="\n".join(content_parts),
                structured_data=structured_data,
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
                question_text = await self.safe_text(
                    page,
                    f'{self.SELECTORS["questions"]}:nth-child({i + 1}) {self.SELECTORS["question_title"]}',
                )

                # 질문 설명
                question_desc = await q.evaluate("""
                    (el) => {
                        const heading = el.querySelector('div[role="heading"]');
                        if (heading && heading.nextElementSibling) {
                            const text = heading.nextElementSibling.textContent;
                            // 옵션 텍스트가 아닌 설명만 반환
                            if (text && !text.includes('옵션')) {
                                return text.trim();
                            }
                        }
                        return '';
                    }
                """)

                # 필수 여부
                required_count = await q.locator(self.SELECTORS["required"]).count()
                is_required = required_count > 0

                # 입력 타입 판별
                question_type = await self._detect_question_type(q)

                # 옵션 추출 (객관식인 경우)
                options = []
                if question_type in ("radio", "checkbox"):
                    options = await self._extract_options(q, question_type)

                if question_text:  # 빈 질문 제외
                    questions.append(
                        {
                            "index": i,
                            "text": question_text.strip(),
                            "description": question_desc if question_desc else None,
                            "required": is_required,
                            "type": question_type,
                            "options": options,
                        }
                    )

        except Exception:
            pass

        return questions

    async def _detect_question_type(self, question_element) -> str:
        """질문 타입 감지.

        Args:
            question_element: 질문 요소 Locator

        Returns:
            질문 타입 문자열
        """
        try:
            has_radio = await question_element.locator(self.SELECTORS["radio"]).count()
            if has_radio > 0:
                return "radio"

            has_checkbox = await question_element.locator(
                self.SELECTORS["checkbox"]
            ).count()
            if has_checkbox > 0:
                return "checkbox"

            has_textarea = await question_element.locator(
                self.SELECTORS["textarea"]
            ).count()
            if has_textarea > 0:
                return "textarea"

            has_text = await question_element.locator(
                self.SELECTORS["text_input"]
            ).count()
            if has_text > 0:
                return "text"

            has_listbox = await question_element.locator(
                self.SELECTORS["listbox"]
            ).count()
            if has_listbox > 0:
                return "dropdown"

        except Exception:
            pass

        return "unknown"

    async def _extract_options(
        self, question_element, question_type: str
    ) -> List[str]:
        """객관식 옵션 추출.

        Args:
            question_element: 질문 요소 Locator
            question_type: 질문 타입 (radio 또는 checkbox)

        Returns:
            옵션 텍스트 리스트
        """
        options = []
        try:
            selector = self.SELECTORS[question_type]
            option_elements = question_element.locator(selector)
            count = await option_elements.count()

            for i in range(count):
                label = await option_elements.nth(i).get_attribute(
                    "aria-label", timeout=1000
                )
                if label:
                    options.append(label)
        except Exception:
            pass

        return options
