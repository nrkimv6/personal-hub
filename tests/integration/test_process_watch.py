"""Process Watch integration tests."""
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.shared.process.snapshot_writer import SnapshotWriter

client = TestClient(app)


@pytest.mark.integration
def test_process_watch_fingerprint_kill_mismatch_then_success():
    pid = 54321
    create_time = 1712100000.0
    cmdline_parts = [
        "python",
        "D:/work/project/tools/monitor-page/app/main.py",
        "--port",
        "8001",
    ]
    cmdline = " ".join(cmdline_parts)
    cmdline_hash = SnapshotWriter._cmdline_hash(cmdline)
    stale_iso = (datetime.now() - timedelta(minutes=15)).isoformat()
    fresh_iso = datetime.now().isoformat()

    snapshot_row = {
        "captured_at": fresh_iso,
        "pid": pid,
        "ppid": 1000,
        "parent_pid": 10,
        "parent_name": "cmd.exe",
        "name": "python.exe",
        "exe": r"D:\Python312\python.exe",
        "cmdline": cmdline,
        "cmdline_hash": cmdline_hash,
        "create_time": create_time,
        "memory_mb": 128.0,
        "is_orphan": False,
        "scope": "monitor_page",
        "captured_by": "on_demand",
    }

    mock_writer = MagicMock()
    mock_writer.get_latest_python_snapshots.side_effect = [
        (stale_iso, []),
        (fresh_iso, [snapshot_row]),
    ]
    mock_writer.capture_python_processes = AsyncMock(return_value=1)

    mock_proc = MagicMock()
    mock_proc.name.return_value = "python.exe"
    mock_proc.exe.return_value = r"D:\Python312\python.exe"
    mock_proc.cmdline.return_value = cmdline_parts
    mock_proc.create_time.return_value = create_time

    with patch("app.routes.system._process_watch_writer", return_value=mock_writer), \
         patch("app.routes.system._enrich_process_watch_items", side_effect=lambda items: items), \
         patch("app.routes.system._protected_pids", return_value=set()), \
         patch("app.routes.system._last_process_watch_on_demand_at", 0.0), \
         patch("app.routes.system.psutil.Process", return_value=mock_proc), \
         patch("scripts.services.service_utils.kill_pid", return_value=True) as mock_kill:
        latest = client.get("/api/v1/system/process-watch/latest?min_mb=0&limit=500")
        assert latest.status_code == 200
        latest_data = latest.json()
        assert latest_data["source"] == "on_demand"
        assert latest_data["item_count"] == 1
        target = latest_data["items"][0]
        assert target["pid"] == pid
        assert target["cmdline_hash"] == cmdline_hash
        assert target["is_orphan"] is False
        mock_writer.capture_python_processes.assert_awaited_once()

        mismatch_resp = client.post(
            "/api/v1/system/process-watch/kill",
            json={
                "pid": pid,
                "expected_create_time": target.get("create_time"),
                "expected_cmdline_hash": "ffffffffffffffffffffffffffffffff",
                "reason": "e2e fingerprint mismatch",
                "force": True,
            },
        )
        assert mismatch_resp.status_code == 409
        assert mismatch_resp.json()["detail"]["code"] == "fingerprint_mismatch"

        success_resp = client.post(
            "/api/v1/system/process-watch/kill",
            json={
                "pid": pid,
                "expected_create_time": target.get("create_time"),
                "expected_cmdline_hash": target.get("cmdline_hash"),
                "reason": "e2e force cleanup target",
                "force": True,
            },
        )
        assert success_resp.status_code == 200
        assert success_resp.json()["success"] is True
        assert success_resp.json()["cmdline_hash"] == cmdline_hash
        mock_kill.assert_called_once_with(pid, timeout=5)


@pytest.mark.integration
def test_process_watch_latest_has_source_and_age():
    resp = client.get("/api/v1/system/process-watch/latest?min_mb=0&limit=10")
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] in ("periodic", "on_demand", "stale_cache")
    assert "snapshot_age_seconds" in data
    if data.get("items"):
        assert isinstance(data["items"][0]["is_orphan"], bool)
