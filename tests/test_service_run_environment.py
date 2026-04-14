from __future__ import annotations

from unittest.mock import MagicMock, patch

from scripts.services import service_run


def test_log_environment_includes_path_and_fingerprint_context():
    runner = object.__new__(service_run.ServiceRunner)
    runner.log = MagicMock()
    runner.app_mode = "admin"

    fingerprint = {
        "runtime_fingerprint": "runtime-1234567890abcdef",
        "source_fingerprint": "source-abcdef1234567890",
        "source_files": [{"path": "app/main.py"}],
    }

    with patch.object(service_run, "get_session_id", return_value=0), patch.object(
        service_run.os, "getcwd", return_value=str(service_run.PROJECT_ROOT)
    ), patch.object(service_run, "get_runtime_fingerprint_snapshot", return_value=fingerprint), patch.object(
        service_run.sys, "path", [str(service_run.PROJECT_ROOT)]
    ), patch.object(service_run.sys, "version", "3.12.1 (mock)"), patch("socket.getaddrinfo", return_value=[object()]):
        runner.log_environment()

    messages = [call.args[0] for call in runner.log.info.call_args_list]
    assert any(msg.startswith("Service script: ") for msg in messages)
    assert any(msg.startswith("Project root: ") for msg in messages)
    assert any(msg.startswith("sys.path[0]: ") for msg in messages)
    assert any("Runtime fingerprint: runtime-1234..." in msg for msg in messages)
