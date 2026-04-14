from __future__ import annotations

from unittest.mock import MagicMock, patch

from scripts.services import service_run


def test_service_runner_run_sets_expected_environment_and_logs_boot():
    logger = MagicMock()
    with patch.object(service_run, "setup_service_logger", return_value=logger), patch.object(
        service_run, "atexit"
    ) as mock_atexit, patch.object(service_run.signal, "signal", return_value=None), patch.object(
        service_run, "sys"
    ) as mock_sys:
        mock_sys.exit = MagicMock()
        runner = service_run.ServiceRunner(dev=True)
        runner.cleanup_before_start = MagicMock()
        runner.start_frontend = MagicMock(return_value=None)

        def _fake_run_api():
            service_run.os.environ["API_PORT"] = "8001"
            service_run.os.environ["WORKER_AUTO_START"] = "false"

        runner.run_api = MagicMock(side_effect=_fake_run_api)
        runner.cleanup = MagicMock()
        runner.run()

    assert service_run.os.environ["PYTHONIOENCODING"] == "utf-8"
    assert service_run.os.environ["APP_MODE"] == "admin"
    assert service_run.os.environ["API_PORT"] == "8001"
    assert service_run.os.environ["WORKER_AUTO_START"] == "false"
    mock_sys.exit.assert_called_once_with(0)
    mock_atexit.register.assert_called()
    messages = [str(call.args[0]) for call in logger.info.call_args_list if call.args]
    assert any("Monitor Page Service Starting" in msg for msg in messages)
    assert any("Mode: admin" in msg for msg in messages)
