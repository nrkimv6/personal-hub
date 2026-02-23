"""
헬스 모니터 서비스 테스트

테스트 항목:
- PID 파일 읽기
- 프로세스 존재 확인
- 포트 점유 확인
- HTTP 헬스체크
- 알림 발송 (모킹)
- API 엔드포인트
"""

import pytest
import asyncio
import os
from pathlib import Path
from datetime import datetime
from unittest.mock import Mock, AsyncMock, patch, MagicMock
import tempfile


class TestServiceHealth:
    """ServiceHealth 모델 테스트"""

    def test_service_health_to_dict(self):
        """ServiceHealth.to_dict() 테스트"""
        from app.services.health_monitor_service import ServiceHealth, ServiceStatus

        health = ServiceHealth(
            name="test_service",
            status=ServiceStatus.HEALTHY,
            last_check=datetime(2025, 12, 28, 14, 30, 0),
            failure_count=0,
            response_time_ms=50.5,
            error_message=None,
            pid=12345,
            expected_port=8000,
            actual_port_owner=12345
        )

        result = health.to_dict()

        assert result["name"] == "test_service"
        assert result["status"] == "healthy"
        assert result["failure_count"] == 0
        assert result["response_time_ms"] == 50.5
        assert result["pid"] == 12345
        assert result["expected_port"] == 8000

    def test_service_health_unhealthy(self):
        """비정상 상태 ServiceHealth 테스트"""
        from app.services.health_monitor_service import ServiceHealth, ServiceStatus

        health = ServiceHealth(
            name="api",
            status=ServiceStatus.UNHEALTHY,
            last_check=datetime.now(),
            failure_count=3,
            error_message="Connection timeout"
        )

        assert health.status == ServiceStatus.UNHEALTHY
        assert health.failure_count == 3
        assert health.error_message == "Connection timeout"


