"""
T5 HTTP 통합 테스트: GET /api/v1/worker/status
mappings().first() 전환 후 이름 기반 접근이 API 응답에 올바르게 반영되는지 검증.

검증 포인트:
- started_at 필드 존재 (worker.py 고유 키 — system.py의 start_time과 구분)
- pid/status 인덱스 오염 없음 (regression)
- DB 없을 때 not_started 기본값 200 반환
"""
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


def _db_status(
    pid=None,
    status="not_started",
    started_at=None,
    active_tasks=0,
    uptime_seconds=0,
    active_tabs=0,
    browser_contexts=0,
    global_pause=False,
    paused_at=None,
    error_message=None,
):
    return {
        "pid": pid,
        "status": status,
        "started_at": started_at,
        "last_heartbeat": None,
        "active_tasks": active_tasks,
        "memory_usage_mb": None,
        "uptime_seconds": uptime_seconds,
        "active_tabs": active_tabs,
        "browser_contexts": browser_contexts,
        "global_pause": global_pause,
        "paused_at": paused_at,
        "error_message": error_message,
    }


class TestWorkerRouteStatusHttp:
    """GET /api/v1/worker/status — started_at 필드 이름 기반 접근 회귀 방지"""

    def test_worker_status_running_returns_started_at_R_http(self, client):
        """R: worker 실행 중일 때 started_at 필드 존재 + pid/status 정확."""
        db_val = _db_status(
            pid=5678,
            status="running",
            started_at="2026-04-22T09:00:00",
            active_tasks=3,
            uptime_seconds=1800,
            active_tabs=2,
            browser_contexts=1,
        )

        with patch("app.routes.worker.get_worker_status_from_db", return_value=db_val), \
             patch("app.routes.worker.is_process_running", return_value=True), \
             patch("app.routes.worker.get_process_memory", return_value=128.5), \
             patch("app.routes.worker.calculate_uptime", return_value=1800):
            resp = client.get("/api/v1/worker/status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["pid"] == 5678, f"pid 오염: {data['pid']}"
        assert data["status"] == "running", f"status 오염: {data['status']}"
        assert "started_at" in data, "started_at 필드 누락"
        assert data["started_at"] == "2026-04-22T09:00:00"
        assert data["active_tasks"] == 3

    def test_worker_status_not_started_returns_200_B_http(self, client):
        """B: not_started 시 200 + pid=None, status='not_started', started_at=None."""
        db_val = _db_status(pid=None, status="not_started")

        with patch("app.routes.worker.get_worker_status_from_db", return_value=db_val), \
             patch("app.routes.worker.is_process_running", return_value=False):
            resp = client.get("/api/v1/worker/status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["pid"] is None
        assert data["status"] == "not_started"
        assert data["started_at"] is None

    def test_worker_status_pid_not_contaminated_by_status_Re_http(self, client):
        """Re: pid=9999, status='paused' — 인덱스 오염 없이 각 필드 독립 반환."""
        db_val = _db_status(
            pid=9999,
            status="paused",
            started_at="2026-04-22T07:00:00",
            uptime_seconds=7200,
            global_pause=True,
            paused_at="2026-04-22T08:30:00",
        )

        with patch("app.routes.worker.get_worker_status_from_db", return_value=db_val), \
             patch("app.routes.worker.is_process_running", return_value=True), \
             patch("app.routes.worker.get_process_memory", return_value=64.0), \
             patch("app.routes.worker.calculate_uptime", return_value=7200):
            resp = client.get("/api/v1/worker/status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["pid"] == 9999, f"pid가 오염됨: {data['pid']}"
        assert data["status"] == "paused", f"status가 오염됨: {data['status']}"
        assert data["global_pause"] is True
        assert data["paused_at"] == "2026-04-22T08:30:00"
