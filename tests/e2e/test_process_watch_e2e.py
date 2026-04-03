"""Process Watch E2E 테스트."""
import subprocess
import sys
import time

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


@pytest.mark.e2e
def test_process_watch_fingerprint_kill_mismatch_then_success():
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(120)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    target = None
    try:
        for _ in range(10):
            latest = client.get("/api/v1/system/process-watch/latest?min_mb=0&limit=500")
            assert latest.status_code == 200
            items = latest.json().get("items", [])
            target = next((item for item in items if int(item.get("pid", -1)) == proc.pid), None)
            if target:
                break
            time.sleep(1)

        if not target:
            pytest.skip("spawned python process not found in process-watch snapshot")

        mismatch_resp = client.post(
            "/api/v1/system/process-watch/kill",
            json={
                "pid": proc.pid,
                "expected_create_time": target.get("create_time"),
                "expected_cmdline_hash": "ffffffffffffffffffffffffffffffff",
                "reason": "e2e fingerprint mismatch",
                "force": True,
            },
        )
        assert mismatch_resp.status_code == 409

        success_resp = client.post(
            "/api/v1/system/process-watch/kill",
            json={
                "pid": proc.pid,
                "expected_create_time": target.get("create_time"),
                "expected_cmdline_hash": target.get("cmdline_hash"),
                "reason": "e2e force cleanup target",
                "force": True,
            },
        )
        assert success_resp.status_code == 200
        assert success_resp.json()["success"] is True
        proc.wait(timeout=10)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


@pytest.mark.e2e
def test_process_watch_latest_has_source_and_age():
    resp = client.get("/api/v1/system/process-watch/latest?min_mb=0&limit=10")
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] in ("periodic", "on_demand", "stale_cache")
    assert "snapshot_age_seconds" in data
