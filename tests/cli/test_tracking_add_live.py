import os
import re
import subprocess
import sys

import httpx
import pytest


pytestmark = pytest.mark.http_live

ADMIN_API = os.environ.get("MONITOR_ADMIN_API_BASE", "http://localhost:8001")


def _require_live_ready():
    if not os.environ.get("MONITOR_ADMIN_TOKEN"):
        pytest.skip("MONITOR_ADMIN_TOKEN is not set")
    try:
        response = httpx.get(f"{ADMIN_API}/api/v1/system/liveness", timeout=3.0)
    except (httpx.ConnectError, httpx.ConnectTimeout):
        pytest.skip("Admin API is not reachable")
    if response.status_code >= 500:
        pytest.skip(f"Admin API liveness returned {response.status_code}")


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.setdefault("MONITOR_ADMIN_API_BASE", ADMIN_API)
    return subprocess.run(
        [sys.executable, "-m", "app.cli.tracking_add", *args],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def _extract_item_id(stdout: str) -> int:
    match = re.search(r"id=(\d+)", stdout)
    assert match, stdout
    return int(match.group(1))


def _delete_item(item_id: int) -> None:
    headers = {"Authorization": f"Bearer {os.environ['MONITOR_ADMIN_TOKEN']}"}
    with httpx.Client(base_url=ADMIN_API, headers=headers, timeout=5.0) as client:
        client.delete(f"/api/v1/tracking/items/{item_id}")


def test_cli_live_R_wait_until_2w_fills_start_at():
    _require_live_ready()
    result = _run_cli("--title", "live wait-until cli test", "--wait-until", "2w")
    assert result.returncode == 0, result.stderr
    item_id = _extract_item_id(result.stdout)
    try:
        headers = {"Authorization": f"Bearer {os.environ['MONITOR_ADMIN_TOKEN']}"}
        data = httpx.get(
            f"{ADMIN_API}/api/v1/tracking/items/{item_id}",
            headers=headers,
            timeout=5.0,
        ).json()
        assert data["start_at"] is not None
        assert data["due_at"] is None
    finally:
        _delete_item(item_id)


def test_cli_live_R_deadline_fills_due_at():
    _require_live_ready()
    result = _run_cli("--title", "live deadline cli test", "--deadline", "2099-12-31")
    assert result.returncode == 0, result.stderr
    item_id = _extract_item_id(result.stdout)
    try:
        headers = {"Authorization": f"Bearer {os.environ['MONITOR_ADMIN_TOKEN']}"}
        data = httpx.get(
            f"{ADMIN_API}/api/v1/tracking/items/{item_id}",
            headers=headers,
            timeout=5.0,
        ).json()
        assert data["start_at"] is None
        assert data["due_at"] is not None
    finally:
        _delete_item(item_id)


def test_cli_live_R_link_plan_resolves():
    _require_live_ready()
    plan_path = ".worktrees/plans/docs/plan/2026-04-29_feat-tracking-item-cli-wrapper.md"
    result = _run_cli(
        "--title",
        "live link-plan cli test",
        "--deadline",
        "2099-12-31",
        "--link-plan",
        plan_path,
    )
    assert result.returncode == 0, result.stderr
    item_id = _extract_item_id(result.stdout)
    try:
        headers = {"Authorization": f"Bearer {os.environ['MONITOR_ADMIN_TOKEN']}"}
        data = httpx.get(
            f"{ADMIN_API}/api/v1/tracking/items/{item_id}",
            headers=headers,
            timeout=5.0,
        ).json()
        assert any(plan["file_path"] == plan_path for plan in data["linked_plans"])
    finally:
        _delete_item(item_id)
