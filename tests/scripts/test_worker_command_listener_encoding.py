"""worker-command-listener text-mode subprocess encoding tests."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parent.parent.parent / "scripts" / "services" / "worker-command-listener.py"


@pytest.fixture(scope="module")
def listener():
    spec = importlib.util.spec_from_file_location("worker_command_listener_encoding", _SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_execute_worker_action_uses_utf8_replace(listener):
    """R: worker action subprocess는 cp949 기본값 대신 UTF-8 text 계약을 사용한다."""
    completed = MagicMock(returncode=0, stdout="완료", stderr="")

    with patch("subprocess.run", return_value=completed) as mock_run:
        result = listener.execute_worker_action("restart")

    assert result["success"] is True
    kwargs = mock_run.call_args.kwargs
    assert kwargs["text"] is True
    assert kwargs["encoding"] == "utf-8"
    assert kwargs["errors"] == "replace"


def test_execute_worker_action_restart_frontend_R_allows_action(listener):
    """R: restart-frontend는 Session 1 listener whitelist에서 거부되지 않는다."""
    completed = MagicMock(returncode=0, stdout="frontend restarted", stderr="")

    with patch("subprocess.run", return_value=completed) as mock_run:
        result = listener.execute_worker_action("restart-frontend")

    assert result["success"] is True
    args = mock_run.call_args.args[0]
    assert "-Action" in args
    assert args[args.index("-Action") + 1] == "restart-frontend"


def test_execute_worker_action_restart_frontend_public_Co_passes_public_switch(listener):
    """Co: public payload는 browser-workers.ps1 -Public 스위치로 전달된다."""
    completed = MagicMock(returncode=0, stdout="frontend restarted", stderr="")

    with patch("subprocess.run", return_value=completed) as mock_run:
        result = listener.execute_worker_action("restart-frontend", public=True)

    assert result["success"] is True
    args = mock_run.call_args.args[0]
    assert args[-1] == "-Public"


def test_execute_worker_action_unknown_E_returns_error(listener):
    """E: 지원하지 않는 action은 기존처럼 실패 JSON을 반환한다."""
    result = listener.execute_worker_action("unknown-action")

    assert result["success"] is False
    assert "알 수 없는 액션" in result["message"]


def test_execute_worker_action_restart_Re_preserves_existing_worker_restart(listener):
    """Re: 기존 restart argv와 PID 추출 동작은 유지된다."""
    completed = MagicMock(returncode=0, stdout="Worker started (PID: 1234)", stderr="")

    with patch("subprocess.run", return_value=completed) as mock_run:
        result = listener.execute_worker_action("restart")

    args = mock_run.call_args.args[0]
    assert result["success"] is True
    assert result["pid"] == 1234
    assert args[args.index("-Action") + 1] == "restart"
    assert "-Public" not in args


def test_execute_worker_action_restart_frontend_public_T3_executes_temp_script(listener, tmp_path, monkeypatch):
    """T3: 실제 PowerShell script 파일을 통해 restart-frontend/-Public argv를 read-back한다."""
    args_file = tmp_path / "args.txt"
    script = tmp_path / "browser-workers.ps1"
    script.write_text(
        "\n".join(
            [
                "param([string]$Action, [switch]$Public)",
                f"Set-Content -LiteralPath '{args_file}' -Value \"$Action|$($Public.IsPresent)\" -Encoding UTF8",
                "Write-Output 'ok'",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(listener, "BROWSER_WORKERS_SCRIPT", script)

    result = listener.execute_worker_action("restart-frontend", public=True)

    assert result["success"] is True
    assert args_file.read_text(encoding="utf-8-sig").strip() == "restart-frontend|True"


def test_dev_runner_subprocess_streaming_uses_utf8_replace_source_contract():
    """T3: dev-runner subprocess/log drain은 Windows cp949 decode에 의존하지 않는다."""
    plan_runner = Path(__file__).resolve().parent.parent.parent / "scripts" / "plan_runner"
    subprocess_source = (plan_runner / "_dr_subprocess.py").read_text(encoding="utf-8")
    runner_source = (plan_runner / "_dr_plan_runner.py").read_text(encoding="utf-8")

    for source in (subprocess_source, runner_source):
        assert 'encoding="utf-8"' in source
        assert 'errors="replace"' in source
