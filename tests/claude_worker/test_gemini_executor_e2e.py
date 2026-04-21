import os
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.modules.claude_worker.services.executors.gemini_executor import GeminiExecutor


@pytest.fixture
def fake_gemini_cli(tmp_path, monkeypatch):
    script_path = tmp_path / "gemini_fake.py"
    script_path.write_text(
        "\n".join(
            [
                "import json",
                "import os",
                "import sys",
                "",
                "mode = os.environ.get('FAKE_GEMINI_MODE', 'success')",
                "payload = sys.stdin.read()",
                "image_args = [arg for arg in sys.argv[1:] if arg.startswith('@')]",
                "model = ''",
                "for idx, arg in enumerate(sys.argv[1:]):",
                "    if arg == '--model' and idx + 2 <= len(sys.argv[1:]):",
                "        model = sys.argv[1:][idx + 1]",
                "        break",
                "",
                "if mode == 'success':",
                "    json.dump({'prompt': payload, 'model': model, 'image_args': image_args}, sys.stdout, ensure_ascii=False)",
                "elif mode == 'invalid':",
                "    sys.stdout.write('not-json-response')",
                "else:",
                "    sys.stderr.write('TerminalQuotaError: retryDelayMs: 120000')",
                "    sys.exit(1)",
            ]
        ),
        encoding="utf-8",
    )
    cmd_path = tmp_path / "gemini.cmd"
    cmd_path.write_text(
        f'@echo off\r\n"{Path(__import__("sys").executable)}" "{script_path}" %*\r\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    return tmp_path


def test_gemini_executor_e2e_R_roundtrips_utf8_json(fake_gemini_cli, monkeypatch):
    monkeypatch.setenv("FAKE_GEMINI_MODE", "success")

    with patch(
        "app.modules.claude_worker.services.executors.gemini_executor._build_gemini_command",
        return_value=[str(fake_gemini_cli / "gemini.cmd"), "--model", "gemini-2.5-pro", "@C:/images/sample.png"],
    ):
        result = GeminiExecutor().execute(
            "한글 prompt",
            model="gemini-2.5-pro",
            cli_options={"image_path": "C:/images/sample.png"},
        )

    assert result["success"] is True
    assert result["result"]["prompt"] == "한글 prompt"
    assert result["result"]["model"] == "gemini-2.5-pro"
    assert result["result"]["image_args"] == ["@C:/images/sample.png"]


def test_gemini_executor_e2e_E_invalid_output_keeps_raw_response(fake_gemini_cli, monkeypatch):
    monkeypatch.setenv("FAKE_GEMINI_MODE", "invalid")

    with patch(
        "app.modules.claude_worker.services.executors.gemini_executor._build_gemini_command",
        return_value=[str(fake_gemini_cli / "gemini.cmd")],
    ):
        result = GeminiExecutor().execute("invalid payload", parse_json=True)

    assert result["success"] is False
    assert "JSON 파싱 실패" in result["error"]
    assert result["raw_response"] == "not-json-response"


def test_gemini_executor_e2e_E_quota_nonzero_exit_preserves_retry_ms(fake_gemini_cli, monkeypatch):
    monkeypatch.setenv("FAKE_GEMINI_MODE", "quota")

    with patch(
        "app.modules.claude_worker.services.executors.gemini_executor._build_gemini_command",
        return_value=[str(fake_gemini_cli / "gemini.cmd")],
    ):
        result = GeminiExecutor().execute("quota payload", parse_json=False)

    assert result["success"] is False
    assert "Gemini CLI error" in result["error"]
    assert result["quota_retry_ms"] == 120000
