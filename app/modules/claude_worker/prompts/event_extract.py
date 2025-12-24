"""이벤트 추출 프롬프트 템플릿."""

from typing import Any, Dict

from app.services.page_extractor.base import ExtractedContent

# 이벤트 JSON 스키마
EVENT_JSON_SCHEMA = """{
    "title": "이벤트 제목 (필수)",
    "event_type": "event|popup|ambassador|other (기본: event)",
    "event_start": "YYYY-MM-DD 형식 또는 null",
    "event_end": "YYYY-MM-DD 형식 또는 null",
    "announcement_date": "YYYY-MM-DD 형식 또는 null (당첨자 발표일)",
    "organizer": "주최사/브랜드명 또는 null",
    "summary": "이벤트 요약 (2-3문장)",
    "prizes": ["경품1", "경품2", ...] 또는 [],
    "winner_count": 당첨자 수 (숫자) 또는 null,
    "purchase_required": "yes_all|yes_partial|no (구매 필수 여부)",
    "location_venue": "장소명 (팝업 스토어인 경우) 또는 null",
    "location_address": "주소 (팝업 스토어인 경우) 또는 null"
}"""

# 구조화된 데이터용 프롬프트 템플릿
STRUCTURED_PROMPT_TEMPLATE = """다음은 {page_type} 페이지에서 구조화된 형태로 추출한 데이터입니다.
이 정보를 분석하여 이벤트/행사 정보를 추출해주세요.

[페이지 URL]
{url}

[페이지 제목]
{title}

{description_section}

[추출된 내용]
{content}

{structured_data_section}

## 분석 요청
위 정보를 분석하여 다음 항목들을 추출해주세요:
- 이벤트 기간 (시작일, 종료일, 당첨자 발표일)
- 참여 조건 (구매 필수 여부)
- 경품 정보 및 당첨자 수
- 주최사/브랜드명
- 이벤트 유형 (일반 이벤트, 팝업스토어, 앰버서더 모집 등)

## 응답 형식
반드시 아래 JSON 형식으로만 응답해주세요. 다른 설명은 포함하지 마세요.
```json
{json_schema}
```

중요:
- 날짜는 반드시 YYYY-MM-DD 형식으로 변환해주세요
- 확실하지 않은 정보는 null로 표시해주세요
- 이벤트 제목(title)은 반드시 입력해주세요
"""

# 범용 텍스트용 프롬프트 템플릿
GENERIC_PROMPT_TEMPLATE = """다음 웹페이지 내용에서 이벤트/행사 정보를 추출해주세요.

[페이지 URL]
{url}

[페이지 제목]
{title}

{description_section}

[페이지 내용]
{content}

## 분석 요청
위 정보를 분석하여 다음 항목들을 추출해주세요:
- 이벤트 기간 (시작일, 종료일, 당첨자 발표일)
- 참여 조건 (구매 필수 여부)
- 경품 정보 및 당첨자 수
- 주최사/브랜드명
- 이벤트 유형 (일반 이벤트, 팝업스토어, 앰버서더 모집 등)

## 응답 형식
반드시 아래 JSON 형식으로만 응답해주세요. 다른 설명은 포함하지 마세요.
```json
{json_schema}
```

중요:
- 날짜는 반드시 YYYY-MM-DD 형식으로 변환해주세요
- 확실하지 않은 정보는 null로 표시해주세요
- 이벤트 제목(title)은 반드시 입력해주세요
"""


def build_event_extract_prompt(extracted: ExtractedContent) -> str:
    """추출된 콘텐츠에서 이벤트 추출 프롬프트 생성.

    Args:
        extracted: ExtractedContent 객체

    Returns:
        LLM에 전달할 프롬프트 문자열
    """
    # 설명 섹션
    description_section = ""
    if extracted.description:
        description_section = f"[페이지 설명]\n{extracted.description}\n"

    # 구조화된 데이터 섹션
    structured_data_section = ""
    if extracted.structured_data:
        import json

        structured_data_section = f"[구조화된 데이터]\n```json\n{json.dumps(extracted.structured_data, ensure_ascii=False, indent=2)}\n```\n"

    # 콘텐츠 길이 제한 (토큰 절약)
    content = extracted.content or ""
    if len(content) > 8000:
        content = content[:8000] + "\n... (내용 생략)"

    # 템플릿 선택
    if extracted.extraction_method == "structured" and extracted.structured_data:
        template = STRUCTURED_PROMPT_TEMPLATE
    else:
        template = GENERIC_PROMPT_TEMPLATE

    # 프롬프트 생성
    prompt = template.format(
        page_type=extracted.page_type,
        url=extracted.url,
        title=extracted.title or "제목 없음",
        description_section=description_section,
        content=content,
        structured_data_section=structured_data_section,
        json_schema=EVENT_JSON_SCHEMA,
    )

    return prompt


def parse_event_from_llm_response(response: str) -> Dict[str, Any] | None:
    """LLM 응답에서 이벤트 정보 파싱.

    Args:
        response: LLM 응답 문자열

    Returns:
        파싱된 이벤트 정보 딕셔너리, 실패 시 None
    """
    import json
    import re

    if not response:
        return None

    try:
        # JSON 블록 추출 시도
        json_match = re.search(r"```json\s*([\s\S]*?)\s*```", response)
        if json_match:
            json_str = json_match.group(1)
        else:
            # JSON 블록이 없으면 전체를 JSON으로 파싱 시도
            json_str = response

        # JSON 파싱
        data = json.loads(json_str)

        # 필수 필드 검증
        if not isinstance(data, dict):
            return None

        if not data.get("title"):
            return None

        # 기본값 설정
        data.setdefault("event_type", "event")
        data.setdefault("prizes", [])
        data.setdefault("purchase_required", "no")

        return data

    except (json.JSONDecodeError, AttributeError):
        return None
