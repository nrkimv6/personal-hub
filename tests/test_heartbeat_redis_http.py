"""
Heartbeat Redis 전환 HTTP 통합 테스트

Phase T5 TC:
  test_worker_health_endpoint_http: GET /worker/health → Redis 기반 is_healthy 확인
  test_worker_health_endpoint_redis_down_http: Redis 불가 → 500 아님, PID 기반 판정
  test_worker_browser_status_heartbeat_http: GET /worker/browser-status 정상 응답
  test_instagram_worker_health_http: GET /instagram/worker/health → heartbeat_age_seconds
  test_instagram_llm_worker_status_http: GET /instagram/llm-classification/worker/status → Redis 기반 필드
"""
import os
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

os.environ["TESTING"] = "1"

from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


# ============================================================
# T5-1: GET /worker/health
# ============================================================

class TestWorkerHealthEndpoint:
    """GET /worker/health — Redis TTL 기반 판정 검증"""

    def test_worker_health_endpoint_http(self, client):
        """R(Right): GET /worker/health → 필수 필드 존재 + 500 아님."""
        with patch("app.routes.worker.get_worker_status_from_db") as mock_status, \
             patch("app.routes.worker.is_process_running", return_value=False):
            mock_status.return_value = {
                "pid": None,
                "status": "stopped",
                "started_at": None,
                "last_heartbeat": None,
                "active_tasks": 0,
                "memory_usage_mb": None,
                "uptime_seconds": None,
                "active_tabs": 0,
                "browser_contexts": 0,
                "error_message": None,
                "global_pause": False,
                "paused_at": None,
            }
            response = client.get("/api/v1/worker/health")

        assert response.status_code == 200
        data = response.json()
        assert "is_running" in data
        assert "is_healthy" in data
        assert "details" in data

    def test_worker_health_endpoint_redis_down_http(self, client):
        """E(Error): Redis 불가(None 반환) → 500 에러 없이 is_running 반환."""
        # WorkerHealthRedis.check()는 Redis 불가 시 None을 반환 (내부에서 예외 처리)
        with patch("app.routes.worker.get_worker_status_from_db") as mock_status, \
             patch("app.routes.worker.is_process_running", return_value=True), \
             patch("app.routes.worker.WorkerHealthRedis.check", return_value=None):
            mock_status.return_value = {
                "pid": 12345,
                "status": "running",
                "started_at": None,
                "last_heartbeat": None,
                "active_tasks": 0,
                "memory_usage_mb": None,
                "uptime_seconds": None,
                "active_tabs": 0,
                "browser_contexts": 0,
                "error_message": None,
                "global_pause": False,
                "paused_at": None,
            }
            response = client.get("/api/v1/worker/health")

        # Redis 없어도 500이 아닌 정상 응답
        assert response.status_code == 200
        data = response.json()
        assert "is_running" in data
        assert data["is_running"] is True
        # Redis 없으면 is_healthy=False
        assert data["is_healthy"] is False

    def test_worker_health_endpoint_redis_healthy_http(self, client):
        """R(Right): Redis TTL > 15 → is_healthy=True."""
        redis_data = {"source": "redis", "ttl_remaining": 25, "updated_at": "2026-04-10T00:00:00"}
        with patch("app.routes.worker.get_worker_status_from_db") as mock_status, \
             patch("app.routes.worker.is_process_running", return_value=True), \
             patch("app.routes.worker.get_process_memory", return_value=100.0), \
             patch("app.routes.worker.WorkerHealthRedis.check", return_value=redis_data):
            mock_status.return_value = {
                "pid": 12345,
                "status": "running",
                "started_at": "2026-04-10T00:00:00",
                "last_heartbeat": "2026-04-10T00:00:00",
                "active_tasks": 2,
                "memory_usage_mb": 100.0,
                "uptime_seconds": 3600,
                "active_tabs": 1,
                "browser_contexts": 1,
                "error_message": None,
                "global_pause": False,
                "paused_at": None,
            }
            response = client.get("/api/v1/worker/health")

        assert response.status_code == 200
        data = response.json()
        assert data["is_running"] is True
        assert data["is_healthy"] is True
        assert "seconds_since_heartbeat" in data["details"]
        assert data["details"]["seconds_since_heartbeat"] == 5  # 30 - 25 = 5


# ============================================================
# T5-2: GET /worker/browser-status
# ============================================================

