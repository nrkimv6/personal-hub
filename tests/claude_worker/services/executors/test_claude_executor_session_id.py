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

    @patch("subprocess.run")
    def test_execute_exec_mode_uses_stdin_utf8_R(self, mock_run):
        """R: exec mode도 shell pipe 없이 UTF-8 stdin 파일로 전달한다."""
        from app.modules.claude_worker.services.executors.claude_executor import ClaudeExecutor

        raw = json.dumps({"type": "result", "session_id": "stdin-id", "result": "ok"})
        mock_run.return_value = MagicMock(returncode=0, stdout=raw, stderr="")

        executor = ClaudeExecutor()
        result = executor.execute(
            "한글 프롬프트",
            parse_json=False,
            cli_options={"exec_mode": True},
        )

        assert result["success"] is True
        args, kwargs = mock_run.call_args
        assert isinstance(args[0], list)
        assert args[0][0] == "claude"
        assert kwargs["stdin"].encoding.lower() == "utf-8"
        assert kwargs["shell"] is False

    @patch("subprocess.run")
    def test_execute_single_mode_uses_schema_file_arg_R(self, mock_run):
        """R: single mode json_schema는 @schema_file argv로 전달한다."""
        from app.modules.claude_worker.services.executors.claude_executor import ClaudeExecutor

        raw = json.dumps({"type": "result", "session_id": "schema-id", "result": "ok"})
        mock_run.return_value = MagicMock(returncode=0, stdout=raw, stderr="")

        executor = ClaudeExecutor()
        executor.execute(
            "prompt",
            parse_json=False,
            cli_options={"json_schema": {"type": "object"}},
        )

        command = mock_run.call_args.args[0]
        schema_index = command.index("--json-schema")
        assert command[schema_index + 1].startswith("@")

    @patch("subprocess.run")
    def test_execute_never_builds_type_pipe_E(self, mock_run):
        """E: Windows shell type/cat pipe 문자열을 더 이상 만들지 않는다."""
        from app.modules.claude_worker.services.executors.claude_executor import ClaudeExecutor

        raw = json.dumps({"type": "result", "session_id": "pipe-id", "result": "ok"})
        mock_run.return_value = MagicMock(returncode=0, stdout=raw, stderr="")

        executor = ClaudeExecutor()
        executor.execute("prompt", parse_json=False)

        command = mock_run.call_args.args[0]
        assert isinstance(command, list)
        assert 'type "' not in " ".join(command)
        assert "cat " not in " ".join(command)

    @patch("subprocess.run")
    def test_execute_sets_errors_replace_B(self, mock_run):
        """B: stdout decode 에러는 errors=replace로 완충한다."""
        from app.modules.claude_worker.services.executors.claude_executor import ClaudeExecutor

        raw = json.dumps({"type": "result", "session_id": "replace-id", "result": "ok"})
        mock_run.return_value = MagicMock(returncode=0, stdout=raw, stderr="")

        executor = ClaudeExecutor()
        executor.execute("prompt", parse_json=False)

        assert mock_run.call_args.kwargs["errors"] == "replace"
