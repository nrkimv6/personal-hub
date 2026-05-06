"""Live E2E smoke for process-watch endpoints on localhost:8001."""

from __future__ import annotations

import httpx
import pytest


pytestmark = pytest.mark.e2e

BASE_URL = "http://localhost:8001"


def _get(path: str, *, timeout: float = 10.0) -> httpx.Response:
    try:
        return httpx.get(f"{BASE_URL}{path}", timeout=timeout)
    except httpx.ConnectError:
        pytest.skip("live API(localhost:8001) 미기동 — skip")


def test_process_watch_live_latest_and_history_smoke():
    latest = _get("/api/v1/system/process-watch/latest?min_mb=0&limit=5", timeout=30.0)
    assert latest.status_code == 200
    latest_data = latest.json()
    assert "items" in latest_data
    assert "source" in latest_data
    assert "item_count" in latest_data
    assert isinstance(latest_data["items"], list)

    history = _get("/api/v1/system/process-watch/history?limit=5", timeout=30.0)
    assert history.status_code == 200
    history_data = history.json()
    assert "total" in history_data
    assert "items" in history_data
    assert isinstance(history_data["items"], list)


def test_process_watch_live_kill_guard_rejects_mismatched_hash():
    latest = _get("/api/v1/system/process-watch/latest?min_mb=0&limit=1", timeout=30.0)
    assert latest.status_code == 200
    latest_all = _get("/api/v1/system/process-watch/latest?min_mb=0&limit=10", timeout=30.0)
    assert latest_all.status_code == 200
    items = latest_all.json().get("items") or []
    target = next(
        (
            item
            for item in items
            if item.get("cmdline_hash")
            and item.get("cmdline")
            and item.get("scope") != "monitor_page"
        ),
        None,
    )
    if target is None:
        pytest.skip("fingerprint 검증 가능한 live target 없음 — skip")

    expected_create_time = target.get("create_time")
    if expected_create_time is None:
        pytest.skip("create_time 없는 live target — fingerprint guard skip")

    resp = httpx.post(
        f"{BASE_URL}/api/v1/system/process-watch/kill",
        json={
            "pid": target["pid"],
            "expected_create_time": expected_create_time,
            "expected_cmdline_hash": "ffffffffffffffffffffffffffffffff",
            "reason": "merge-test live fingerprint mismatch guard",
            "force": True,
        },
        timeout=30.0,
    )
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["code"] == "fingerprint_mismatch"
