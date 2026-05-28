"""event_sse — SSE 직렬화 순수 함수

C 도메인: sse_format, build_log_line_payload
상태 없음. 외부 의존성 없음. 입출력 검증만으로 테스트 가능.
"""
import json
import re


_LOG_TAG_PATTERN = re.compile(r"^\s*(?:\[(?P<time>\d{2}:\d{2}:\d{2})\]\s*)?\[(?P<tag>[A-Z_]+)\]\s*(?P<message>.*)", re.DOTALL)
_STRUCTURED_TAGS = {"TOOL", "RESULT"}


def sse_format(event: str, data: object) -> str:
    """SSE 포맷 직렬화."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def build_structured_log_event(text: str) -> dict[str, object] | None:
    """TOOL/RESULT 로그를 안정적인 schema envelope로 보강한다."""
    match = _LOG_TAG_PATTERN.match(text)
    if not match:
        return None
    tag = match.group("tag")
    if tag not in _STRUCTURED_TAGS:
        return None

    message = match.group("message").strip()
    event: dict[str, object] = {
        "schema_version": 1,
        "kind": "tool_call" if tag == "TOOL" else "tool_result",
        "tag": tag,
        "message": message,
        "raw": text,
    }
    timestamp = match.group("time")
    if timestamp:
        event["timestamp"] = timestamp
    if tag == "TOOL" and message:
        event["name"] = re.split(r"[:\s]", message, maxsplit=1)[0]
    return event


def build_log_line_payload(data: str) -> object:
    """로그 payload 직렬화.

    하위호환: 단일 라인은 기존처럼 string.
    확장: 멀티라인 또는 structured 로그는 {text, meta, structured_event} 객체로 보낸다.
    """
    text = str(data or "")
    structured_event = build_structured_log_event(text)
    if "\n" not in text and structured_event is None:
        return text
    line_count = text.count("\n") + 1
    payload: dict[str, object] = {
        "text": text,
        "meta": {
            "multiline": "\n" in text,
            "line_count": line_count,
        },
    }
    if structured_event is not None:
        payload["structured_event"] = structured_event
    return payload
