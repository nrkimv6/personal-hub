"""Phase T5: HTTP integration test for plan execution claim conflicts.

POST /api/v1/dev-runner/run must preserve the structured 409 detail emitted
by the executor when a live plan execution claim already exists.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient


pytestmark = pytest.mark.http


@pytest.fixture(scope="module")
def client():
    from app.main import app

    return TestClient(app)


class TestRunEndpointClaimConflict:
    """POST /api/v1/dev-runner/run claim conflict response contract."""

    @staticmethod
    def _make_409_detail(claim_id="claim-http-001", state="active"):
        return {
            "message": f"plan already claimed: claim_id={claim_id} state={state}",
            "claim_id": claim_id,
            "claim_state": state,
            "stale": False,
            "lease_expires_at": None,
        }

    def test_R_409_when_active_claim_exists(self, client):
        """R: active claim returns 409 with claim_id and claim_state."""
        from app.modules.dev_runner.services.executor_service import executor_service

        detail = self._make_409_detail(state="active")
        with patch.object(
            executor_service,
            "start_dev_runner",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=409, detail=detail),
        ):
            resp = client.post(
                "/api/v1/dev-runner/run",
                json={
                    "plan_file": "docs/plan/test-claim-http.md",
                    "engine": "claude",
                    "test_source": "test_R_409_when_active_claim_exists",
                },
            )

        assert resp.status_code == 409
        resp_detail = resp.json().get("detail", {})
        assert resp_detail["claim_id"] == "claim-http-001"
        assert resp_detail["claim_state"] == "active"

    def test_R_409_detail_structure_complete(self, client):
        """R: 409 detail keeps the claim fields required by the UI."""
        from app.modules.dev_runner.services.executor_service import executor_service

        detail = self._make_409_detail(state="active")
        with patch.object(
            executor_service,
            "start_dev_runner",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=409, detail=detail),
        ):
            resp = client.post(
                "/api/v1/dev-runner/run",
                json={
                    "plan_file": "docs/plan/test-claim-http-2.md",
                    "engine": "claude",
                    "test_source": "test_R_409_detail_structure_complete",
                },
            )

        assert resp.status_code == 409
        resp_detail = resp.json().get("detail", {})
        for field in ("claim_id", "claim_state", "stale", "message"):
            assert field in resp_detail
