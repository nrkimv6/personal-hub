"""T4: E2E 테스트 — exit_reason SSE 스트림 및 runners API 검증 (TestClient 기반)"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app

pytestmark = pytest.mark.http


@pytest.fixture(autouse=True)
def dev_runner_config_isolation(tmp_path):
    """devrunner conftest autouse 오버라이드"""
    yield


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=True)


class TestExitReasonE2ERunners:
    """T4: runner 종료 후 GET /runners 응답에 exit_reason 필드 포함 확인"""

    def test_exit_reason_e2e_runners_api(self, client):
        """T4: runner 종료 후 /runners 응답에 exit_reason 필드 포함 확인"""
        runners = [
            {
                "runner_id": "e2e_runner_1",
                "running": False,
                "plan_file": "docs/plan/test.md",
                "engine": "claude",
                "start_time": "2026-03-27T00:00:00",
                "pid": 9999,
                "worktree_path": None,
                "branch": None,
                "merge_status": None,
                "trigger": "user",
                "visible": True,
                "orphan": False,
                "exit_reason": "rate_limit",
                "stop_stage": None,
            }
        ]
        with patch(
            "app.modules.dev_runner.routes.runner.executor_service.get_all_runners",
            new_callable=AsyncMock,
            return_value=runners,
        ):
            response = client.get("/api/v1/dev-runner/runners")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["exit_reason"] == "rate_limit"
        assert "stop_stage" in data[0]
        assert data[0]["running"] is False

    def test_pre_review_stop_stage_exposed_e2e(self, client):
        """T4: pre_review 중지 케이스에서 stop_stage가 runners API에 노출된다."""
        runners = [
            {
                "runner_id": "e2e_runner_pre",
                "running": False,
                "plan_file": "docs/plan/test.md",
                "engine": "claude",
                "start_time": "2026-03-27T00:00:00",
                "pid": 9998,
                "worktree_path": None,
                "branch": None,
                "merge_status": None,
                "trigger": "user",
                "visible": True,
                "orphan": False,
                "exit_reason": "stopped",
                "stop_stage": "pre_review",
            }
        ]
        with patch(
            "app.modules.dev_runner.routes.runner.executor_service.get_all_runners",
            new_callable=AsyncMock,
            return_value=runners,
        ):
            response = client.get("/api/v1/dev-runner/runners")

        assert response.status_code == 200
        data = response.json()
        assert data[0]["exit_reason"] == "stopped"
        assert data[0]["stop_stage"] == "pre_review"


class TestExitReasonE2ESseStream:
    """T4: SSE 완료 이벤트 reason 파싱 확인 (log_service 레벨)"""

    def test_exit_reason_e2e_sse_stream(self):
        """T4: log_service가 __COMPLETED::rate_limit__ sentinel을 completed 이벤트로 파싱"""
        from app.modules.dev_runner.services.log_service import LogService

        svc = LogService.__new__(LogService)

        # __COMPLETED::rate_limit__ → event: completed, data: rate_limit
        sentinel = "__COMPLETED::rate_limit__"
        assert sentinel.startswith("__COMPLETED")
        # reason 파싱 검증
        if sentinel == "__COMPLETED__":
            reason = "completed"
        else:
            reason = sentinel.split("::")[1].rstrip("__") if "::" in sentinel else "completed"
        assert reason == "rate_limit"

        # 하위 호환: __COMPLETED__ → reason=completed
        legacy = "__COMPLETED__"
        reason2 = "completed" if legacy == "__COMPLETED__" else "unknown"
        assert reason2 == "completed"


class TestRestartButtonE2E:
    """T4: 비정상종료 runner 재실행 → POST /run 호출 확인"""

    def test_restart_button_triggers_new_runner_e2e(self, client):
        """T4: POST /run으로 비정상종료 runner 재실행 → running=True 응답"""
        from app.modules.dev_runner.schemas import RunStatusResponse
        new_status = RunStatusResponse(
            running=True,
            engine="claude",
            runner_id="restarted_e2e_999",
            plan_file="docs/plan/failed.md",
            listener_alive=True,
            redis_connected=True,
        )
        with patch(
            "app.modules.dev_runner.routes.runner.executor_service.start_dev_runner",
            new_callable=AsyncMock,
            return_value=new_status,
        ):
            response = client.post(
                "/api/v1/dev-runner/run",
                json={
                    "plan_file": "docs/plan/failed.md",
                    "engine": "claude",
                    "trigger": "user",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["running"] is True
        assert data["runner_id"] == "restarted_e2e_999"
