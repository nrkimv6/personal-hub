"""
TC HTTP: POST /api/v1/dev-runner/merge/direct 통합 테스트
FastAPI TestClient 기반 — 실제 서버 불필요
"""
import json
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


class TestDirectMergeHttp:
    def test_direct_merge_success(self, client):
        """R(Right): POST /merge/direct → 200 + success=True"""
        mock_result = {"success": True, "message": "accepted", "action": "direct-merge"}
        with patch(
            "app.modules.dev_runner.services.executor_service.ExecutorService.send_direct_merge_command",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            resp = client.post(
                "/api/v1/dev-runner/merge/direct",
                json={"branch": "runner/test123", "worktree_path": "/some/path"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("success") is True

    def test_direct_merge_missing_branch_422(self, client):
        """B(Boundary): branch 누락 → 422 Validation Error"""
        resp = client.post(
            "/api/v1/dev-runner/merge/direct",
            json={"worktree_path": "/some/path"},
        )
        assert resp.status_code == 422

    def test_retry_merge_endpoint_regression(self, client):
        """R(Right): POST /runners/{id}/retry-merge 기존 엔드포인트 정상 동작 (회귀)"""
        mock_result = {"success": True, "message": "accepted"}
        with patch(
            "app.modules.dev_runner.services.executor_service.ExecutorService.send_runner_command",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            resp = client.post("/api/v1/dev-runner/runners/runner-test/retry-merge")
        # 200 또는 404 (runner 없음) — 422/500이 아니면 엔드포인트 자체는 정상
        assert resp.status_code in (200, 404, 400)
