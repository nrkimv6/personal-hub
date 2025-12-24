"""이벤트 추출 프롬프트 테스트."""

import pytest

from app.modules.claude_worker.prompts.event_extract import (
    EVENT_JSON_SCHEMA,
    STRUCTURED_PROMPT_TEMPLATE,
    GENERIC_PROMPT_TEMPLATE,
    build_event_extract_prompt,
    parse_event_from_llm_response,
)
from app.services.page_extractor.base import ExtractedContent


class TestBuildEventExtractPrompt:
    """build_event_extract_prompt 테스트."""

    def test_structured_prompt_with_structured_data(self):
        """Right: 구조화된 데이터가 있으면 STRUCTURED_PROMPT_TEMPLATE 사용."""
        extracted = ExtractedContent(
            url="https://docs.google.com/forms/d/e/xxx/viewform",
            page_type="google_forms",
            extraction_method="structured",
            title="크리스마스 이벤트",
            description="12월 25일까지 진행되는 이벤트입니다.",
            content="이벤트 참여하기...",
            structured_data={
                "questions": ["이름을 입력해주세요", "연락처를 입력해주세요"],
                "form_title": "크리스마스 이벤트 참여"
            },
        )

        prompt = build_event_extract_prompt(extracted)

        # 구조화된 템플릿 키워드 확인
        assert "google_forms" in prompt
        assert "크리스마스 이벤트" in prompt
        assert "구조화된 데이터" in prompt
        assert "form_title" in prompt

    def test_generic_prompt_without_structured_data(self):
        """Right: 구조화된 데이터가 없으면 GENERIC_PROMPT_TEMPLATE 사용."""
        extracted = ExtractedContent(
            url="https://example.com/event",
            page_type="generic",
            extraction_method="fallback",
            title="연말 할인 이벤트",
            content="50% 할인 중...",
        )

        prompt = build_event_extract_prompt(extracted)

        # 범용 템플릿 키워드 확인
        assert "연말 할인 이벤트" in prompt
        assert "웹페이지 내용" in prompt
        assert "구조화된 데이터" not in prompt  # 없어야 함

    def test_content_truncation(self):
        """Boundary: 긴 콘텐츠는 8000자로 잘림."""
        long_content = "A" * 10000  # 10000자

        extracted = ExtractedContent(
            url="https://example.com",
            page_type="generic",
            extraction_method="fallback",
            title="Test",
            content=long_content,
        )

        prompt = build_event_extract_prompt(extracted)

        # 잘린 콘텐츠 확인
        assert "내용 생략" in prompt
        assert len(prompt) < len(long_content) + 2000  # 템플릿 오버헤드 포함

    def test_includes_json_schema(self):
        """Right: JSON 스키마가 포함됨."""
        extracted = ExtractedContent(
            url="https://example.com",
            page_type="generic",
            extraction_method="fallback",
            title="Test",
            content="Test content",
        )

        prompt = build_event_extract_prompt(extracted)

        # 스키마 필드 확인
        assert "event_type" in prompt
        assert "event_start" in prompt
        assert "event_end" in prompt
        assert "YYYY-MM-DD" in prompt

    def test_handles_none_values(self):
        """Boundary: None 값 처리."""
        extracted = ExtractedContent(
            url="https://example.com",
            page_type="generic",
            extraction_method="fallback",
            title=None,  # None
            content=None,  # None
        )

        prompt = build_event_extract_prompt(extracted)

        # 기본값으로 대체
        assert "제목 없음" in prompt


class TestParseEventFromLlmResponse:
    """parse_event_from_llm_response 테스트."""

    def test_parse_json_block(self):
        """Right: ```json 블록에서 파싱."""
        response = """분석 결과입니다:

```json
{
    "title": "크리스마스 이벤트",
    "event_type": "event",
    "event_start": "2024-12-01",
    "event_end": "2024-12-25",
    "organizer": "ABC 브랜드",
    "prizes": ["상품권 10만원", "텀블러"],
    "winner_count": 100
}
```

위 내용으로 이벤트가 생성됩니다."""

        result = parse_event_from_llm_response(response)

        assert result is not None
        assert result["title"] == "크리스마스 이벤트"
        assert result["event_type"] == "event"
        assert result["event_start"] == "2024-12-01"
        assert result["organizer"] == "ABC 브랜드"
        assert len(result["prizes"]) == 2
        assert result["winner_count"] == 100

    def test_parse_raw_json(self):
        """Right: 순수 JSON 응답 파싱."""
        response = """{
    "title": "신년 이벤트",
    "event_type": "popup",
    "prizes": []
}"""

        result = parse_event_from_llm_response(response)

        assert result is not None
        assert result["title"] == "신년 이벤트"
        assert result["event_type"] == "popup"

    def test_default_values(self):
        """Right: 기본값 설정."""
        response = """```json
{
    "title": "간단한 이벤트"
}
```"""

        result = parse_event_from_llm_response(response)

        assert result is not None
        assert result["event_type"] == "event"  # 기본값
        assert result["prizes"] == []  # 기본값
        assert result["purchase_required"] == "no"  # 기본값

    def test_returns_none_for_missing_title(self):
        """Boundary: title이 없으면 None 반환."""
        response = """```json
{
    "event_type": "event",
    "prizes": ["상품"]
}
```"""

        result = parse_event_from_llm_response(response)

        assert result is None  # title 필수

    def test_returns_none_for_invalid_json(self):
        """Boundary: 잘못된 JSON이면 None 반환."""
        response = "이것은 JSON이 아닙니다."

        result = parse_event_from_llm_response(response)

        assert result is None

    def test_returns_none_for_empty_response(self):
        """Boundary: 빈 응답이면 None 반환."""
        result = parse_event_from_llm_response("")
        assert result is None

        result = parse_event_from_llm_response(None)
        assert result is None

    def test_returns_none_for_non_dict(self):
        """Boundary: 딕셔너리가 아니면 None 반환."""
        response = """```json
["item1", "item2"]
```"""

        result = parse_event_from_llm_response(response)

        assert result is None


class TestEventJsonSchema:
    """EVENT_JSON_SCHEMA 상수 테스트."""

    def test_contains_required_fields(self):
        """Right: 필수 필드 포함 확인."""
        assert "title" in EVENT_JSON_SCHEMA
        assert "event_type" in EVENT_JSON_SCHEMA
        assert "event_start" in EVENT_JSON_SCHEMA
        assert "event_end" in EVENT_JSON_SCHEMA

    def test_contains_optional_fields(self):
        """Right: 선택 필드 포함 확인."""
        assert "organizer" in EVENT_JSON_SCHEMA
        assert "prizes" in EVENT_JSON_SCHEMA
        assert "winner_count" in EVENT_JSON_SCHEMA
        assert "purchase_required" in EVENT_JSON_SCHEMA
        assert "location_venue" in EVENT_JSON_SCHEMA