class TestWorkerBrowserStatusEndpoint:
    """GET /worker/browser-status — 정상 응답 확인"""

    def test_worker_browser_status_heartbeat_http(self, client):
        """R(Right): GET /worker/browser-status → 200 + 응답 구조 확인.

        새 구현: Redis heartbeat + PID liveness 기반 available 판정.
        """
        redis_data = {"source": "redis", "ttl_remaining": 25, "updated_at": "2026-04-10T10:00:00"}
        with patch("app.routes.worker.get_worker_status_from_db") as mock_status, \
             patch("app.routes.worker.WorkerHealthRedis.check", return_value=redis_data), \
             patch("app.routes.worker.is_process_running", return_value=True):
            mock_status.return_value = {
                "pid": 12345,
                "status": "running",
                "started_at": "2026-04-10T00:00:00",
                "last_heartbeat": "2026-04-10T10:00:00",
                "active_tasks": 1,
                "memory_usage_mb": 80.0,
                "uptime_seconds": 36000,
                "active_tabs": 2,
                "browser_contexts": 1,
                "error_message": None,
                "global_pause": False,
                "paused_at": None,
            }
            response = client.get("/api/v1/worker/browser-status")

        assert response.status_code == 200
        data = response.json()
        assert data["available"] is True
        assert data["last_heartbeat"] == "2026-04-10T10:00:00"


    def test_worker_browser_status_redis_available_R(self, client):
        """R(Right): Redis heartbeat 존재 + PID 살아 있음 → available=True, last_heartbeat 값 존재."""
        redis_data = {"source": "redis", "ttl_remaining": 25, "updated_at": "2026-04-11T12:00:00"}
        with patch("app.routes.worker.WorkerHealthRedis.check", return_value=redis_data), \
             patch("app.routes.worker.is_process_running", return_value=True), \
             patch("app.routes.worker.get_worker_status_from_db") as mock_status:
            mock_status.return_value = {
                "pid": 9999,
                "status": "running",
                "started_at": None,
                "last_heartbeat": "2026-04-11T12:00:00",
                "active_tasks": 0,
                "memory_usage_mb": None,
                "uptime_seconds": None,
                "active_tabs": 0,
                "browser_contexts": 0,
                "error_message": None,
                "global_pause": False,
                "paused_at": None,
            }
            response = client.get("/api/v1/worker/browser-status")

        assert response.status_code == 200
        data = response.json()
        assert data["available"] is True
        assert data["last_heartbeat"] == "2026-04-11T12:00:00"

    def test_worker_browser_status_redis_down_E(self, client):
        """E(Error): Redis heartbeat 없음 → available=False, last_heartbeat=None, 200 응답."""
        with patch("app.routes.worker.WorkerHealthRedis.check", return_value=None), \
             patch("app.routes.worker.get_worker_status_from_db") as mock_status:
            mock_status.return_value = {
                "pid": None,
                "status": "not_started",
                "started_at": None,
                "last_heartbeat": None,
                "active_tasks": 0,
                "memory_usage_mb": None,
                "uptime_seconds": None,
                "active_tabs": 0,
                "browser_contexts": 0,
                "error_message": None,
                "global_pause": False,
                "paused_at": None,
            }
            response = client.get("/api/v1/worker/browser-status")

        assert response.status_code == 200
        data = response.json()
        assert data["available"] is False
        assert data["last_heartbeat"] is None


# ============================================================
# T5-3: GET /instagram/worker/health
# ============================================================

class TestInstagramWorkerHealthEndpoint:
    """GET /instagram/worker/health — heartbeat_age_seconds Redis TTL 기반"""

    def test_instagram_worker_health_http(self, client):
        """R(Right): GET /instagram/worker/health → 200 + status 필드."""
        response = client.get("/api/v1/instagram/worker/health")
        # 워커가 없어도 200 (no_worker 상태)
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert data["status"] in ["healthy", "warning", "dead", "no_worker", "unhealthy"]


# ============================================================
# T5-4: GET /instagram/llm-classification/worker/status
# ============================================================

class TestInstagramLLMWorkerStatusEndpoint:
    """GET /instagram/llm-classification/worker/status — Redis 기반 필드"""

    def test_instagram_llm_worker_status_http(self, client):
        """R(Right): GET /instagram/llm/worker/status → 활성 워커 없으면 404 또는 200."""
        response = client.get("/api/v1/instagram/llm/worker/status")
        # 워커가 없으면 404, 있으면 200
        assert response.status_code in [200, 404]
        if response.status_code == 200:
            data = response.json()
            assert "heartbeat_age_seconds" in data

    def test_instagram_llm_worker_health_http(self, client):
        """R(Right): GET /instagram/llm/worker/health → status 필드 존재."""
        response = client.get("/api/v1/instagram/llm/worker/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert data["status"] in ["healthy", "warning", "unhealthy", "no_worker", "dead"]
