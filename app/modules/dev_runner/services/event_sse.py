"""event_sse — SSE 직렬화 순수 함수

C 도메인: sse_format, build_log_line_payload
상태 없음. 외부 의존성 없음. 입출력 검증만으로 테스트 가능.
"""
import json


def sse_format(event: str, data: object) -> str:
    """SSE 포맷 직렬화."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def build_log_line_payload(data: str) -> object:
    """로그 payload 직렬화.

    하위호환: 단일 라인은 기존처럼 string.
    확장: 멀티라인은 {text, meta} 객체로 보내 UI가 줄바꿈 보존/보조메타를 활용할 수 있게 한다.
    """
    text = str(data or "")
    if "\n" not in text:
        return text
    line_count = text.count("\n") + 1
    return {
        "text": text,
        "meta": {
            "multiline": True,
            "line_count": line_count,
        },
    }
