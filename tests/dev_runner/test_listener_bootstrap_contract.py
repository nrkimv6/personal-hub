"""listener bootstrap helper contract tests."""

from __future__ import annotations

import sys

import pytest

from tests.dev_runner._path_helpers import (
    bootstrap_plan_runner_modules,
    load_listener_module,
)


@pytest.fixture(autouse=True)
def cleanup_bootstrap_modules():
    aliases = [
        "dev_runner_bootstrap_right",
        "dev_runner_bootstrap_boundary",
    ]
    for name in ["_dr_state", "_dr_process_utils", *aliases]:
        sys.modules.pop(name, None)
    yield
    for name in ["_dr_state", "_dr_process_utils", *aliases]:
        sys.modules.pop(name, None)


def test_listener_bootstrap_right_registers_state_before_fixture_read():
    """R: helper가 listener load 전에 canonical state/process modules를 등록한다."""
    listener_mod = load_listener_module("dev_runner_bootstrap_right")

    assert listener_mod is sys.modules["dev_runner_bootstrap_right"]
    assert "_dr_state" in sys.modules
    assert "_dr_process_utils" in sys.modules

    state_mod, process_utils_mod = bootstrap_plan_runner_modules()

    assert state_mod is sys.modules["_dr_state"]
    assert process_utils_mod is sys.modules["_dr_process_utils"]
    assert state_mod.get_running_processes() == {}


def test_listener_bootstrap_boundary_no_exec_side_effect_dependency():
    """B: unique listener alias에서도 canonical bootstrap modules를 그대로 재사용한다."""
    state_mod, process_utils_mod = bootstrap_plan_runner_modules()
    listener_mod = load_listener_module("dev_runner_bootstrap_boundary")

    assert listener_mod is sys.modules["dev_runner_bootstrap_boundary"]
    assert sys.modules["_dr_state"] is state_mod
    assert sys.modules["_dr_process_utils"] is process_utils_mod
    assert state_mod.get_running_processes() is sys.modules["_dr_state"].get_running_processes()


def test_listener_bootstrap_error_missing_state_module_raises_import_error(monkeypatch):
    """E: _dr_state import 실패는 helper가 침묵하지 않고 그대로 surface해야 한다."""

    def _raise_on_state(name: str, package=None):
        if name == "_dr_state":
            raise ImportError("forced missing _dr_state")
        return original_import_module(name, package)

    original_import_module = __import__("importlib").import_module
    monkeypatch.setattr(
        "tests.dev_runner._path_helpers.importlib.import_module",
        _raise_on_state,
    )

    with pytest.raises(ImportError, match="forced missing _dr_state"):
        bootstrap_plan_runner_modules()
