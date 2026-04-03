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
from sqlalchemy.orm import sessionmaker

from app.database import get_db
from app.models.workflow import Workflow
from app.modules.dev_runner.routes.logs import router as logs_router
from app.modules.dev_runner.routes.runner import router as runner_router
from app.modules.dev_runner.routes.workflows import router as workflows_router
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
def client(test_db_engine):
    from app import database as app_database
    from app.core import database as core_database

    app = FastAPI()
    app.include_router(runner_router, prefix=BASE_URL)
    app.include_router(logs_router, prefix=BASE_URL)
    app.include_router(workflows_router, prefix=f"{BASE_URL}/workflows")

    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_db_engine)

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with patch.object(app_database, "SessionLocal", SessionLocal), \
         patch.object(core_database, "SessionLocal", SessionLocal):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c
    app.dependency_overrides.clear()


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


def _seed_failed_workflow(
    test_db_engine,
    *,
    slug: str,
    runner_id: str,
    plan_file: str,
    error_message: str,
) -> int:
    """runtime 실패를 반영한 workflow 레코드를 테스트 DB에 생성."""
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_db_engine)
    db = SessionLocal()
    try:
        wf = Workflow(
            slug=slug,
            plan_file=plan_file,
            runner_id=runner_id,
            status="failed",
            engine="codex",
            error_message=error_message,
            started_at=datetime.now(),
            finished_at=datetime.now(),
        )
        db.add(wf)
        db.commit()
        db.refresh(wf)
        return int(wf.id)
    finally:
        db.close()


class TestCodexRuntimeFailureHttp:
    def test_run_accepted_then_runtime_failure_reflected_in_runners_and_logs(
        self,
        client,
        fake_services,
        test_db_engine,
    ):
        """accepted 이후 runtime 실패가 runners/workflows/logs API에 일관 반영된다."""
        fake_sync = fake_services["sync"]
        fake_sync.set("plan-runner:listener:heartbeat", datetime.now().isoformat())
        runner_id = f"codex-runtime-{datetime.now().strftime('%H%M%S%f')}"
        plan_file = "docs/plan/runtime-failure.md"
        synthetic = [
            "Error: unknown variant `xhigh`, expected one of `minimal`, `low`, `medium`, `high`",
            "in `model_reasoning_effort`",
        ]
        error_detail = synthetic[0]
        workflow_error = f"exit_code=15; exit_reason=auto_plan_failed; detail={error_detail}"

        accepted = RunStatusResponse(
            running=True,
            engine="codex",
            runner_id=runner_id,
            plan_file=plan_file,
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
                    "plan_file": plan_file,
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
            plan_file=plan_file,
            trigger="tc:codex_runtime_failure_http",
            exit_reason="auto_plan_failed",
            stderr_lines=synthetic,
        )
        fake_sync.set(f"plan-runner:runners:{runner_id}:error", error_detail)
        _seed_failed_workflow(
            test_db_engine,
            slug=f"runtime-failure-{runner_id}",
            runner_id=runner_id,
            plan_file=plan_file,
            error_message=workflow_error,
        )

        try:
            runners_resp = client.get(f"{BASE_URL}/runners")
            assert runners_resp.status_code == 200
            runners = runners_resp.json()
            target = next(item for item in runners if item["runner_id"] == runner_id)
            assert target["running"] is False
            assert target["exit_reason"] == "auto_plan_failed"
            assert target["error"] == error_detail

            workflows_resp = client.get(f"{BASE_URL}/workflows", params={"status": "failed"})
            assert workflows_resp.status_code == 200
            failed_workflows = workflows_resp.json()
            workflow = next(item for item in failed_workflows if item["runner_id"] == runner_id)
            assert workflow["error_message"] == workflow_error

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
