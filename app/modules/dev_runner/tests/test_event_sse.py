"""event_sse 단위 테스트

sse_format, build_log_line_payload 순수 함수 검증.
외부 의존성 없음.
"""

import json
import pytest

from app.modules.dev_runner.services.event_sse import (
    build_log_line_payload,
    build_structured_log_event,
    classify_failure,
    normalize_artifact_path,
    sse_format,
)


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

    def test_tool_line_returns_structured_payload(self):
        payload = build_log_line_payload("[12:00:00] [TOOL] shell_command Get-ChildItem")
        assert isinstance(payload, dict)
        assert payload["text"] == "[12:00:00] [TOOL] shell_command Get-ChildItem"
        assert payload["meta"]["multiline"] is False
        assert payload["structured_event"]["schema_version"] == 1
        assert payload["structured_event"]["event_id"].startswith("log_")
        assert payload["structured_event"]["kind"] == "tool_call"
        assert payload["structured_event"]["source"] == "dev_runner_log"
        assert payload["structured_event"]["severity"] == "info"
        assert payload["structured_event"]["tag"] == "TOOL"
        assert payload["structured_event"]["name"] == "shell_command"
        assert payload["structured_event"]["args_summary"] == "Get-ChildItem"


class TestStructuredLogEvent:
    def test_result_line_returns_tool_result_event(self):
        event = build_structured_log_event("[12:00:01] [RESULT] exit=0")
        assert event is not None
        assert event["kind"] == "tool_result"
        assert event["timestamp"] == "12:00:01"
        assert event["message"] == "exit=0"
        assert event["result"]["status"] == "success"
        assert event["artifact"] is None

    def test_parse_structured_event_right_failure_classification(self):
        event = build_structured_log_event("[12:00:01] [RESULT] exit=1 timeout waiting for Redis")
        assert event is not None
        assert event["kind"] == "tool_result"
        assert event["severity"] == "error"
        assert event["result"]["status"] == "failure"
        assert event["failure"]["classification"] == "retryable"
        assert classify_failure("approval_required by merge guard") == "approval_required"

    def test_parse_structured_event_boundary_empty_output(self):
        event = build_structured_log_event("[12:00:01] [RESULT]   ")
        assert event is not None
        assert event["raw"] == "[12:00:01] [RESULT]   "
        assert event["message"] == ""
        assert event["result"]["output_schema"]["empty"] is True

    def test_parse_structured_event_boundary_no_artifact_path(self):
        event = build_structured_log_event("[12:00:01] [RESULT] exit=0")
        assert event is not None
        assert event["artifact"] is None
        assert event["artifacts"] == []

    def test_parse_structured_event_error_disallowed_artifact_path(self):
        event = build_structured_log_event("[12:00:01] [RESULT] screenshot saved root-shot.png and .tmp/codex/p1/evidence.json")
        assert event is not None
        assert len(event["artifacts"]) == 1
        assert event["artifact"]["allowed"] is True
        assert event["artifact"]["display_path"] == ".tmp/codex/p1/evidence.json"
        blocked = normalize_artifact_path("D:\\work\\project\\tools\\monitor-page\\root-shot.png")
        assert blocked is not None
        assert blocked["allowed"] is False
        assert blocked["reason"] == "disallowed_artifact_root"

    def test_structured_event_conformance_schema(self):
        event = build_structured_log_event("[12:00:01] [FAILURE] approval_required: user decision needed")
        assert event is not None
        for key in ("event_id", "kind", "source", "severity", "raw"):
            assert key in event
        assert event["schema_version"] == 1
        assert event["kind"] == "failure"
        assert event["failure"]["classification"] == "approval_required"

    def test_non_tool_line_has_no_structured_event(self):
        assert build_structured_log_event("[12:00:01] [INFO] hello") is None
