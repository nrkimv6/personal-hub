"""Executor + _parse_json_response TC (Task 25)."""
import json
import subprocess
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def parser():
    """LLMExecutorBase concrete subclass for _parse_json_response."""
    from app.modules.claude_worker.services.executors.base import LLMExecutorBase

    class _Concrete(LLMExecutorBase):
        def execute(self, prompt, **kwargs):
            return {}

    return _Concrete()


class TestClaudeExecutor:
    @patch("subprocess.run")
    def test_claude_executor_R_success(self, mock_run):
        """R: subprocess mock 정상 응답 → success dict."""
        from app.modules.claude_worker.services.executors.claude_executor import ClaudeExecutor

        payload = {"key": "value"}
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps(payload),
            stderr="",
        )
        executor = ClaudeExecutor()
        with patch("shutil.which", return_value="/usr/bin/claude"):
            result = executor.execute("test prompt", parse_json=True)

        assert result["success"] is True

    @patch("subprocess.run", side_effect=subprocess.TimeoutExpired("claude", 30))
    def test_claude_executor_E_timeout(self, mock_run):
        """E: TimeoutExpired → success=False."""
        from app.modules.claude_worker.services.executors.claude_executor import ClaudeExecutor
        executor = ClaudeExecutor()
        with patch("shutil.which", return_value="/usr/bin/claude"):
            result = executor.execute("prompt", timeout=30)
        assert result["success"] is False
        assert "timeout" in result.get("error", "").lower() or "error" in result

    @patch("subprocess.run")
    def test_claude_executor_E_nonzero_exit(self, mock_run):
        """E: returncode≠0 → error dict."""
        from app.modules.claude_worker.services.executors.claude_executor import ClaudeExecutor
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="some error")
        executor = ClaudeExecutor()
        with patch("shutil.which", return_value="/usr/bin/claude"):
            result = executor.execute("prompt")
        assert result["success"] is False

    @patch("subprocess.run")
    def test_gemini_executor_R_success(self, mock_run):
        """R: Gemini subprocess mock 정상 응답."""
        from app.modules.claude_worker.services.executors.gemini_executor import GeminiExecutor
        mock_run.return_value = MagicMock(returncode=0, stdout='{"ok": true}', stderr="")
        executor = GeminiExecutor()
        with patch("shutil.which", return_value="/usr/bin/gemini"):
            result = executor.execute("prompt", parse_json=True)
        assert result["success"] is True

    @patch("subprocess.run")
    def test_gemini_executor_E_failure(self, mock_run):
        """E: Gemini returncode≠0."""
        from app.modules.claude_worker.services.executors.gemini_executor import GeminiExecutor
        mock_run.return_value = MagicMock(returncode=2, stdout="", stderr="fail")
        executor = GeminiExecutor()
        with patch("shutil.which", return_value="/usr/bin/gemini"):
            result = executor.execute("prompt")
        assert result["success"] is False


class TestParseJsonResponse:
    def test_parse_json_response_R_markdown_block(self, parser):
        """R: ```json {...}``` → parsed dict."""
        text = '```json\n{"a": 1}\n```'
        result = parser._parse_json_response(text)
        assert result == {"a": 1}

    def test_parse_json_response_R_pure_json(self, parser):
        """R: 순수 JSON 문자열 → parsed dict."""
        result = parser._parse_json_response('{"x": 42}')
        assert result == {"x": 42}

    def test_parse_json_response_B_empty_string(self, parser):
        """B: 빈 문자열 → 예외."""
        with pytest.raises(Exception):
            parser._parse_json_response("")

    def test_parse_json_response_E_invalid_json(self, parser):
        """E: 파싱 불가 텍스트 → 예외."""
        with pytest.raises(Exception):
            parser._parse_json_response("this is not json at all")
