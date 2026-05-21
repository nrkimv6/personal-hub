from __future__ import annotations

import os
import time
from pathlib import Path

import httpx
import pytest

from tests.dev_runner.conftest_e2e import copy_fixture_plan_to_tmp
from tests.dev_runner.dummy_plan_lifecycle_helpers import DUMMY_PLAN_FIXTURE, DUMMY_PLAN_SENTINEL


pytestmark = pytest.mark.http_live

BASE_API = os.environ.get("E2E_API_URL", "http://localhost:8001")
TERMINAL_MERGE_STATES = {"merged", "approval_required", "test_failed", "residue_blocked", "error", "conflict"}


def _poll_until(timeout_seconds: float, interval_seconds: float, fn):
    deadline = time.monotonic() + timeout_seconds
    last_value = None
    while time.monotonic() < deadline:
        last_value = fn()
        if last_value:
            return last_value
        time.sleep(interval_seconds)
    return last_value


def _best_effort_cleanup(client: httpx.Client, runner_id: str) -> None:
    for method, path in (
        ("POST", f"/api/v1/dev-runner/runners/{runner_id}/stop"),
        ("DELETE", f"/api/v1/dev-runner/runners/{runner_id}/worktree"),
        ("DELETE", f"/api/v1/dev-runner/runners/{runner_id}/tab"),
    ):
        try:
            client.request(method, path, timeout=10.0)
        except Exception:
            pass


def test_live_dummy_plan_run_to_log_and_terminal_merge_result(tmp_path):
    plan_file = copy_fixture_plan_to_tmp(Path(tmp_path), DUMMY_PLAN_FIXTURE)
    runner_id = None
    with httpx.Client(base_url=BASE_API, timeout=30.0) as client:
        try:
            response = client.post(
                "/api/v1/dev-runner/run",
                json={
                    "plan_file": str(plan_file),
                    "test_source": "dummy_plan_playwright_live",
                    "engine": "codex",
                    "fix_engine": "codex",
                },
            )
            response.raise_for_status()
            accepted = response.json()
            runner_id = accepted["runner_id"]
            assert accepted["plan_file"] == str(plan_file)

            def read_sentinel():
                recent = client.get("/api/v1/dev-runner/logs/recent", params={"runner_id": runner_id, "lines": 200})
                if recent.status_code == 200 and any(DUMMY_PLAN_SENTINEL in line for line in recent.json().get("lines", [])):
                    return {"source": "recent", "body": recent.json()}
                full = client.get("/api/v1/dev-runner/logs/full", params={"runner_id": runner_id, "offset": 0, "limit": 500})
                if full.status_code == 200 and any(DUMMY_PLAN_SENTINEL in line for line in full.json().get("lines", [])):
                    return {"source": "full", "body": full.json()}
                return None

            sentinel = _poll_until(180.0, 3.0, read_sentinel)
            assert sentinel, f"{DUMMY_PLAN_SENTINEL} not found for runner_id={runner_id}"

            def read_terminal_merge():
                merge = client.get(f"/api/v1/dev-runner/merge/{runner_id}")
                if merge.status_code == 200:
                    body = merge.json()
                    if body.get("status") in TERMINAL_MERGE_STATES:
                        return body
                runners = client.get("/api/v1/dev-runner/runners")
                if runners.status_code == 200:
                    for item in runners.json():
                        if item.get("runner_id") == runner_id and item.get("merge_status") in TERMINAL_MERGE_STATES:
                            return item
                return None

            terminal = _poll_until(240.0, 5.0, read_terminal_merge)
            assert terminal, f"terminal merge result not found for runner_id={runner_id}"
            assert terminal.get("status") in TERMINAL_MERGE_STATES or terminal.get("merge_status") in TERMINAL_MERGE_STATES
        finally:
            if runner_id:
                _best_effort_cleanup(client, runner_id)
