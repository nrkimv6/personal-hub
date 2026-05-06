"""trigger source HTTP 통합 테스트

Phase T5: FastAPI TestClient로 trigger 필드 포함 API 동작 검증
"""
import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.http


def _build_test_client() -> TestClient:
    from app.main import app
    return TestClient(app)


@pytest.fixture(scope="module")
def client():
    return _build_test_client()


def test_http_post_run_with_trigger(client):
    """T5: POST /api/v1/dev-runner/run body에 trigger='user' 포함 → 스키마 파싱 검증"""
    from unittest.mock import patch, AsyncMock
    from app.modules.dev_runner.schemas import RunRequest, RunStatusResponse

    # RunRequest에 trigger 필드가 파싱되는지 검증
    req = RunRequest(plan_file="test.md", trigger="user", dry_run=True)
    assert req.trigger == "user"

    # start API 호출 (Redis 없으므로 mock)
    mock_response = RunStatusResponse(
        running=True,
        listener_alive=True,
        redis_connected=True,
        runner_id="test-http-01",
    )
    with patch(
        "app.modules.dev_runner.routes.runner.executor_service.start_dev_runner",
        new=AsyncMock(return_value=mock_response),
    ):
        r = client.post(
            "/api/v1/dev-runner/run",
            json={"plan_file": "test.md", "trigger": "user", "dry_run": True},
        )
    assert r.status_code == 200, f"HTTP {r.status_code}: {r.text}"


def test_http_post_run_without_trigger(client):
    """T5: trigger 미포함 → 200 응답 (하위호환), trigger 자동 폴백 'api'"""
    from unittest.mock import patch, AsyncMock
    from app.modules.dev_runner.schemas import RunRequest, RunStatusResponse

    # trigger 없는 RunRequest — 기본값 None
    req = RunRequest(plan_file="test.md", dry_run=True)
    assert req.trigger is None

    mock_response = RunStatusResponse(
        running=True,
        listener_alive=True,
        redis_connected=True,
        runner_id="test-http-02",
    )
    with patch(
        "app.modules.dev_runner.routes.runner.executor_service.start_dev_runner",
        new=AsyncMock(return_value=mock_response),
    ):
        r = client.post(
            "/api/v1/dev-runner/run",
            json={"plan_file": "test.md", "dry_run": True},
        )
    assert r.status_code == 200, f"HTTP {r.status_code}: {r.text}"


def test_http_history_includes_trigger(client):
    """T5: GET /api/v1/dev-runner/logs/history 응답에 trigger 필드 존재"""
    from unittest.mock import patch
    from app.modules.dev_runner.schemas import RunHistoryItem, RunHistoryResponse

    mock_history = RunHistoryResponse(
        runs=[
            RunHistoryItem(
                runner_id="test-hist-01",
                plan_file="test.md",
                engine="claude",
                status="completed",
                has_log=False,
                trigger="user",
            )
        ],
        total=1,
    )
    with patch(
        "app.modules.dev_runner.routes.logs.log_service.get_run_history",
        return_value=mock_history,
    ):
        r = client.get("/api/v1/dev-runner/logs/history")
    assert r.status_code == 200, f"HTTP {r.status_code}: {r.text}"
    data = r.json()
    assert "runs" in data
    assert len(data["runs"]) > 0
    assert "trigger" in data["runs"][0], f"trigger 필드 없음: {data['runs'][0]}"
    assert data["runs"][0]["trigger"] == "user"
