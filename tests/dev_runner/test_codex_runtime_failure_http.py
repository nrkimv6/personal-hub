"""HTTP 통합 테스트 — codex accepted 이후 runtime 실패 노출 계약."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import fakeredis
import fakeredis.aioredis
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.dev_runner.routes.logs import router as logs_router
from app.modules.dev_runner.routes.runner import router as runner_router
from app.modules.dev_runner.schemas import RunStatusResponse
from app.modules.dev_runner.services.executor_service import executor_service
from app.modules.dev_runner.services.log_service import log_service
from tests.dev_runner.merge_test_helpers import emit_codex_runtime_failure

pytestmark = pytest.mark.http
BASE_URL = "/api/v1/dev-runner"


@pytest.fixture(autouse=True)
def dev_runner_config_isolation(tmp_path):
    """tests/dev_runner 공통 autouse fixture 오버라이드."""
    yield


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(runner_router, prefix=BASE_URL)
    app.include_router(logs_router, prefix=BASE_URL)
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture
def fake_services():
    """executor/log service Redis를 shared fakeredis로 고정."""
    server = fakeredis.FakeServer()
    fake_sync = fakeredis.FakeRedis(server=server, decode_responses=True)
    fake_async = fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)
    with patch.object(executor_service, "redis_client", fake_sync), \
         patch.object(executor_service, "async_redis", fake_async), \
         patch.object(log_service, "redis_client", fake_sync):
        yield {"sync": fake_sync, "async": fake_async}


def _cleanup_log(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


class TestCodexRuntimeFailureHttp:
    def test_run_accepted_then_runtime_failure_reflected_in_runners_and_logs(
        self,
        client,
        fake_services,
    ):
        """accepted 이후 runtime 실패(auto_plan_failed)가 runners/logs API에 동시 반영된다."""
        fake_sync = fake_services["sync"]
        fake_sync.set("plan-runner:listener:heartbeat", datetime.now().isoformat())
        synthetic = [
            "Error: unknown variant `xhigh`, expected one of `minimal`, `low`, `medium`, `high`",
            "in `model_reasoning_effort`",
        ]

        accepted = RunStatusResponse(
            running=True,
            engine="codex",
            runner_id="codex-runtime-accepted",
            plan_file="docs/plan/runtime-failure.md",
            listener_alive=True,
            redis_connected=True,
        )
        with patch(
            "app.modules.dev_runner.routes.runner.executor_service.start_dev_runner",
            new_callable=AsyncMock,
            return_value=accepted,
        ):
            response = client.post(
                f"{BASE_URL}/run",
                json={
                    "plan_file": "docs/plan/runtime-failure.md",
                    "engine": "codex",
                    "fix_engine": "codex",
                    "trigger": "tc:codex_runtime_failure_http",
                    "test_source": "test_codex_runtime_failure_http",
                },
            )

        assert response.status_code == 200
        runner_id = response.json()["runner_id"]

        log_path = emit_codex_runtime_failure(
            fake_sync,
            runner_id,
            plan_file="docs/plan/runtime-failure.md",
            trigger="tc:codex_runtime_failure_http",
            exit_reason="auto_plan_failed",
            stderr_lines=synthetic,
        )

        try:
            runners_resp = client.get(f"{BASE_URL}/runners")
            assert runners_resp.status_code == 200
            runners = runners_resp.json()
            target = next(item for item in runners if item["runner_id"] == runner_id)
            assert target["running"] is False
            assert target["exit_reason"] == "auto_plan_failed"

            logs_resp = client.get(f"{BASE_URL}/logs/recent", params={"runner_id": runner_id})
            assert logs_resp.status_code == 200
            lines = logs_resp.json()["lines"]
            merged = "\n".join(lines)
            assert "unknown variant" in merged
            assert "model_reasoning_effort" in merged
        finally:
            _cleanup_log(log_path)

    def test_runtime_failure_stderr_injection_is_deterministic(
        self,
        client,
        fake_services,
    ):
        """전역 codex 설정값과 무관하게 synthetic stderr를 결정적으로 주입/검증한다."""
        fake_sync = fake_services["sync"]
        runner_id = "codex-runtime-fixed-id"
        synthetic = [
            "Error: unknown variant `xhigh`, expected one of `minimal`, `low`, `medium`, `high`",
            "in `model_reasoning_effort`",
        ]

        log_path = emit_codex_runtime_failure(
            fake_sync,
            runner_id,
            plan_file="docs/plan/runtime-failure.md",
            trigger="tc:deterministic_injection",
            exit_reason="auto_plan_failed",
            stderr_lines=synthetic,
        )

        try:
            logs_resp = client.get(f"{BASE_URL}/logs/recent", params={"runner_id": runner_id})
            assert logs_resp.status_code == 200
            lines = logs_resp.json()["lines"]
            assert any("unknown variant `xhigh`" in line for line in lines)
            assert any("model_reasoning_effort" in line for line in lines)
        finally:
            _cleanup_log(log_path)
