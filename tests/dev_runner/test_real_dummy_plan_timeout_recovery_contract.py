from __future__ import annotations

import importlib.util
from pathlib import Path

import httpx


_E2E_PATH = (
    Path(__file__).resolve().parents[1]
    / "e2e"
    / "frontend"
    / "test_dev_runner_real_dummy_plan_merge_e2e.py"
)


def _load_e2e_module():
    spec = importlib.util.spec_from_file_location("real_dummy_plan_timeout_contract", _E2E_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _TimeoutClient:
    def __init__(self):
        self.calls = 0

    def get(self, *_args, **_kwargs):
        self.calls += 1
        raise httpx.ReadTimeout("simulated timeout")


def test_poll_attempt_result_treats_log_timeouts_as_poll_miss(monkeypatch):
    mod = _load_e2e_module()
    monkeypatch.setattr(mod, "_poll", lambda _timeout, _interval, fn: fn())

    result = mod._poll_attempt_result(_TimeoutClient(), "runner-timeout", attempt=1, engine="claude")

    assert result["success"] is False
    assert result["reason"] == "sentinel_timeout"
    assert result["runner_id"] == "runner-timeout"


def test_live_http_timeout_has_short_connect_budget():
    mod = _load_e2e_module()

    assert mod.HTTP_TIMEOUT.connect == 2.0
    assert mod.HTTP_TIMEOUT.read == 10.0
