"""Live HTTP regression for already-merged dev-runner plans.

Requires:
  DEV_RUNNER_ALREADY_MERGED_PLAN=<absolute fixture plan path>
  monitor-page admin API on localhost:8001
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

import httpx
import pytest

from tests.dev_runner.live_http_readiness import ADMIN_BASE_URL, wait_until_live_api_ready

pytestmark = pytest.mark.http_live

DEV_RUNNER_BASE = f"{ADMIN_BASE_URL}/api/v1/dev-runner"
METADATA_VALUES = {True, False, "unknown"}


def _fixture_plan_path() -> Path:
    raw = os.environ.get("DEV_RUNNER_ALREADY_MERGED_PLAN")
    if not raw:
        pytest.skip("DEV_RUNNER_ALREADY_MERGED_PLAN is required for this live regression")
    path = Path(raw)
    if not path.exists():
        pytest.skip(f"already-merged fixture plan not found: {path}")
    return path


def _read_plan_status(path: Path) -> str:
    content = path.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"^>\s*상태:\s*(.+)$", content, flags=re.MULTILINE)
    return match.group(1).strip() if match else ""


def _has_unchecked_post_merge_gate(path: Path) -> bool:
    content = path.read_text(encoding="utf-8", errors="replace")
    return bool(
        re.search(
            r"^\s+(?:[-*]|\d+\.)\s+\[ \].*(?:T4|T5|post-merge|머지|통합테스트)",
            content,
            flags=re.MULTILINE | re.IGNORECASE,
        )
    )


def _wait_for_runner_settled(runner_id: str, timeout_seconds: float = 300.0) -> dict:
    deadline = time.time() + timeout_seconds
    last_payload: dict = {}
    while time.time() <= deadline:
        response = httpx.get(f"{DEV_RUNNER_BASE}/runners/{runner_id}", timeout=15)
        response.raise_for_status()
        last_payload = response.json()
        if not last_payload.get("running"):
            return last_payload
        time.sleep(3)
    pytest.fail(f"runner did not settle within {timeout_seconds}s: {runner_id}")


def test_already_merged_runner_keeps_post_merge_gate_and_metadata_contract():
    plan_path = _fixture_plan_path()
    wait_until_live_api_ready()

    response = httpx.post(
        f"{DEV_RUNNER_BASE}/run",
        json={
            "plan_file": str(plan_path),
            "engine": os.environ.get("DEV_RUNNER_ALREADY_MERGED_ENGINE", "codex"),
            "max_cycles": int(os.environ.get("DEV_RUNNER_ALREADY_MERGED_MAX_CYCLES", "1")),
            "test_source": "already_merged_post_merge_gate",
        },
        timeout=60,
    )
    response.raise_for_status()
    started = response.json()
    runner_id = started.get("runner_id")
    assert runner_id, started

    settled = _wait_for_runner_settled(runner_id)
    for field in ("worktree_exists", "branch_exists", "branch_merged_to_main"):
        assert settled.get(field) in METADATA_VALUES
    assert settled.get("metadata_checked_at") or settled.get("metadata_checked_at") == "unknown"

    logs_response = httpx.get(f"{DEV_RUNNER_BASE}/logs/recent", params={"runner_id": runner_id, "lines": 200}, timeout=15)
    logs_response.raise_for_status()
    assert isinstance(logs_response.json().get("lines"), list)

    status = _read_plan_status(plan_path)
    assert not (status == "구현완료" and _has_unchecked_post_merge_gate(plan_path)), (
        "plan reached 구현완료 while post-merge gates remained unchecked"
    )

    runners_response = httpx.get(f"{DEV_RUNNER_BASE}/runners", timeout=15)
    runners_response.raise_for_status()
    runner = next((item for item in runners_response.json() if item.get("runner_id") == runner_id), None)
    if runner is not None:
        for field in ("worktree_exists", "branch_exists", "branch_merged_to_main"):
            assert runner.get(field) in METADATA_VALUES
        assert runner.get("metadata_checked_at") or runner.get("metadata_checked_at") == "unknown"
