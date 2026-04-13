"""ClaudeExecutor session_id 파싱 TC (Phase T1)."""

import json
import pytest
from unittest.mock import MagicMock, patch


class TestExtractSessionId:
    def test_extract_session_id_from_json_output(self):
        """R: JSON에 session_id 있으면 추출."""
        from app.modules.claude_worker.services.executors.claude_executor import _extract_session_id

        raw = json.dumps({"type": "result", "session_id": "abc-123", "result": "ok"})
        assert _extract_session_id(raw) == "abc-123"

    def test_extract_session_id_missing(self):
        """B: session_id 키 없으면 None."""
        from app.modules.claude_worker.services.executors.claude_executor import _extract_session_id

        raw = json.dumps({"type": "result", "result": "ok"})
        assert _extract_session_id(raw) is None

    def test_extract_session_id_invalid_json(self):
        """E: JSON 파싱 실패 → None (예외 미발생)."""
        from app.modules.claude_worker.services.executors.claude_executor import _extract_session_id

        assert _extract_session_id("not-valid-json") is None
        assert _extract_session_id("") is None
        assert _extract_session_id("{broken") is None

    def test_extract_session_id_null_value(self):
        """B: session_id 값이 null이면 None 반환."""
        from app.modules.claude_worker.services.executors.claude_executor import _extract_session_id

        raw = json.dumps({"session_id": None})
        assert _extract_session_id(raw) is None


class TestExecuteReturnsSessionId:
    @patch("subprocess.run")
    def test_execute_returns_claude_session_id_field(self, mock_run):
        """R: execute() 결과 dict에 claude_session_id 키 포함."""
        from app.modules.claude_worker.services.executors.claude_executor import ClaudeExecutor

        session_uuid = "2af53fdc-182f-47a1-8424-b2e1e897f19e"
        raw = json.dumps({
            "type": "result",
            "session_id": session_uuid,
            "result": "hello",
        })
        mock_run.return_value = MagicMock(returncode=0, stdout=raw, stderr="")

        executor = ClaudeExecutor()
        with patch("shutil.which", return_value="/usr/bin/claude"):
            result = executor.execute("test prompt", parse_json=False)

        assert result["success"] is True
        assert result.get("claude_session_id") == session_uuid

    @patch("subprocess.run")
    def test_execute_output_format_json_forced(self, mock_run):
        """R: cli_options에 output_format 없으면 json 강제 주입."""
        from app.modules.claude_worker.services.executors.claude_executor import ClaudeExecutor

        raw = json.dumps({"type": "result", "session_id": "test-id", "result": "ok"})
        mock_run.return_value = MagicMock(returncode=0, stdout=raw, stderr="")

        executor = ClaudeExecutor()
        with patch("shutil.which", return_value="/usr/bin/claude"):
            result = executor.execute("prompt", cli_options={})

        # --output-format json이 강제 주입됐으므로 session_id 추출 가능
        assert result["success"] is True

    @patch("subprocess.run")
    def test_execute_failure_no_session_id(self, mock_run):
        """E: subprocess 실패 시 claude_session_id 없음."""
        from app.modules.claude_worker.services.executors.claude_executor import ClaudeExecutor

        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")

        executor = ClaudeExecutor()
        with patch("shutil.which", return_value="/usr/bin/claude"):
            result = executor.execute("prompt")

        assert result["success"] is False
        assert "claude_session_id" not in result
