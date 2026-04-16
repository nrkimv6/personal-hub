from __future__ import annotations

from unittest.mock import MagicMock, patch

from scripts.services import service_run


def test_bootstrap_service_environment_sets_mode_and_encoding():
    env: dict[str, str] = {}

    resolved_admin = service_run.bootstrap_service_environment(["--admin"], env)
    assert resolved_admin == "admin"
    assert env["APP_MODE"] == "admin"
    assert env["PYTHONIOENCODING"] == "utf-8"

    resolved_public = service_run.bootstrap_service_environment([], env)
    assert resolved_public == "public"
    assert env["APP_MODE"] == "public"


def test_log_mode_alignment_detects_stale_settings():
    logger = MagicMock()
    with patch.dict(service_run.os.environ, {"APP_MODE": "admin"}, clear=False), patch.object(
        service_run,
        "get_runtime_fingerprint_snapshot",
        return_value={"app_mode": "admin"},
    ):
        aligned = service_run._log_mode_alignment(logger, "public")

    assert aligned is False
    logger.info.assert_called_once_with("Mode alignment: env=%s | settings=%s | runtime=%s", "admin", "public", "admin")
    logger.warning.assert_called_once_with(
        "Mode alignment drift detected: env=%s | settings=%s | runtime=%s",
        "admin",
        "public",
        "admin",
    )


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
