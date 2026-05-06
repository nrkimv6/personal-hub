"""E2E-style contract for Dev Runner post-merge-only residual visibility."""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.dev_runner.routes.runner import router as runner_router

pytestmark = pytest.mark.e2e


def test_post_merge_only_residual_runner_shows_followup_state():
    app = FastAPI()
    app.include_router(runner_router, prefix="/api/v1/dev-runner")
    client = TestClient(app, raise_server_exceptions=True)
    runner = {
        "runner_id": "runner-post-merge-ui",
        "running": False,
        "plan_file": "docs/plan/post-merge-only.md",
        "engine": "claude",
        "start_time": "2026-05-06T00:00:00",
        "pid": None,
        "worktree_path": ".worktrees/impl-post-merge-only",
        "branch": "impl/post-merge-only",
        "merge_status": "merge_pending",
        "exit_reason": "completed",
        "remaining_post_merge_tasks": 7,
        "merge_evidence_missing": False,
    }

    with patch(
        "app.modules.dev_runner.services.executor_service.executor_service.get_all_runners",
        new_callable=AsyncMock,
        return_value=[runner],
    ):
        response = client.get("/api/v1/dev-runner/runners")

    assert response.status_code == 200
    item = response.json()[0]
    assert item["merge_status"] == "merge_pending"
    assert item["remaining_post_merge_tasks"] == 7
    assert item["exit_reason"] == "completed"

