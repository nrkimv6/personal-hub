from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.services import service_run


def _info_lines(log: MagicMock) -> list[str]:
    return [str(call.args[0]) for call in log.info.call_args_list if call.args]


def test_service_runner_log_environment_reports_boot_paths():
    logger = MagicMock()
    fingerprint = {
        "runtime_fingerprint": "runtime-fp-1234567890",
        "source_fingerprint": "source-fp-1234567890",
        "source_files": [{"path": "app/main.py", "present": True}],
    }

    with patch.object(service_run, "setup_service_logger", return_value=logger), patch.object(
        service_run, "get_session_id", return_value=7
    ), patch.object(service_run, "get_runtime_fingerprint_snapshot", return_value=fingerprint), patch(
        "socket.getaddrinfo", return_value=[("localhost", None, None, None, None)]
    ):
        runner = service_run.ServiceRunner(dev=True)
        runner.log_environment()

    lines = _info_lines(logger)
    assert any("Script:" in line and str(Path(service_run.__file__).resolve()) in line for line in lines)
    assert any("PROJECT_ROOT:" in line and str(service_run.PROJECT_ROOT) in line for line in lines)
    assert any("sys.path[0]:" in line and str(service_run.PROJECT_ROOT) in line for line in lines)
    assert any("Runtime fingerprint:" in line and "source=" in line and "files=1" in line for line in lines)
    assert any("CWD:" in line for line in lines)
