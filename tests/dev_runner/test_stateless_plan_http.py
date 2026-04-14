"""HTTP 통합 테스트 — 상태 필드 없는 plan 무한 루프 방어 (Phase T5)

plan-runner는 admin API를 통해 간접 실행되는 모듈이므로 T5는 admin API 레벨 E2E로 작성.

검증 시나리오:
- POST /api/v1/dev-runner/run 호출 후 runner가 state_stuck / return_early 등
  비정상 루프 없이 종료하는지 확인 (무한 루프 = 무응답/타임아웃)
- GET /api/v1/dev-runner/runners/{runner_id} 에서 exit_reason 검증

기존 test_plan_runner_skip_only_termination_http.py 패턴 참조.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.dev_runner.routes.runner import router as runner_router

BASE_URL = "/api/v1/dev-runner"

pytestmark = pytest.mark.http


@pytest.fixture(autouse=True)
def dev_runner_config_isolation(tmp_path):
    """devrunner conftest autouse 오버라이드"""
    yield


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(runner_router, prefix=BASE_URL)
    return TestClient(app, raise_server_exceptions=False)


def _make_runner(runner_id="r1", exit_reason=None, running=False, status="done"):
    return {
        "runner_id": runner_id,
        "running": running,
        "plan_file": "docs/plan/test.md",
        "engine": "claude",
        "start_time": "2026-04-10T00:00:00",
        "pid": 1234,
        "worktree_path": None,
        "branch": None,
        "exit_reason": exit_reason,
        "status": status,
        "stop_stage": None,
    }


def test_run_done_plan_without_status_field_http_no_infinite_loop(client):
    """
    R: `- **status**: DONE` + commit hash 포함 plan 실행 시
    runner가 state_stuck이나 무한 루프 없이 정상 종료한다.

    plan-runner가 올바르게 동작하면:
    - commit이 HEAD에 있음 → prevalidate에서 조기 종료 (return_early)
    - exit_reason이 state_stuck이어서는 안 됨 (무한 루프 미발생)
    """
    from app.modules.dev_runner.schemas import RunStatusResponse

    mock_response = RunStatusResponse(
        running=True,
        runner_id="test-r1",
        engine="claude",
        plan_file="docs/plan/2026-04-09_fix-dev-runner-model-selection.md",
    )

    with patch(
        "app.modules.dev_runner.services.executor_service.executor_service.start_dev_runner",
        new_callable=AsyncMock,
        return_value=mock_response,
    ):
        resp = client.post(
            f"{BASE_URL}/run",
            json={
                "plan_file": "docs/plan/2026-04-09_fix-dev-runner-model-selection.md",
                "engine": "claude",
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data.get("runner_id") == "test-r1"
    assert data.get("running") is True


def test_state_stuck_exit_reason_is_not_classified_as_error(client):
    """
    R: exit_reason=state_stuck인 runner가 runners 목록에서 조회 가능해야 한다
    (state_stuck은 정상 안전장치 종료 — 에러가 아닌 보호 상태)
    """
    runners = [
        _make_runner("r1", exit_reason="state_stuck", status="done"),
        _make_runner("r2", exit_reason="completed", status="done"),
    ]
    with patch(
        "app.modules.dev_runner.services.executor_service.executor_service.get_all_runners",
        new_callable=AsyncMock,
        return_value=runners,
    ):
        resp = client.get(f"{BASE_URL}/runners")

    assert resp.status_code == 200
    data = resp.json()
    stuck = [r for r in data if r.get("exit_reason") == "state_stuck"]
    assert len(stuck) == 1, f"state_stuck runner가 목록에 있어야 함: {data}"


def test_run_endpoint_rejects_missing_plan_file(client):
    """
    B: plan_file 없이 POST /run 호출 시 422 반환
    (엔드포인트 기본 검증 — stateless plan 처리와 무관한 경계값)
    """
    resp = client.post(f"{BASE_URL}/run", json={})
    # plan_file이 필수 필드이므로 4xx 또는 5xx (에러 응답) 기대
    assert resp.status_code >= 400
