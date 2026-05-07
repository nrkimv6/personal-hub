"""Executor + _parse_json_response TC (Task 25)."""
import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest


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

    @patch("subprocess.run")
    def test_gemini_executor_R_uses_direct_utf8_stdin_without_shell(self, mock_run):
        """R: Gemini는 shell pipe 대신 argv + UTF-8 stdin을 사용한다."""
        from app.modules.claude_worker.services.executors.gemini_executor import GeminiExecutor

        mock_run.return_value = MagicMock(returncode=0, stdout='{"ok": true}', stderr="")
        executor = GeminiExecutor()
        with patch("shutil.which", return_value="/usr/bin/gemini"):
            executor.execute(
                "한글 prompt",
                model="gemini-2.5-pro",
                cli_options={"image_path": "C:/tmp/image.png"},
                parse_json=False,
            )

        mock_run.assert_called_once()
        args, kwargs = mock_run.call_args
        assert args[0] == ["/usr/bin/gemini", "--model", "gemini-2.5-pro", "@C:/tmp/image.png"]
        assert kwargs["input"] == "한글 prompt"
        assert kwargs["encoding"] == "utf-8"
        assert kwargs["errors"] == "replace"
        assert kwargs["shell"] is False

    @patch("subprocess.run")
    def test_gemini_executor_R_preserves_image_path_arg(self, mock_run):
        """R: image_path는 argv 마지막 @경로 인수로 유지된다."""
        from app.modules.claude_worker.services.executors.gemini_executor import GeminiExecutor

        mock_run.return_value = MagicMock(returncode=0, stdout='{"ok": true}', stderr="")
        executor = GeminiExecutor()
        with patch("shutil.which", return_value="/usr/bin/gemini"):
            executor.execute("prompt", cli_options={"image_path": "D:/img/sample.png"}, parse_json=False)

        args, _ = mock_run.call_args
        assert args[0] == ["/usr/bin/gemini", "@D:/img/sample.png"]

    @patch("subprocess.run")
    def test_gemini_executor_R_prefers_windows_cmd_shim(self, mock_run):
        """R: Windows PATH에서는 extensionless shim 대신 gemini.cmd를 실행한다."""
        from app.modules.claude_worker.services.executors.gemini_executor import GeminiExecutor

        def fake_which(name, path=None):
            if name == "gemini.cmd":
                return "C:/Users/test/AppData/Roaming/npm/gemini.cmd"
            if name == "gemini":
                return "C:/Users/test/AppData/Roaming/npm/gemini"
            return None

        mock_run.return_value = MagicMock(returncode=0, stdout='{"ok": true}', stderr="")
        executor = GeminiExecutor()
        with patch("shutil.which", side_effect=fake_which):
            executor.execute("prompt", parse_json=False)

        args, _ = mock_run.call_args
        assert args[0][0].endswith("gemini.cmd")

    @patch("subprocess.run")
    def test_gemini_executor_E_never_uses_type_pipe(self, mock_run):
        """E: Windows shell pipe 문자열은 더 이상 생성되지 않는다."""
        from app.modules.claude_worker.services.executors.gemini_executor import GeminiExecutor

        mock_run.return_value = MagicMock(returncode=0, stdout='{"ok": true}', stderr="")
        executor = GeminiExecutor()
        executor.execute("prompt", parse_json=False)

        args, _ = mock_run.call_args
        command = args[0]
        assert isinstance(command, list)
        assert all("type " not in part for part in command)

    @patch("subprocess.run")
    def test_gemini_executor_B_parse_json_false_returns_raw_response(self, mock_run):
        """B: parse_json=False이면 raw_response를 그대로 반환한다."""
        from app.modules.claude_worker.services.executors.gemini_executor import GeminiExecutor

        mock_run.return_value = MagicMock(returncode=0, stdout="plain text", stderr="")
        executor = GeminiExecutor()
        result = executor.execute("prompt", parse_json=False)

        assert result == {"success": True, "result": None, "raw_response": "plain text"}

    @patch("subprocess.run")
    def test_gemini_executor_E_quota_failure_keeps_retry_ms(self, mock_run):
        """E: quota stderr는 quota_retry_ms를 유지한다."""
        from app.modules.claude_worker.services.executors.gemini_executor import GeminiExecutor

        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="TerminalQuotaError\nretryDelayMs: 22751416",
        )
        executor = GeminiExecutor()
        result = executor.execute("prompt")

        assert result["success"] is False
        assert result["quota_retry_ms"] == 22751416

    @patch("subprocess.run", side_effect=FileNotFoundError)
    def test_gemini_executor_E_cli_not_found_message(self, mock_run):
        """E: Gemini CLI 미설치 시 안내 메시지를 유지한다."""
        from app.modules.claude_worker.services.executors.gemini_executor import GeminiExecutor

        executor = GeminiExecutor()
        with patch("shutil.which", return_value=None):
            result = executor.execute("prompt")

        assert result["success"] is False
        assert "Gemini CLI not found" in result["error"]
        assert "Searched: gemini.cmd, gemini.exe, gemini" in result["error"]
        assert "PATH head:" in result["error"]
        assert result["error_code"] == "GEMINI_CLI_NOT_FOUND"

    @patch("subprocess.run")
    def test_gemini_executor_E_nonzero_sets_cli_error_code(self, mock_run):
        """E: 일반 Gemini CLI 실패는 auth/not-found와 구분되는 error_code를 반환한다."""
        from app.modules.claude_worker.services.executors.gemini_executor import GeminiExecutor

        mock_run.return_value = MagicMock(returncode=2, stdout="", stderr="bad arg")
        executor = GeminiExecutor()
        result = executor.execute("prompt")

        assert result["success"] is False
        assert result["error"] == "Gemini CLI error: bad arg"
        assert result["error_code"] == "GEMINI_CLI_ERROR"


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
