"""HTTP 통합 테스트 — stop-all API (TestClient 기반)

Phase T4: POST /api/v1/dev-runner/stop-all 엔드포인트 검증
실제 Redis/listener 없이 executor_service를 mock으로 교체하여 HTTP 레이어만 검증합니다.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from app.modules.dev_runner.services.executor_service import ExecutorService

pytestmark = pytest.mark.http

BASE_URL = "/api/v1/dev-runner"


@pytest.fixture(autouse=True)
def dev_runner_config_isolation(tmp_path):
    """devrunner conftest autouse 오버라이드 — plan_service 의존성 없음"""
    yield


@pytest.fixture
def client():
    """TestClient — DB/Redis 연결 없이 HTTP 레이어 테스트"""
    from app.main import app
    return TestClient(app, raise_server_exceptions=True)


def _mock_executor_stop_all(stopped: int):
    """stop_all_runners()를 mock하여 지정된 stopped 수를 반환하는 패치 컨텍스트"""
    return patch(
        "app.modules.dev_runner.routes.runner.executor_service.stop_all_runners",
        new_callable=AsyncMock,
        return_value={"stopped": stopped},
    )


def _mock_executor_get_all(runners: list):
    """get_all_runners()를 mock하여 지정된 목록을 반환하는 패치 컨텍스트"""
    return patch(
        "app.modules.dev_runner.routes.runner.executor_service.get_all_runners",
        return_value=runners,
    )


def _mock_executor_start(runner_id: str = "testaaaa"):
    """start_dev_runner()를 mock하여 RunStatusResponse를 반환하는 패치 컨텍스트"""
    from app.modules.dev_runner.schemas import RunStatusResponse
    from datetime import datetime
    mock_response = RunStatusResponse(
        running=True,
        runner_id=runner_id,
        engine="claude",
        pid=1234,
        plan_file="test.md",
        start_time=datetime.now(),
        current_cycle=0,
        listener_alive=True,
        redis_connected=True,
    )
    return patch(
        "app.modules.dev_runner.routes.runner.executor_service.start_dev_runner",
        new_callable=AsyncMock,
        return_value=mock_response,
    )


def _mock_executor_stop_one(runner_id: str = "testaaaa"):
    """stop_dev_runner()를 mock하는 패치 컨텍스트"""
    return patch(
        "app.modules.dev_runner.routes.runner.executor_service.stop_dev_runner",
        new_callable=AsyncMock,
        return_value={"message": "Stopped successfully"},
    )


class TestHttpStopAll200:
    """HTTP 200 응답 및 stopped 카운트 검증"""

    def test_http_stop_all_200(self, client):
        """mock runner 2개 → POST /stop-all → 200 + {"stopped": 2}"""
        with _mock_executor_stop_all(stopped=2):
            response = client.post(f"{BASE_URL}/stop-all")

        assert response.status_code == 200
        data = response.json()
        assert data.get("stopped") == 2

    def test_http_stop_all_empty_200(self, client):
        """runner 없을 때 → 200 + {"stopped": 0} (에러 아님)"""
        with _mock_executor_stop_all(stopped=0):
            response = client.post(f"{BASE_URL}/stop-all")

        assert response.status_code == 200
        data = response.json()
        assert data.get("stopped") == 0


class TestHttpStartWhileRunning:
    """실행 중 추가 시작 — 409 없음 검증"""

    def test_http_start_while_running_200(self, client):
        """runner 실행 중 POST /run → 200 + 새 runner_id (409 아님)"""
        with _mock_executor_start(runner_id="t-stopall-new"):
            response = client.post(
                f"{BASE_URL}/run",
                json={"plan_file": "test.md", "engine": "claude"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data.get("runner_id") == "t-stopall-new"
        assert data.get("running") is True


class TestHttpRunnersListAfterTwoStarts:
    """2번 start 후 /runners 목록 검증"""

    def test_http_runners_list_after_two_starts(self, client):
        """POST /run 2회 후 GET /runners → 200 + list 2개"""
        from app.modules.dev_runner.schemas import RunnerListItem
        from datetime import datetime

        mock_runners = [
            RunnerListItem(
                runner_id="t-stopall-01",
                running=True,
                plan_file="plan_a.md",
                engine="claude",
                start_time=datetime.now(),
                pid=1111,
                worktree_path=None,
                branch=None,
                merge_status=None,
            ),
            RunnerListItem(
                runner_id="t-stopall-02",
                running=True,
                plan_file="plan_b.md",
                engine="claude",
                start_time=datetime.now(),
                pid=2222,
                worktree_path=None,
                branch=None,
                merge_status=None,
            ),
        ]

        with _mock_executor_get_all(runners=mock_runners):
            response = client.get(f"{BASE_URL}/runners")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 2
        runner_ids = {r["runner_id"] for r in data}
        assert "t-stopall-01" in runner_ids
        assert "t-stopall-02" in runner_ids


class TestHttpStopIndividualThenStopAll:
    """개별 stop 후 stop-all 검증"""

    def test_http_stop_individual_then_stop_all(self, client):
        """POST /runners/{id}/stop 후 POST /stop-all → stopped: 1"""
        # 개별 stop
        with _mock_executor_stop_one():
            stop_resp = client.post(f"{BASE_URL}/runners/runner01/stop")

        # stop-all (남은 runner 1개만 처리)
        with _mock_executor_stop_all(stopped=1):
            all_stop_resp = client.post(f"{BASE_URL}/stop-all")

        assert stop_resp.status_code == 200
        assert all_stop_resp.status_code == 200
        assert all_stop_resp.json().get("stopped") == 1


class TestHttpAllStoppedNoRunners:
    """전체 종료 후 GET /runners 빈 목록"""

    def test_http_all_stopped_no_runners(self, client):
        """전체 종료 후 GET /runners → 200 + 빈 list"""
        with _mock_executor_get_all(runners=[]):
            response = client.get(f"{BASE_URL}/runners")

        assert response.status_code == 200
        data = response.json()
        assert data == []


class TestHttpStopAllResponseSchema:
    """응답 스키마 검증"""

    def test_http_stop_all_response_schema(self, client):
        """응답 JSON에 'stopped' 정수 필드 존재"""
        with _mock_executor_stop_all(stopped=3):
            response = client.post(f"{BASE_URL}/stop-all")

        assert response.status_code == 200
        data = response.json()
        assert "stopped" in data
        assert isinstance(data["stopped"], int)
        assert data["stopped"] >= 0
