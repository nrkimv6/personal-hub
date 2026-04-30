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


def _utf8_env():
    env = os.environ.copy()
    env.setdefault("MONITOR_ADMIN_API_BASE", ADMIN_API)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def _run_module(module: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", module, *args],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
        env=_utf8_env(),
    )


def _extract_item_id(stdout: str) -> int:
    match = re.search(r"id=(\d+)", stdout)
    assert match, stdout
    return int(match.group(1))


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {os.environ['MONITOR_ADMIN_TOKEN']}"}


def _delete_item(item_id: int) -> None:
    with httpx.Client(base_url=ADMIN_API, headers=_headers(), timeout=5.0) as client:
        client.delete(f"/api/v1/tracking/items/{item_id}")


@pytest.fixture
def live_item_id():
    _require_live_ready()
    result = _run_module("app.cli.tracking_add", "--title", "[TC] update", "--wait-until", "1w")
    assert result.returncode == 0, result.stderr
    item_id = _extract_item_id(result.stdout)
    try:
        yield item_id
    finally:
        _delete_item(item_id)


def test_cli_live_R_clear_deadline_persists_null(live_item_id):
    result = _run_module(
        "app.cli.tracking_update",
        "--id",
        str(live_item_id),
        "--deadline",
        "2026-12-31",
    )
    assert result.returncode == 0, result.stderr

    result = _run_module(
        "app.cli.tracking_update",
        "--id",
        str(live_item_id),
        "--clear-deadline",
    )
    assert result.returncode == 0, result.stderr

    data = httpx.get(
        f"{ADMIN_API}/api/v1/tracking/items/{live_item_id}",
        headers=_headers(),
        timeout=5.0,
    ).json()
    assert data["due_at"] is None


def test_cli_live_R_wait_until_updates_start_at(live_item_id):
    result = _run_module(
        "app.cli.tracking_update",
        "--id",
        str(live_item_id),
        "--wait-until",
        "2026-05-13",
    )
    assert result.returncode == 0, result.stderr
    data = httpx.get(
        f"{ADMIN_API}/api/v1/tracking/items/{live_item_id}",
        headers=_headers(),
        timeout=5.0,
    ).json()
    assert data["start_at"].startswith("2026-05-13T00:00:00")


def test_cli_live_E_both_dates_null_rejected(live_item_id):
    result = _run_module(
        "app.cli.tracking_update",
        "--id",
        str(live_item_id),
        "--clear-wait-until",
        "--clear-deadline",
    )
    assert result.returncode == 5
    assert "start_at 또는 due_at 중 하나 이상이 필요합니다." in result.stderr
