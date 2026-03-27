"""HTTP 통합 테스트 — exit_reason 필드 (TestClient 기반)

Phase T5: exit_reason 관련 HTTP 엔드포인트 검증
- GET /api/v1/dev-runner/runners 응답에 exit_reason 필드 존재 확인
- POST /api/v1/dev-runner/run 재실행 호출 확인
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
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


def _make_runner(runner_id="abc123", exit_reason=None):
    """RunnerListItem 모의 딕셔너리 생성"""
    return {
        "runner_id": runner_id,
        "running": False,
        "plan_file": "docs/plan/test.md",
        "engine": "claude",
        "start_time": "2026-03-27T00:00:00",
        "pid": 1234,
        "worktree_path": None,
        "branch": None,
        "merge_status": None,
        "trigger": "user",
        "visible": True,
        "orphan": False,
        "exit_reason": exit_reason,
    }


class TestRunnersApiExitReasonHttp:
    """T5: GET /runners 응답에 exit_reason 필드 존재 확인"""

    @pytest.mark.http
    def test_runners_api_exit_reason_present(self, client):
        """exit_reason이 있는 runner → 응답 JSON에 exit_reason 필드 존재"""
        runners = [_make_runner("r1", exit_reason="rate_limit")]
        with patch(
            "app.modules.dev_runner.routes.runner.executor_service.get_all_runners",
            new_callable=AsyncMock,
            return_value=runners,
        ):
            response = client.get(f"{BASE_URL}/runners")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert "exit_reason" in data[0]
        assert data[0]["exit_reason"] == "rate_limit"

    @pytest.mark.http
    def test_runners_api_exit_reason_null_when_absent(self, client):
        """exit_reason이 없는 runner → 응답 JSON에 exit_reason=null"""
        runners = [_make_runner("r2", exit_reason=None)]
        with patch(
            "app.modules.dev_runner.routes.runner.executor_service.get_all_runners",
            new_callable=AsyncMock,
            return_value=runners,
        ):
            response = client.get(f"{BASE_URL}/runners")

        assert response.status_code == 200
        data = response.json()
        assert "exit_reason" in data[0]
        assert data[0]["exit_reason"] is None


class TestRestartRunnerHttp:
    """T5: 비정상종료 runner의 plan_file로 POST /run 재호출"""

    @pytest.mark.http
    def test_restart_runner_via_run_endpoint(self, client):
        """POST /run → 새 runner 생성 (plan_file 동일, 새 runner_id)"""
        from app.modules.dev_runner.schemas import RunStatusResponse
        new_status = RunStatusResponse(
            running=True,
            engine="claude",
            runner_id="new999",
            plan_file="docs/plan/test.md",
            listener_alive=True,
            redis_connected=True,
        )
        with patch(
            "app.modules.dev_runner.routes.runner.executor_service.start_dev_runner",
            new_callable=AsyncMock,
            return_value=new_status,
        ):
            response = client.post(
                f"{BASE_URL}/run",
                json={
                    "plan_file": "docs/plan/test.md",
                    "engine": "claude",
                    "trigger": "user",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["runner_id"] == "new999"
        assert data["running"] is True
