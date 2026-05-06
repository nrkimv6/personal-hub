"""Phase T5: HTTP 통합 테스트 — plan 실행점유 claim HTTP 응답

POST /api/v1/dev-runner/run 에서 live claim 충돌 시 409 + structured detail 검증.
TestClient 기반 (실서버 불필요).

전략: executor_service.start_dev_runner를 모킹하여 ClaimConflictError 처리 결과인
HTTPException(409, detail={...})를 직접 발생시킨다.
실제 ClaimConflictError → HTTPException 변환 코드(executor_service.py)에서 생성하는
동일한 구조의 detail dict를 사용해 HTTP 계층의 409 전달 여부를 검증한다.
"""
import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient


pytestmark = pytest.mark.http


@pytest.fixture(scope="module")
def client():
    from app.main import app
    return TestClient(app)


class TestRunEndpointClaimConflict:
    """POST /api/v1/dev-runner/run — claim 충돌 시 409 structured detail 검증"""

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
        """R: active claim이 있으면 409 + claim_id/claim_state 포함 detail 반환"""
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
        assert "claim_id" in resp_detail
        assert "claim_state" in resp_detail
        assert resp_detail["claim_id"] == "claim-http-001"
        assert resp_detail["claim_state"] == "active"

    def test_R_409_detail_structure_complete(self, client):
        """R: 409 detail에 claim_id, claim_state, stale, message 필드가 있다"""
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
            assert field in resp_detail, f"detail에 '{field}' 누락: {resp_detail}"


def _encode_path(path: str) -> str:
    return base64.urlsafe_b64encode(path.encode("utf-8")).decode("ascii").rstrip("=")


class TestPlanClaimReleaseEndpoint:
    """DELETE /plans/{encoded_path}/claim — active/queued claim release HTTP 계약"""

    def test_R_delete_claim_releases_queued_claim(self, client):
        claim = SimpleNamespace(claim_id="claim-http-release-001")
        mock_get = MagicMock(return_value=claim)
        mock_release = MagicMock()

        with patch(
            "app.modules.dev_runner.services.plan_execution_claim_service.get_active_claim_for_plan",
            mock_get,
        ), patch(
            "app.modules.dev_runner.services.plan_execution_claim_service.release_claim",
            mock_release,
        ):
            resp = client.delete(
                f"/api/v1/dev-runner/plans/{_encode_path('docs/plan/queued-claim.md')}/claim"
            )

        assert resp.status_code == 200
        assert resp.json() == {"ok": True, "claim_id": "claim-http-release-001"}
        mock_get.assert_called_once()
        assert mock_get.call_args.args[1] == "docs/plan/queued-claim.md"
        mock_release.assert_called_once_with(mock_get.call_args.args[0], claim.claim_id)

    def test_B_delete_claim_returns_404_when_no_active_claim(self, client):
        with patch(
            "app.modules.dev_runner.services.plan_execution_claim_service.get_active_claim_for_plan",
            return_value=None,
        ):
            resp = client.delete(
                f"/api/v1/dev-runner/plans/{_encode_path('docs/plan/no-claim.md')}/claim"
            )

        assert resp.status_code == 404
        assert resp.json()["detail"] == "active claim not found"
