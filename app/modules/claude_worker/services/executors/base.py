"""LLMExecutorBase — Executor 전략 패턴 ABC."""

import json
import re
from abc import ABC, abstractmethod
from typing import Any


def parse_json_response_text(text: str) -> dict:
    """LLM 응답 텍스트에서 JSON dict를 추출한다."""
    errors = []

    # Tier 1: ```json ... ``` 블록 추출
    json_match = re.search(r"```json\s*([\s\S]*?)\s*```", text)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError as e:
            errors.append(f"markdown block: {e}")

    # Tier 2: 순수 JSON 시도
    stripped = text.strip()
    if stripped.startswith("{"):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError as e:
            errors.append(f"pure JSON: {e}")

    # Tier 3: { } 블록 추출 (brace counting으로 정확한 범위)
    start = text.find("{")
    if start != -1:
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"' and not escape:
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError as e:
                        errors.append(f"brace extraction: {e}")
                    break

    detail = "; ".join(errors) if errors else "no JSON structure found"
    raise ValueError(f"No valid JSON found in response ({detail})")


def normalize_json_payload(value: Any) -> dict:
    """structured_output/result envelope를 재귀적으로 벗겨 최종 dict payload를 반환한다."""
    if isinstance(value, str):
        parsed = parse_json_response_text(value)
        return normalize_json_payload(parsed)

    if not isinstance(value, dict):
        raise ValueError(f"Unsupported payload type: {type(value).__name__}")

    for key in ("structured_output", "result"):
        child = value.get(key)
        if child in (None, ""):
            continue
        try:
            return normalize_json_payload(child)
        except ValueError:
            continue

    return value


class LLMExecutorBase(ABC):
    """LLM CLI 실행 전략 추상 기반 클래스.

    각 provider(Claude, Gemini, Codex 등)별 Executor가 이를 상속한다.
    DB 접근 금지 — subprocess 실행과 결과 파싱만 담당.
    """

    @abstractmethod
    def execute(self, prompt: str, **kwargs) -> dict:
        """LLM CLI 실행.

        Returns:
            {"success": True, "result": {...}, "raw_response": "..."}
            또는
            {"success": False, "error": "..."}
        """

    def _parse_json_response(self, text: str) -> dict:
        """LLM 응답에서 JSON 추출.

        3-tier 시도:
          Tier 1: ```json ... ``` 마크다운 블록
          Tier 2: 순수 JSON (text.startswith("{"))
          Tier 3: brace counting으로 { } 블록 추출

        Args:
            text: LLM 응답 텍스트

        Returns:
            파싱된 JSON dict

        Raises:
            ValueError: JSON 파싱 실패
        """
        return parse_json_response_text(text)
