"""death_log.build_boot_history() 및 /system/boot-history 계약 테스트."""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


def _make_entry(
    event: str,
    minutes_ago: float,
    pid: int = 12345,
    cause: str | None = None,
    details: str | None = None,
    last_request: str | None = None,
    exit_code: int | None = None,
) -> dict:
    return {
        "timestamp": (datetime.now() - timedelta(minutes=minutes_ago)).isoformat(timespec="seconds"),
        "pid": pid,
        "event": event,
        "cause": cause,
        "exit_code": exit_code,
        "uptime_seconds": 42 if event == "death" else 0,
        "details": details,
        "last_request": last_request,
    }


def _write_log(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _run_build(entries: list[dict], limit: int = 50) -> list[dict]:
    from app.core import death_log as dl

    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = Path(tmpdir) / "logs" / "death_log.json"
        _write_log(log_path, entries)
        with patch.object(dl, "_LOG_PATH", log_path):
            return dl.build_boot_history(limit=limit)


@pytest.fixture
def client():
    from app.main import app

    return TestClient(app)


class TestBuildBootHistory:
    """세션 단위 부팅 이력 집계 검증."""

    def test_build_boot_history_pairs_start_and_death(self):
        """start/death는 하나의 세션으로 묶이고 종료 원인이 유지된다."""
        entries = [
            _make_entry("start", 5.0, pid=11111),
            _make_entry("death", 4.0, pid=11111, cause="normal_shutdown", details="graceful exit", last_request="/api/v1/system/self-restart"),
        ]

        items = _run_build(entries)

        assert len(items) == 1
        item = items[0]
        assert item["end_cause"] == "normal_shutdown"
        assert item["status"] == "stopped"
        assert item["needs_attention"] is True
        assert item["current"] is False
        assert item["restarted"] is False

    def test_build_boot_history_marks_unrestarted_session(self):
        """마지막 종료 세션은 다음 start가 없으면 주의 필요로 표시된다."""
        entries = [
            _make_entry("start", 8.0, pid=22222),
            _make_entry("death", 7.0, pid=22222, cause="signal", details="SIGTERM"),
        ]

        items = _run_build(entries)

        assert len(items) == 1
        assert items[0]["status"] == "stopped"
        assert items[0]["needs_attention"] is True
        assert items[0]["end_cause"] == "signal"

    def test_build_boot_history_infers_unclean_previous_stop(self):
        """다음 start가 왔는데 이전 death가 없으면 system_reboot로 추정한다."""
        entries = [
            _make_entry("start", 12.0, pid=33333),
            _make_entry("start", 2.0, pid=44444),
        ]

        items = _run_build(entries)

        assert len(items) == 2
        inferred = next(item for item in items if item["status"] == "restarted")
        current = next(item for item in items if item["status"] == "running")

        assert inferred["end_cause"] == "system_reboot"
        assert inferred["inferred_end"] is True
        assert inferred["restarted"] is True
        assert inferred["needs_attention"] is False
        assert current["current"] is True
        assert current["needs_attention"] is False

    def test_build_boot_history_file_backed_start_then_start(self):
        """실제 파일 기반 로그에서도 start -> start는 재부팅 추정으로 묶인다."""
        entries = [
            _make_entry("start", 15.0, pid=55555),
            _make_entry("start", 1.0, pid=66666),
        ]

        items = _run_build(entries)

        assert len(items) == 2
        old_session = items[1]
        new_session = items[0]

        assert old_session["end_cause"] == "system_reboot"
        assert old_session["inferred_end"] is True
        assert old_session["status"] == "restarted"
        assert new_session["status"] == "running"


class TestBootHistoryRoute:
    """/system/boot-history HTTP 계약 검증."""

    def test_get_boot_history_returns_expected_shape(self, client):
        from app.core import death_log as dl
        from datetime import datetime

        entries = [
            _make_entry("start", 5.0, pid=77777),
            _make_entry("death", 4.0, pid=77777, cause="normal_shutdown"),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "logs" / "death_log.json"
            _write_log(log_path, entries)
            with patch.object(dl, "_LOG_PATH", log_path), \
                 patch("app.routes.system.psutil.boot_time", return_value=1704067200.0):
                resp = client.get("/api/v1/system/boot-history?limit=10")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["system_boot_at"] == datetime.fromtimestamp(1704067200.0).isoformat(timespec="seconds")
        assert isinstance(data["items"], list)
        assert data["items"][0]["status"] in {"running", "restarted", "stopped"}
        assert "started_at" in data["items"][0]
