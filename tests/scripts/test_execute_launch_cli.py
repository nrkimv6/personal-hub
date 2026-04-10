"""execute_launch_cli 함수 단위 테스트.

scripts/worker-command-listener.py의 execute_launch_cli() 함수가
올바른 env를 조립하여 subprocess.Popen을 호출하는지 검증한다.
"""
import importlib
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# worker-command-listener.py는 스크립트이므로 importlib로 로드
_SCRIPT_PATH = Path(__file__).parent.parent.parent / "scripts" / "worker-command-listener.py"


@pytest.fixture(scope="module")
def listener():
    """worker-command-listener 모듈 동적 로드."""
    spec = importlib.util.spec_from_file_location("worker_command_listener", _SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── RIGHT ────────────────────────────────────────────────────────────────────

def test_execute_launch_cli_right_env_injection(listener):
    """R(정상): env_key + config_dir → Popen env에 해당 키=값 포함."""
    payload = {
        "env_key": "CLAUDE_CONFIG_DIR",
        "config_dir": "C:/tmp/.claude-work",
        "extra_env": {},
        "engine_cmd": "claude",
        "engine": "claude",
        "name": "work",
    }
    with patch("subprocess.Popen") as mock_popen:
        mock_popen.return_value = MagicMock()
        result = listener.execute_launch_cli(payload)

    assert result["success"] is True
    call_kwargs = mock_popen.call_args
    env_arg = call_kwargs[1]["env"] if call_kwargs[1] else call_kwargs.kwargs.get("env")
    assert env_arg is not None
    assert env_arg.get("CLAUDE_CONFIG_DIR") == "C:/tmp/.claude-work"


def test_execute_launch_cli_right_extra_env_merge(listener):
    """R(정상): extra_env 항목이 Popen env에 병합된다."""
    payload = {
        "env_key": "CLAUDE_CONFIG_DIR",
        "config_dir": "C:/tmp/.claude-work",
        "extra_env": {"MY_KEY": "myval"},
        "engine_cmd": "claude",
        "engine": "claude",
        "name": "work",
    }
    with patch("subprocess.Popen") as mock_popen:
        mock_popen.return_value = MagicMock()
        listener.execute_launch_cli(payload)

    env_arg = mock_popen.call_args[1]["env"]
    assert env_arg.get("MY_KEY") == "myval"


def test_execute_launch_cli_right_cmd_args(listener):
    """R(정상): engine_cmd=claude → Popen(['cmd', '/k', 'claude'], creationflags=CREATE_NEW_CONSOLE)."""
    payload = {
        "env_key": None,
        "config_dir": None,
        "extra_env": {},
        "engine_cmd": "claude",
        "engine": "claude",
        "name": "default",
    }
    with patch("subprocess.Popen") as mock_popen:
        mock_popen.return_value = MagicMock()
        listener.execute_launch_cli(payload)

    call_args = mock_popen.call_args
    cmd = call_args[0][0]
    assert cmd == ["cmd", "/k", "claude"]
    assert call_args[1].get("creationflags") == subprocess.CREATE_NEW_CONSOLE


# ── BOUNDARY ─────────────────────────────────────────────────────────────────

def test_execute_launch_cli_boundary_null_config_dir(listener):
    """B(경계): config_dir=None, env_key 있음 → env에서 해당 키 제거."""
    import os
    base_env = os.environ.copy()
    base_env["CLAUDE_CONFIG_DIR"] = "old_value"

    payload = {
        "env_key": "CLAUDE_CONFIG_DIR",
        "config_dir": None,
        "extra_env": {},
        "engine_cmd": "claude",
        "engine": "claude",
        "name": "default",
    }
    with patch("subprocess.Popen") as mock_popen, \
         patch("os.environ", base_env):
        mock_popen.return_value = MagicMock()
        listener.execute_launch_cli(payload)

    env_arg = mock_popen.call_args[1]["env"]
    assert "CLAUDE_CONFIG_DIR" not in env_arg


def test_execute_launch_cli_boundary_null_env_key(listener):
    """B(경계): env_key=None (gemini) → config_dir 있어도 env 주입 스킵."""
    payload = {
        "env_key": None,
        "config_dir": "C:/some/path",
        "extra_env": {},
        "engine_cmd": "gemini",
        "engine": "gemini",
        "name": "default",
    }
    with patch("subprocess.Popen") as mock_popen:
        mock_popen.return_value = MagicMock()
        listener.execute_launch_cli(payload)

    env_arg = mock_popen.call_args[1]["env"]
    # config_dir 값이 env 어딘가에 들어가선 안 된다
    assert "C:/some/path" not in env_arg.values()


def test_execute_launch_cli_boundary_empty_extra_env(listener):
    """B(경계): extra_env={} → 기존 env 변경 없음 (예외 미발생)."""
    import os
    payload = {
        "env_key": None,
        "config_dir": None,
        "extra_env": {},
        "engine_cmd": "claude",
        "engine": "claude",
        "name": "default",
    }
    with patch("subprocess.Popen") as mock_popen:
        mock_popen.return_value = MagicMock()
        result = listener.execute_launch_cli(payload)

    assert result["success"] is True


# ── ERROR ─────────────────────────────────────────────────────────────────────

def test_execute_launch_cli_error_popen_failure(listener):
    """E(에러): subprocess.Popen 예외 → success=False, message 포함 반환."""
    payload = {
        "env_key": None,
        "config_dir": None,
        "extra_env": {},
        "engine_cmd": "claude",
        "engine": "claude",
        "name": "default",
    }
    with patch("subprocess.Popen", side_effect=OSError("no such file")):
        result = listener.execute_launch_cli(payload)

    assert result["success"] is False
    assert "message" in result
    assert "no such file" in result["message"]
