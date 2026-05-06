"""CodexExecutor subprocess contract tests."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

from app.modules.claude_worker.services.executors.codex_executor import CodexExecutor


def _output_path_from_command(command: list[str]) -> str:
    return command[command.index("--output-last-message") + 1]


@patch("app.modules.claude_worker.services.executors.codex_executor.build_cli_env", return_value={})
@patch("shutil.which", return_value="C:/Users/Narang/AppData/Roaming/npm/codex.cmd")
@patch("subprocess.run")
def test_codex_executor_builds_read_only_exec_argv(mock_run, _mock_which, _mock_env):
    """R: codex exec is called with stdin prompt, read-only sandbox, and no shell."""
    mock_run.return_value = MagicMock(returncode=0, stdout='{"ok": true}', stderr="")

    result = CodexExecutor().execute("prompt", model="gpt-5.2")

    assert result["success"] is True
    args, kwargs = mock_run.call_args
    command = args[0]
    assert command[0].endswith("codex.cmd")
    assert command[1] == "exec"
    assert command[command.index("--model") + 1] == "gpt-5.2"
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert "--output-last-message" in command
    assert "--cd" in command
    assert command[-1] == "-"
    assert kwargs["input"] == "prompt"
    assert kwargs["shell"] is False
    assert kwargs["encoding"] == "utf-8"


@patch("app.modules.claude_worker.services.executors.codex_executor.build_cli_env", return_value={})
@patch("shutil.which", return_value="codex")
@patch("subprocess.run")
def test_codex_executor_prefers_output_last_message_file(mock_run, _mock_which, _mock_env):
    """R: last-message file wins over stdout warnings."""
    def _run(command, **_kwargs):
        output_path = _output_path_from_command(command)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write('{"from_file": true}')
        return MagicMock(returncode=0, stdout="warning on stdout", stderr="")

    mock_run.side_effect = _run

    result = CodexExecutor().execute("prompt")

    assert result["success"] is True
    assert result["raw_response"] == '{"from_file": true}'
    assert result["result"] == {"from_file": True}


@patch("app.modules.claude_worker.services.executors.codex_executor.build_cli_env", return_value={})
@patch("shutil.which", return_value="codex")
@patch("subprocess.run")
def test_codex_executor_uses_safe_default_model(mock_run, _mock_which, _mock_env):
    """B: blank model uses the CLI-compatible safe default."""
    mock_run.return_value = MagicMock(returncode=0, stdout='{"ok": true}', stderr="")

    result = CodexExecutor().execute("prompt", model="")

    args, _kwargs = mock_run.call_args
    command = args[0]
    assert command[command.index("--model") + 1] == "gpt-5.5"
    assert result["model"] == "gpt-5.5"


@patch("app.modules.claude_worker.services.executors.codex_executor.build_cli_env", return_value={})
@patch("shutil.which", return_value="codex")
@patch("subprocess.run")
def test_codex_executor_allows_parse_json_cli_metadata(mock_run, _mock_which, _mock_env):
    """B: worker-owned parse_json metadata is allowed but never emitted as argv."""
    mock_run.return_value = MagicMock(returncode=0, stdout='{"ok": true}', stderr="")

    result = CodexExecutor().execute("prompt", cli_options={"parse_json": True})

    args, _kwargs = mock_run.call_args
    command = args[0]
    assert result["success"] is True
    assert "parse_json" not in command


@patch("app.modules.claude_worker.services.executors.codex_executor.build_cli_env", return_value={})
@patch("shutil.which", return_value="codex")
@patch("subprocess.run", side_effect=subprocess.TimeoutExpired("codex", 1))
def test_codex_executor_timeout_is_classified(_mock_run, _mock_which, _mock_env):
    """E: timeout returns CODEX_TIMEOUT."""
    result = CodexExecutor().execute("prompt", timeout=1)

    assert result["success"] is False
    assert result["error"] == "CODEX_TIMEOUT"
    assert "CODEX_TIMEOUT" in result["warnings"]


@patch("app.modules.claude_worker.services.executors.codex_executor.build_cli_env", return_value={})
@patch("shutil.which", return_value="codex")
@patch("subprocess.run")
def test_codex_executor_model_incompatible_is_classified(mock_run, _mock_which, _mock_env):
    """E: Codex CLI version mismatch returns dedicated warning."""
    mock_run.return_value = MagicMock(
        returncode=1,
        stdout="",
        stderr="400: model requires a newer version of Codex",
    )

    result = CodexExecutor().execute("prompt", model="gpt-5.5")

    assert result["success"] is False
    assert result["error"] == "CODEX_CLI_MODEL_INCOMPATIBLE"
    assert "CODEX_CLI_MODEL_INCOMPATIBLE" in result["warnings"]


@patch("shutil.which", return_value="codex")
def test_codex_executor_rejects_dangerous_cli_option(_mock_which):
    """E: unsafe sandbox bypass options are rejected before subprocess."""
    with patch("subprocess.run") as mock_run:
        result = CodexExecutor().execute(
            "prompt",
            cli_options={"sandbox": "workspace-write"},
        )

    assert result["success"] is False
    assert "CODEX_UNSAFE_CLI_OPTION" in result["error"]
    mock_run.assert_not_called()


@patch("shutil.which", return_value="codex")
def test_codex_executor_rejects_unknown_cli_option(_mock_which):
    """E: raw flag injection cannot pass through cli_options."""
    with patch("subprocess.run") as mock_run:
        result = CodexExecutor().execute(
            "prompt",
            cli_options={"--dangerously-bypass-approvals-and-sandbox": True},
        )

    assert result["success"] is False
    assert "CODEX_UNSUPPORTED_CLI_OPTION" in result["error"]
    mock_run.assert_not_called()
