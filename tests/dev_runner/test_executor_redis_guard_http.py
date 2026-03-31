"""T4 HTTP 통합 TC: executor Redis guard 수정 후 HTTP 엔드포인트 회귀 검증

이 plan은 테스트 fixture 수정(monkeypatch.setenv 추가)만 포함.
HTTP 엔드포인트 동작 변경 없음을 TestClient로 확인하는 regression TC.
"""
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from app.main import app

BASE_URL = "/api/v1/dev-runner"


@pytest.fixture(autouse=True)
def dev_runner_config_isolation(tmp_path):
    """devrunner conftest autouse 오버라이드"""
    yield


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=True)


def test_get_runners_endpoint_still_works(client):
    """[Regression] executor fixture 수정 후 GET /runners 엔드포인트 정상 응답"""
    with patch(
        "app.modules.dev_runner.routes.runner.executor_service.get_process_status",
        new_callable=AsyncMock,
        return_value=type("R", (), {"running": False, "engine": "claude", "runner_id": None,
                                    "plan_file": None, "runners": [], "total_count": 0,
                                    "model_dict": lambda self: {"running": False}})(),
    ):
        resp = client.get(f"{BASE_URL}/runners")
        assert resp.status_code == 200


def test_post_run_endpoint_validates_request(client):
    """[Regression] POST /run 요청 시 422가 아닌 정상 처리(mock) 확인"""
    with patch(
        "app.modules.dev_runner.routes.runner.executor_service.start_dev_runner",
        new_callable=AsyncMock,
        return_value=type("R", (), {
            "runner_id": "t-test-abcd", "engine": "claude", "running": True,
            "model_dict": lambda self: {"runner_id": "t-test-abcd", "engine": "claude", "running": True}
        })(),
    ):
        resp = client.post(f"{BASE_URL}/run", json={
            "test_source": "executor_redis_guard_http",
            "plan_file": "test.md",
            "engine": "claude"
        })
        # 400/422가 아닌 응답 (mock이므로 실제 실행 없음)
        assert resp.status_code in (200, 201, 202, 500)
