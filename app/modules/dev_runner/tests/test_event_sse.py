"""event_sse 단위 테스트

sse_format, build_log_line_payload 순수 함수 검증.
외부 의존성 없음.
"""

import json
import pytest

from app.modules.dev_runner.services.event_sse import sse_format, build_log_line_payload


class TestSseFormat:
    def test_sse_format(self):
        result = sse_format("status", {"running": True})
        assert result.startswith("event: status\n")
        assert "data: " in result
        assert result.endswith("\n\n")

    def test_sse_data_is_valid_json(self):
        payload = {"runners": [{"runner_id": "abc", "status": "running"}]}
        result = sse_format("status", payload)
        data_line = [l for l in result.splitlines() if l.startswith("data: ")][0]
        parsed = json.loads(data_line[6:])
        assert parsed["runners"][0]["runner_id"] == "abc"

    def test_sse_format_event_name_preserved(self):
        result = sse_format("log", {"runner_id": "r01", "line": "hello"})
        assert "event: log\n" in result

    def test_sse_format_unicode(self):
        result = sse_format("tracking", {"text": "[ ] 한글 태스크"})
        assert "한글" in result


class TestBuildLogLinePayload:
    def test_single_line_returns_string(self):
        payload = build_log_line_payload("hello")
        assert payload == "hello"

    def test_multiline_returns_object(self):
        payload = build_log_line_payload("a\nb\nc")
        assert isinstance(payload, dict)
        assert payload["text"] == "a\nb\nc"
        assert payload["meta"]["multiline"] is True
        assert payload["meta"]["line_count"] == 3

    def test_single_line_no_newline(self):
        payload = build_log_line_payload("[12:00:00] step complete")
        assert payload == "[12:00:00] step complete"

    def test_multiline_line_count_correct(self):
        payload = build_log_line_payload("a\nb\nc\nd\ne")
        assert isinstance(payload, dict)
        assert payload["meta"]["line_count"] == 5
