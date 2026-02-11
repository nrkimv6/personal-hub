"""작업 API + 통계 API 테스트"""

import pytest


class TestGetTasks:
    async def test_get_tasks_returns_200(self, client, patch_db):
        response = await client.get("/api/v1/auto-next/tasks")
        assert response.status_code == 200
        data = response.json()
        assert "tasks" in data
        assert "total" in data
        assert isinstance(data["tasks"], list)

    async def test_get_tasks_total_count(self, client, patch_db):
        response = await client.get("/api/v1/auto-next/tasks")
        data = response.json()
        assert data["total"] == 3

    async def test_get_tasks_with_status_filter(self, client, patch_db):
        response = await client.get("/api/v1/auto-next/tasks?status=pending")
        data = response.json()
        assert data["total"] == 1
        assert data["tasks"][0]["status"] == "pending"

    async def test_get_tasks_with_limit(self, client, patch_db):
        response = await client.get("/api/v1/auto-next/tasks?limit=1")
        data = response.json()
        assert len(data["tasks"]) == 1
        assert data["total"] == 3


class TestGetTask:
    async def test_get_task_found(self, client, patch_db):
        response = await client.get("/api/v1/auto-next/tasks/test-1")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "test-1"
        assert data["text"] == "Test task 1"
        assert data["status"] == "success"

    async def test_get_task_not_found(self, client, patch_db):
        response = await client.get("/api/v1/auto-next/tasks/nonexistent")
        assert response.status_code == 404


class TestDeleteTask:
    async def test_delete_task_success(self, client, patch_db):
        response = await client.delete("/api/v1/auto-next/tasks/test-2")
        assert response.status_code == 200
        response = await client.get("/api/v1/auto-next/tasks/test-2")
        assert response.status_code == 404

    async def test_delete_task_not_found(self, client, patch_db):
        response = await client.delete("/api/v1/auto-next/tasks/nonexistent")
        assert response.status_code == 404


class TestGetStats:
    async def test_get_stats_returns_200(self, client, patch_db):
        response = await client.get("/api/v1/auto-next/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 3
        assert data["success"] == 1
        assert data["pending"] == 1
        assert data["failed"] == 1
        assert "completion_rate" in data
        assert "success_rate" in data
        assert "total_input_tokens" in data
        assert "total_output_tokens" in data
        assert "total_tokens" in data

    async def test_get_history(self, client, patch_db):
        response = await client.get("/api/v1/auto-next/history")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    async def test_get_duplicates(self, client, patch_db):
        response = await client.get("/api/v1/auto-next/duplicates")
        assert response.status_code == 200
        assert isinstance(response.json(), list)
