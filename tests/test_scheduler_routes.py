"""
스케줄러 API 라우트 테스트
"""
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from datetime import datetime

from app.main import app


client = TestClient(app)


class TestSchedulerTasksAPI:
    """작업 목록 API 테스트"""

    @patch("app.routes.scheduler.scheduler_service")
    def test_get_tasks_success(self, mock_service):
        """작업 목록 조회 성공"""
        mock_service.get_tasks.return_value = [
            {
                "name": "InstagramWatchdog",
                "folder": "MonitorPage",
                "status": "Ready",
                "last_run_time": None,
                "last_result": None,
                "next_run_time": None,
                "schedule": "MINUTE",
                "enabled": True,
            }
        ]

        response = client.get("/api/v1/scheduler/tasks")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["tasks"]) == 1
        assert data["tasks"][0]["name"] == "InstagramWatchdog"

    @patch("app.routes.scheduler.scheduler_service")
    def test_get_tasks_empty(self, mock_service):
        """작업이 없으면 빈 목록 반환"""
        mock_service.get_tasks.return_value = []

        response = client.get("/api/v1/scheduler/tasks")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["tasks"] == []

    @patch("app.routes.scheduler.scheduler_service")
    def test_get_tasks_platform_error(self, mock_service):
        """비-Windows에서 501 반환"""
        mock_service.get_tasks.side_effect = RuntimeError("Windows only")

        response = client.get("/api/v1/scheduler/tasks")

        assert response.status_code == 501
        assert "Windows" in response.json()["detail"]


class TestSchedulerTaskDetailAPI:
    """작업 상세 조회 API 테스트"""

    @patch("app.routes.scheduler.scheduler_service")
    def test_get_task_success(self, mock_service):
        """특정 작업 조회 성공"""
        mock_service.get_task.return_value = {
            "name": "InstagramWatchdog",
            "folder": "MonitorPage",
            "status": "Running",
            "last_run_time": "2025-12-21T14:00:00",
            "last_result": 0,
            "next_run_time": "2025-12-21T14:05:00",
            "schedule": "MINUTE",
            "enabled": True,
        }

        response = client.get("/api/v1/scheduler/tasks/InstagramWatchdog")

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "InstagramWatchdog"
        assert data["status"] == "Running"

    @patch("app.routes.scheduler.scheduler_service")
    def test_get_task_not_found(self, mock_service):
        """작업이 없으면 404 반환"""
        mock_service.get_task.return_value = None

        response = client.get("/api/v1/scheduler/tasks/InstagramWatchdog")

        assert response.status_code == 404

    @patch("app.routes.scheduler.scheduler_service")
    def test_get_task_invalid_name(self, mock_service):
        """허용되지 않은 작업명은 400 반환"""
        mock_service.get_task.side_effect = ValueError("허용되지 않은 작업명")

        response = client.get("/api/v1/scheduler/tasks/InvalidTask")

        assert response.status_code == 400
        assert "허용되지 않은" in response.json()["detail"]


class TestSchedulerRunTaskAPI:
    """작업 실행 API 테스트"""

    @patch("app.routes.scheduler.scheduler_service")
    def test_run_task_success(self, mock_service):
        """작업 즉시 실행 성공"""
        mock_service.run_task.return_value = True

        response = client.post("/api/v1/scheduler/tasks/InstagramWatchdog/run")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "started"
        assert data["task_name"] == "InstagramWatchdog"

    @patch("app.routes.scheduler.scheduler_service")
    def test_run_task_failure(self, mock_service):
        """작업 실행 실패 시 500 반환"""
        mock_service.run_task.return_value = False

        response = client.post("/api/v1/scheduler/tasks/InstagramWatchdog/run")

        assert response.status_code == 500

    @patch("app.routes.scheduler.scheduler_service")
    def test_run_task_invalid_name(self, mock_service):
        """허용되지 않은 작업명은 400 반환"""
        mock_service.run_task.side_effect = ValueError("허용되지 않은 작업명")

        response = client.post("/api/v1/scheduler/tasks/InvalidTask/run")

        assert response.status_code == 400


class TestSchedulerUpdateTaskAPI:
    """작업 상태 변경 API 테스트"""

    @patch("app.routes.scheduler.scheduler_service")
    def test_enable_task_success(self, mock_service):
        """작업 활성화 성공"""
        mock_service.enable_task.return_value = True

        response = client.patch(
            "/api/v1/scheduler/tasks/InstagramWatchdog",
            json={"enabled": True},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "updated"
        assert data["enabled"] is True

    @patch("app.routes.scheduler.scheduler_service")
    def test_disable_task_success(self, mock_service):
        """작업 비활성화 성공"""
        mock_service.disable_task.return_value = True

        response = client.patch(
            "/api/v1/scheduler/tasks/DailyMaintenance",
            json={"enabled": False},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "updated"
        assert data["enabled"] is False

    @patch("app.routes.scheduler.scheduler_service")
    def test_update_task_failure(self, mock_service):
        """작업 상태 변경 실패 시 500 반환"""
        mock_service.enable_task.return_value = False

        response = client.patch(
            "/api/v1/scheduler/tasks/WeeklyVacuum",
            json={"enabled": True},
        )

        assert response.status_code == 500


class TestSchedulerLogsAPI:
    """작업 로그 API 테스트"""

    def test_get_logs_empty(self):
        """로그가 없으면 빈 목록 반환"""
        response = client.get("/api/v1/scheduler/logs")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["logs"] == []

    def test_get_logs_invalid_task_name(self):
        """허용되지 않은 작업명으로 필터링 시 400 반환"""
        response = client.get("/api/v1/scheduler/logs?task_name=InvalidTask")

        assert response.status_code == 400

    def test_get_logs_by_name_invalid(self):
        """허용되지 않은 작업명으로 조회 시 400 반환"""
        response = client.get("/api/v1/scheduler/logs/InvalidTask")

        assert response.status_code == 400

    def test_get_logs_limit_validation(self):
        """limit 파라미터 검증"""
        # 너무 큰 limit
        response = client.get("/api/v1/scheduler/logs?limit=500")
        assert response.status_code == 422  # Validation error

        # 너무 작은 limit
        response = client.get("/api/v1/scheduler/logs?limit=0")
        assert response.status_code == 422
