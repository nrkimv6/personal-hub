from __future__ import annotations

import sys
import types
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.services import service_run


class _FakeServer:
    def __init__(self, config):
        self.config = config
        self.should_exit = False
        self.exit_code = 0
        self.ran = False

    def run(self):
        self.ran = True


def test_run_api_boot_wires_uvicorn_server_and_sets_shared_handle(tmp_path: Path):
    runner = object.__new__(service_run.ServiceRunner)
    runner.dev = True
    runner.api_port = 8001
    runner.frontend_port = 6101
    runner.app_mode = "admin"
    runner.pid_suffix = "_admin"
    runner.pid_dir = tmp_path / ".pids"
    runner.pid_dir.mkdir(parents=True, exist_ok=True)
    runner.log = MagicMock()

    fake_settings = types.SimpleNamespace(APP_MODE="admin")
    fake_app = object()
    fake_uvicorn = types.SimpleNamespace()
    fake_server_holder = {}

    class FakeConfig:
        def __init__(self, app, **kwargs):
            self.app = app
            self.kwargs = kwargs

    def fake_server_factory(config):
        server = _FakeServer(config)
        fake_server_holder["server"] = server
        return server

    fake_uvicorn.Config = FakeConfig
    fake_uvicorn.Server = fake_server_factory

    fake_config_mod = types.ModuleType("app.config")
    fake_config_mod.settings = fake_settings
    fake_main_mod = types.ModuleType("app.main")
    fake_main_mod.app = fake_app
    fake_server_state_mod = types.ModuleType("app.core.server_state")
    recorded_server = {}

    def fake_set_server(server):
        recorded_server["server"] = server

    fake_server_state_mod.set_server = fake_set_server

    runner.check_crash_loop = MagicMock(return_value=False)

    with patch.object(
        service_run, "get_runtime_fingerprint_snapshot", return_value={
            "runtime_fingerprint": "runtime-1234567890abcdef",
            "source_fingerprint": "source-abcdef1234567890",
            "source_files": [{"path": "app/main.py"}],
        }
    ), patch.object(service_run, "is_port_listening", return_value=True), patch.object(
        service_run, "write_pid_file"
    ), patch.dict(sys.modules, {"uvicorn": fake_uvicorn, "app": types.ModuleType("app"), "app.config": fake_config_mod, "app.main": fake_main_mod, "app.core": types.ModuleType("app.core"), "app.core.server_state": fake_server_state_mod}, clear=False), patch.object(
        threading, "Thread"
    ) as mock_thread:
        mock_thread.return_value.start = MagicMock()
        runner.run_api()

    assert "server" in fake_server_holder
    assert fake_server_holder["server"].ran is True
    assert recorded_server["server"] is fake_server_holder["server"]
    assert fake_server_holder["server"].config.kwargs["port"] == 8001