class TestHealthMonitorService:
    """HealthMonitorService 테스트"""

    @pytest.fixture
    def temp_pid_dir(self):
        """임시 PID 디렉토리 생성"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def health_monitor(self, temp_pid_dir):
        """HealthMonitorService 인스턴스 생성"""
        from app.services.health_monitor_service import HealthMonitorService

        with patch('app.services.health_monitor_service.settings') as mock_settings:
            mock_settings.PID_DIR = str(temp_pid_dir)
            mock_settings.APP_MODE = "public"
            mock_settings.HEALTH_CHECK_TIMEOUT = 5
            mock_settings.HEALTH_FAILURE_THRESHOLD = 3
            mock_settings.HEALTH_RECOVERY_NOTIFY = True
            mock_settings.HEALTH_PID_CHECK_INTERVAL = 10
            mock_settings.HEALTH_HTTP_CHECK_INTERVAL = 60
            mock_settings.EXTERNAL_API_URL = ""
            mock_settings.EXTERNAL_FRONTEND_URL = ""

            monitor = HealthMonitorService(notification_service=None)
            monitor.pid_dir = temp_pid_dir
            yield monitor

    def test_read_pid_file_exists(self, health_monitor, temp_pid_dir):
        """PID 파일이 존재하는 경우 테스트"""
        # PID 파일 생성
        pid_file = temp_pid_dir / "api.pid"
        pid_file.write_text("12345")

        result = health_monitor.read_pid_file("api")
        assert result == 12345

    def test_read_pid_file_not_exists(self, health_monitor, temp_pid_dir):
        """PID 파일이 없는 경우 테스트"""
        result = health_monitor.read_pid_file("api")
        assert result is None

    def test_read_pid_file_invalid(self, health_monitor, temp_pid_dir):
        """PID 파일 내용이 잘못된 경우 테스트"""
        pid_file = temp_pid_dir / "api.pid"
        pid_file.write_text("not_a_number")

        result = health_monitor.read_pid_file("api")
        assert result is None

    def test_read_pid_file_unknown_service(self, health_monitor):
        """알 수 없는 서비스명 테스트"""
        result = health_monitor.read_pid_file("unknown_service")
        assert result is None

    def test_check_process_exists_current_process(self, health_monitor):
        """현재 프로세스 존재 확인 테스트"""
        current_pid = os.getpid()
        result = health_monitor.check_process_exists(current_pid)
        assert result is True

    def test_check_process_exists_not_exists(self, health_monitor):
        """존재하지 않는 프로세스 테스트"""
        # 99999는 거의 확실히 존재하지 않는 PID
        result = health_monitor.check_process_exists(99999)
        assert result is False

    def test_check_pid_and_port_no_pid_file(self, health_monitor, temp_pid_dir):
        """PID 파일이 없을 때 체크 테스트"""
        result = health_monitor.check_pid_and_port("api")

        from app.services.health_monitor_service import ServiceStatus
        assert result.status == ServiceStatus.UNHEALTHY
        assert "PID file not found" in result.error_message

    def test_check_pid_and_port_process_not_running(self, health_monitor, temp_pid_dir):
        """프로세스가 실행 중이지 않을 때 테스트"""
        pid_file = temp_pid_dir / "api.pid"
        pid_file.write_text("99999")  # 존재하지 않는 PID

        result = health_monitor.check_pid_and_port("api")

        from app.services.health_monitor_service import ServiceStatus
        assert result.status == ServiceStatus.UNHEALTHY
        assert "not running" in result.error_message

    def test_check_pid_and_port_unknown_service(self, health_monitor):
        """알 수 없는 서비스 체크 테스트"""
        result = health_monitor.check_pid_and_port("unknown")

        from app.services.health_monitor_service import ServiceStatus
        assert result.status == ServiceStatus.UNKNOWN
        assert "Unknown service" in result.error_message

    def test_get_failure_count_empty(self, health_monitor):
        """실패 횟수 조회 - 비어있을 때"""
        result = health_monitor._get_failure_count("unknown_service")
        assert result == 0

    def test_get_failure_count_exists(self, health_monitor):
        """실패 횟수 조회 - 기존 값이 있을 때"""
        from app.services.health_monitor_service import ServiceHealth, ServiceStatus

        health_monitor.services["api"] = ServiceHealth(
            name="api",
            status=ServiceStatus.UNHEALTHY,
            last_check=datetime.now(),
            failure_count=5,
            error_message="Connection timeout"
        )

        result = health_monitor._get_failure_count("api")
        assert result == 5

    def test_get_all_services_status(self, health_monitor):
        """모든 서비스 상태 조회 테스트"""
        from app.services.health_monitor_service import ServiceHealth, ServiceStatus

        # 임의의 서비스 상태 추가
        health_monitor.services["api"] = ServiceHealth(
            name="api",
            status=ServiceStatus.HEALTHY,
            last_check=datetime.now(),
            failure_count=0
        )
        health_monitor.services["worker"] = ServiceHealth(
            name="worker",
            status=ServiceStatus.UNHEALTHY,
            last_check=datetime.now(),
            failure_count=2,
            error_message="Not responding"
        )

        result = health_monitor.get_all_services_status()

        assert "api" in result
        assert "worker" in result
        assert result["api"]["status"] == "healthy"
        assert result["worker"]["status"] == "unhealthy"

    def test_get_recent_alerts(self, health_monitor):
        """최근 알림 목록 조회 테스트"""
        from app.services.health_monitor_service import RecentAlert

        # 알림 추가
        health_monitor.recent_alerts = [
            RecentAlert(
                timestamp=datetime.now(),
                alert_type="failure",
                service="api",
                message="Connection timeout",
                check_type="HTTP"
            ),
            RecentAlert(
                timestamp=datetime.now(),
                alert_type="recovery",
                service="worker",
                message="Service recovered",
                check_type="PID"
            )
        ]

        result = health_monitor.get_recent_alerts(limit=10)

        assert len(result) == 2
        assert result[0]["service"] == "api"
        assert result[1]["service"] == "worker"

    @pytest.mark.asyncio
    async def test_send_pid_failure_alert_without_notification_service(self, health_monitor):
        """알림 서비스 없이 PID 장애 알림 테스트"""
        from app.services.health_monitor_service import ServiceHealth, ServiceStatus

        health = ServiceHealth(
            name="api",
            status=ServiceStatus.UNHEALTHY,
            last_check=datetime.now(),
            failure_count=1,
            error_message="Process not running",
            pid=12345,
            expected_port=8000
        )

        # 예외 없이 실행되어야 함
        await health_monitor._send_pid_failure_alert(health)

        # 알림이 추가되었는지 확인
        assert len(health_monitor.recent_alerts) == 1
        assert health_monitor.recent_alerts[0].service == "api"
        assert health_monitor.recent_alerts[0].alert_type == "failure"

    @pytest.mark.asyncio
    async def test_send_pid_failure_alert_with_notification_service(self, health_monitor):
        """알림 서비스와 함께 PID 장애 알림 테스트"""
        from app.services.health_monitor_service import ServiceHealth, ServiceStatus

        mock_notification = AsyncMock()
        mock_notification.send_telegram = AsyncMock()
        health_monitor.notification_service = mock_notification

        health = ServiceHealth(
            name="api",
            status=ServiceStatus.UNHEALTHY,
            last_check=datetime.now(),
            failure_count=1,
            error_message="Process not running",
            pid=12345,
            expected_port=8000
        )

        await health_monitor._send_pid_failure_alert(health)

        mock_notification.send_telegram.assert_called_once()
        call_args = mock_notification.send_telegram.call_args
        assert "프로세스 장애 감지" in call_args[0][0]


class TestHealthRoutes:
    """헬스 API 라우트 테스트"""

    @pytest.fixture
    def test_client(self):
        """테스트 클라이언트 생성"""
        from fastapi.testclient import TestClient
        from fastapi import FastAPI

        app = FastAPI()

        from app.routes.health import router
        app.include_router(router, prefix="/api/v1")

        return TestClient(app)

    def test_get_health_status_disabled(self, test_client):
        """헬스 모니터 비활성화 시 상태 조회 테스트"""
        with patch('app.core.config.settings') as mock_settings:
            mock_settings.HEALTH_MONITOR_ENABLED = False

            response = test_client.get("/api/v1/health/status")

            assert response.status_code == 200
            data = response.json()
            assert data["enabled"] is False
            assert data["services"] == {}

    def test_get_health_status_enabled_no_monitor(self, test_client):
        """헬스 모니터 활성화 but 인스턴스 없음 테스트"""
        from app.routes.health import set_health_monitor

        set_health_monitor(None)

        with patch('app.core.config.settings') as mock_settings:
            mock_settings.HEALTH_MONITOR_ENABLED = True

            response = test_client.get("/api/v1/health/status")

            assert response.status_code == 200
            data = response.json()
            assert data["enabled"] is True
            assert data["services"] == {}

    def test_get_health_status_with_data(self, test_client):
        """헬스 데이터가 있을 때 상태 조회 테스트"""
        from app.routes.health import set_health_monitor

        mock_monitor = MagicMock()
        mock_monitor.get_all_services_status.return_value = {
            "api": {
                "name": "api",
                "status": "healthy",
                "last_check": "2025-12-28T14:30:00",
                "failure_count": 0
            }
        }
        mock_monitor.get_recent_alerts.return_value = []

        set_health_monitor(mock_monitor)

        with patch('app.core.config.settings') as mock_settings:
            mock_settings.HEALTH_MONITOR_ENABLED = True

            response = test_client.get("/api/v1/health/status")

            assert response.status_code == 200
            data = response.json()
            assert data["enabled"] is True
            assert "api" in data["services"]

        # 정리
        set_health_monitor(None)

    def test_get_recent_alerts(self, test_client):
        """최근 알림 조회 테스트"""
        from app.routes.health import set_health_monitor

        mock_monitor = MagicMock()
        mock_monitor.get_recent_alerts.return_value = [
            {
                "timestamp": "2025-12-28T14:30:00",
                "type": "failure",
                "service": "api",
                "message": "Connection timeout",
                "check_type": "HTTP"
            }
        ]

        set_health_monitor(mock_monitor)

        with patch('app.core.config.settings') as mock_settings:
            mock_settings.HEALTH_MONITOR_ENABLED = True

            response = test_client.get("/api/v1/health/alerts?limit=10")

            assert response.status_code == 200
            data = response.json()
            assert len(data["alerts"]) == 1

        # 정리
        set_health_monitor(None)

    def test_trigger_health_check_disabled(self, test_client):
        """헬스 모니터 비활성화 시 수동 체크 테스트"""
        with patch('app.core.config.settings') as mock_settings:
            mock_settings.HEALTH_MONITOR_ENABLED = False

            response = test_client.post("/api/v1/health/check")

            assert response.status_code == 503

    def test_trigger_health_check_no_monitor(self, test_client):
        """헬스 모니터 인스턴스 없을 때 수동 체크 테스트"""
        from app.routes.health import set_health_monitor
        set_health_monitor(None)

        with patch('app.core.config.settings') as mock_settings:
            mock_settings.HEALTH_MONITOR_ENABLED = True

            response = test_client.post("/api/v1/health/check")

            assert response.status_code == 503


class TestRecentAlert:
    """RecentAlert 모델 테스트"""

    def test_recent_alert_to_dict(self):
        """RecentAlert.to_dict() 테스트"""
        from app.services.health_monitor_service import RecentAlert

        alert = RecentAlert(
            timestamp=datetime(2025, 12, 28, 14, 30, 0),
            alert_type="failure",
            service="api",
            message="Connection timeout",
            check_type="HTTP"
        )

        result = alert.to_dict()

        assert result["type"] == "failure"
        assert result["service"] == "api"
        assert result["message"] == "Connection timeout"
        assert result["check_type"] == "HTTP"
