"""Phase T5: HTTP 통합 테스트 — plan 실행점유 claim 409 충돌 응답

POST /api/v1/dev-runner/run 에서 live claim 충돌 시 409 + structured detail 검증.
TestClient 기반 (실서버 불필요).

전략: executor_service.start_dev_runner를 모킹하여 ClaimConflictError 처리 결과인
HTTPException(409, detail={...})를 직접 발생시킨다.
실제 ClaimConflictError → HTTPException 변환 코드(executor_service.py)에서 생성하는
동일한 구조의 detail dict를 사용해 HTTP 계층의 409 전달 여부를 검증한다.
"""
import pytest
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException
from fastapi.testclient import TestClient


pytestmark = pytest.mark.http


@pytest.fixture(scope="module")
def client():
    from app.main import app
    return TestClient(app)


class TestRunEndpointClaimConflict:
    """POST /api/v1/dev-runner/run — claim 충돌 시 409 structured detail 검증"""

    def _make_409_detail(self, claim_id="claim-http-001", state="active"):
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
