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
