"""
browser_workers facade contract tests.

This file keeps the public entry surface stable while the implementation
continues moving into scripts/services/browser_worker_runtime/.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
SERVICES_DIR = SCRIPTS_DIR / "services"
sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(SERVICES_DIR))

import browser_workers
from scripts.services.browser_worker_runtime import BrowserWorkerManager as RuntimeBrowserWorkerManager
from scripts.services.browser_worker_runtime import _kill_by_cmdline as runtime_kill_by_cmdline


def test_browser_workers_facade_exports_public_symbols_R():
    """R: facade re-exports the runtime manager and kill helper."""
    assert browser_workers.BrowserWorkerManager is RuntimeBrowserWorkerManager
    assert browser_workers._kill_by_cmdline is runtime_kill_by_cmdline
    assert callable(browser_workers.main)


def test_browser_workers_main_dispatches_restart_frontend_public_R(monkeypatch):
    """R: facade main() still dispatches CLI actions through the runtime parser."""
    calls: list[bool] = []

    class FakeManager:
        def start(self) -> bool:
            return True

        def stop(self) -> bool:
            return True

        def restart(self) -> bool:
            return True

        def status(self) -> bool:
            return True

        def restart_api(self) -> bool:
            return True

        def redis_status(self) -> bool:
            return True

        def redis_restart(self) -> bool:
            return True

        def redis_cleanup(self) -> bool:
            return True

        def restart_listener(self) -> bool:
            return True

        def restart_infra(self, target: str) -> bool:
            return True

        def restart_frontend(self, public: bool = False) -> bool:
            calls.append(public)
            return True

    monkeypatch.setattr(browser_workers, "BrowserWorkerManager", FakeManager)
    monkeypatch.setattr(sys, "argv", ["browser_workers.py", "restart-frontend", "--public"])

    with pytest.raises(SystemExit) as exc:
        browser_workers.main()

    assert exc.value.code == 0
    assert calls == [True]


def test_browser_workers_ps1_wrapper_still_targets_python_entrypoint_R():
    """R: PowerShell wrapper still calls the Python facade entrypoint."""
    wrapper_path = SCRIPTS_DIR / "services" / "browser-workers.ps1"
    text = wrapper_path.read_text(encoding="utf-8")

    assert "browser_workers.py" in text
    assert "python.exe" in text
    assert "restart-frontend" in text
    assert "ValidateSet" in text
