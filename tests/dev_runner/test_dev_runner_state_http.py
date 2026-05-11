"""HTTP contract tests for DB-primary dev-runner state and merge queue reads."""

from datetime import datetime
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.dev_runner.routes.runner import router
from app.modules.dev_runner.schemas import MergeQueueItem, RunnerListItem


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/dev-runner")
    return TestClient(app, raise_server_exceptions=False)


def test_get_runners_http_returns_db_only_runner_row():
    row = RunnerListItem(
        runner_id="runner-db-only",
        running=False,
        plan_file="docs/plan/db.md",
        engine="codex",
        start_time=datetime(2026, 5, 6, 10, 30, 0),
        branch="impl/db",
        worktree_path="D:/work/project/tools/monitor-page/.worktrees/impl-db",
        redis_missing=True,
        log_file_found=True,
        display_state="stopped",
        display_label="중지됨",
    )
    with patch(
        "app.modules.dev_runner.routes.runner.executor_service.get_all_runners",
        new=AsyncMock(return_value=[row]),
    ):
        response = _client().get("/api/v1/dev-runner/runners")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["runner_id"] == "runner-db-only"
    assert body[0]["redis_missing"] is True
    assert body[0]["branch"] == "impl/db"


def test_get_merge_queue_http_returns_db_pending_row():
    item = MergeQueueItem(
        runner_id="runner-db",
        branch="impl/db",
        plan_file="docs/plan/db.md",
        project="monitor-page",
        status="queued",
        timestamp="2026-05-06T10:30:00",
        worktree_path="D:/work/project/tools/monitor-page/.worktrees/impl-db",
    )
    with patch(
        "app.modules.dev_runner.routes.runner.executor_service.get_merge_queue",
        new=AsyncMock(return_value=[item]),
    ):
        response = _client().get("/api/v1/dev-runner/merge-queue")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["runner_id"] == "runner-db"
    assert body[0]["status"] == "queued"


def test_get_merge_queue_http_db_unavailable_uses_redis_fallback_contract():
    fallback = MergeQueueItem(
        runner_id="runner-redis",
        branch="impl/redis",
        plan_file="docs/plan/redis.md",
        project="monitor-page",
        status="queued",
        timestamp="2026-05-06T10:31:00",
        worktree_path="D:/work/project/tools/monitor-page/.worktrees/impl-redis",
    )
    with patch(
        "app.modules.dev_runner.routes.runner.executor_service.get_merge_queue",
        new=AsyncMock(return_value=[fallback]),
    ):
        response = _client().get("/api/v1/dev-runner/merge-queue")

    assert response.status_code == 200
    assert response.json()[0]["runner_id"] == "runner-redis"
