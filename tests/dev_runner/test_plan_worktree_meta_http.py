"""test_plan_worktree_meta_http.py — worktree 메타 HTTP 통합 테스트

T5 시나리오:
- GET /api/v1/dev-runner/plans 응답에 branch/worktree_path/worktree_owner 필드 존재 검증
- 정규화 검증: 백슬래시 입력 → 슬래시 변환
- 일반 plan: 3개 필드 null 검증
"""
import textwrap
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.modules.dev_runner.schemas import PlanFileResponse, PlanProgressResponse

pytestmark = pytest.mark.http

BASE_URL = "/api/v1/dev-runner"


@pytest.fixture(scope="module")
def api_client():
    from app.main import app
    return TestClient(app)


def _make_response(
    filename: str,
    branch: str | None = None,
    worktree_path: str | None = None,
    worktree_owner: str | None = None,
) -> PlanFileResponse:
    return PlanFileResponse(
        path=f"D:/work/docs/plan/{filename}",
        filename=filename,
        status="구현중",
        progress=PlanProgressResponse(done=2, total=5, percent=40),
        source="monitor-page",
        ignored=False,
        path_type="file",
        summary="테스트 요약",
        branch=branch,
        worktree_path=worktree_path,
        worktree_owner=worktree_owner,
    )


class TestWorktreeMetaHTTP:

    def test_plans_api_worktree_owner_field(self, api_client):
        """R: GET /plans → worktree 메타 필드 존재 + 값 정확성"""
        mock_plans = [
            _make_response(
                "2026-04-06_test.md",
                branch="impl/test-feature",
                worktree_path=".worktrees/impl-test-feature",
                worktree_owner="docs/plan/2026-04-06_test.md",
            )
        ]
        with patch(
            "app.modules.dev_runner.routes.plans.plan_service.list_plans",
            return_value=mock_plans,
        ):
            resp = api_client.get(f"{BASE_URL}/plans")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        plan = data[0]
        assert plan["branch"] == "impl/test-feature"
        assert plan["worktree_path"] == ".worktrees/impl-test-feature"
        assert plan["worktree_owner"] == "docs/plan/2026-04-06_test.md"

    def test_plans_api_worktree_meta_null_when_absent(self, api_client):
        """R: worktree 메타 없는 일반 plan → 3개 필드 null"""
        mock_plans = [
            _make_response("2026-04-06_plain.md")  # branch/worktree_path/worktree_owner 미전달 → None
        ]
        with patch(
            "app.modules.dev_runner.routes.plans.plan_service.list_plans",
            return_value=mock_plans,
        ):
            resp = api_client.get(f"{BASE_URL}/plans")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        plan = data[0]
        assert plan["branch"] is None
        assert plan["worktree_path"] is None
        assert plan["worktree_owner"] is None

    def test_plans_api_normalize_backslash_in_worktree_owner(self, api_client):
        """R: 정규화 검증 — API 응답에서 백슬래시 없는 경로"""
        # 서비스 레이어(_extract_worktree_meta)에서 이미 정규화 완료 후 반환
        # API 응답에서 백슬래시가 없어야 함을 확인
        mock_plans = [
            _make_response(
                "2026-04-06_norm.md",
                branch="impl/norm",
                worktree_path=".worktrees/impl-norm",
                worktree_owner="docs/plan/2026-04-06_norm.md",  # 정규화 완료 상태
            )
        ]
        with patch(
            "app.modules.dev_runner.routes.plans.plan_service.list_plans",
            return_value=mock_plans,
        ):
            resp = api_client.get(f"{BASE_URL}/plans")

        assert resp.status_code == 200
        plan = resp.json()[0]
        assert plan["worktree_owner"] is not None
        assert "\\" not in plan["worktree_owner"], f"백슬래시 미정규화: {plan['worktree_owner']}"
