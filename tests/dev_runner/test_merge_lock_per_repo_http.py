"""T5 HTTP: merge lock API 경유 회귀 테스트."""
from __future__ import annotations

import inspect
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

pytestmark = pytest.mark.http

BASE_URL = "/api/v1/dev-runner"
_PLAN_RUNNER_DIR = Path(__file__).resolve().parents[2] / "scripts" / "plan_runner"
if str(_PLAN_RUNNER_DIR) not in sys.path:
    sys.path.insert(0, str(_PLAN_RUNNER_DIR))


@pytest.fixture
def client():
    from app.modules.dev_runner.routes import router as dev_runner_router

    app = FastAPI()
    app.include_router(dev_runner_router)
    with TestClient(app) as c:
        yield c


def test_direct_merge_http_dispatch_uses_configured_lock_contract(client):
    """POST /merge/direct 경로의 merge helper가 600초 literal이 아닌 24h 기본 계약을 가진다."""
    import _dr_merge

    source = inspect.getsource(_dr_merge._execute_merge_with_lock)
    assert "timeout=600" not in source
    assert _dr_merge.DEFAULT_MERGE_LOCK_TIMEOUT_SECONDS == 86400

    with patch(
        "app.modules.dev_runner.routes.runner.executor_service.send_direct_merge_command",
        new=AsyncMock(return_value={"success": True, "message": "accepted"}),
    ) as send_direct:
        resp = client.post(
            f"{BASE_URL}/merge/direct",
            json={
                "branch": "impl/test-timeout",
                "worktree_path": "D:/tmp/impl-test-timeout",
                "plan_file": "docs/plan/test-timeout.md",
            },
        )

    assert resp.status_code == 200
    send_direct.assert_awaited_once()


def test_direct_merge_http_redis_unavailable_is_not_200_success(client):
    """POST /merge/direct가 Redis unavailable을 200 success로 숨기지 않는다."""
    with patch(
        "app.modules.dev_runner.routes.runner.executor_service.send_direct_merge_command",
        new=AsyncMock(side_effect=HTTPException(status_code=503, detail="REDIS_UNAVAILABLE")),
    ):
        resp = client.post(
            f"{BASE_URL}/merge/direct",
            json={
                "branch": "impl/test-redis-unavailable",
                "worktree_path": "D:/tmp/impl-test-redis-unavailable",
                "plan_file": "docs/plan/test-redis-unavailable.md",
            },
        )

    assert resp.status_code == 503
    assert "REDIS_UNAVAILABLE" in resp.text


def test_retry_merge_http_redis_unavailable_is_not_200_success(client):
    """POST /merge/{runner_id}/retry가 Redis unavailable을 200 success로 숨기지 않는다."""
    with patch(
        "app.modules.dev_runner.routes.runner.executor_service.send_runner_command",
        new=AsyncMock(side_effect=HTTPException(status_code=503, detail="REDIS_UNAVAILABLE")),
    ):
        resp = client.post(
            f"{BASE_URL}/merge/runner-redis-unavailable/retry",
            json={"worktree_path": "D:/tmp/retry", "branch": "impl/retry"},
        )

    assert resp.status_code == 503
    assert "REDIS_UNAVAILABLE" in resp.text
