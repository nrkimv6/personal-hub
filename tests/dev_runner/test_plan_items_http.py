"""
TC: GET /plans/{encoded_path}/items — asyncio.to_thread 적용 검증 + 스키마 검증

수정 이력:
  2026-03-09: parse_plan_items()가 async def 라우트에서 asyncio.to_thread 없이
              동기 호출되어 이벤트루프를 블로킹하던 버그 수정 후 검증 TC 작성.
"""
import base64
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

pytestmark = pytest.mark.http

BASE_URL = "/api/v1/dev-runner"


def encode_path(path: str) -> str:
    return base64.urlsafe_b64encode(path.encode()).decode().rstrip("=")


def make_plan_detail(filename="test.md"):
    """PlanDetailResponse 호환 dict"""
    return {
        "path": f"D:/work/plan/{filename}",
        "filename": filename,
        "status": "구현중",
        "phases": [{
            "name": "Phase 1: 구현",
            "items": [
                {"level": 0, "text": "기능 구현", "checked": True, "children": [], "file_path": "app/main.py"},
                {"level": 0, "text": "테스트 작성", "checked": False, "children": [], "file_path": None},
            ],
            "done_count": 1,
            "total_count": 2,
        }],
        "progress": {"done": 1, "total": 2, "percent": 50},
        "summary": "테스트 요약",
    }


@pytest.fixture(scope="module")
def api_client():
    from app.main import app
    return TestClient(app)


class TestPlanItemsHTTP:
    """GET /plans/{encoded_path}/items 라우트 TC"""

    def test_right_returns_plan_detail_with_phases(self, api_client, tmp_path):
        """Right: 정상 plan 파일 → phases, progress 포함 응답"""
        plan_file = tmp_path / "test-plan.md"
        plan_file.write_text("## Phase 1\n- [x] done\n- [ ] todo\n", encoding="utf-8")
        encoded = encode_path(str(plan_file))

        with patch("app.modules.dev_runner.services.plan_service.plan_service.validate_path", return_value=True):
            with patch("app.modules.dev_runner.services.plan_service.plan_service.parse_plan_items",
                        return_value=make_plan_detail()):
                resp = api_client.get(f"{BASE_URL}/plans/{encoded}/items")

        assert resp.status_code == 200
        data = resp.json()
        assert "phases" in data
        assert "progress" in data
        assert data["progress"]["percent"] == 50

    def test_right_schema_has_required_fields(self, api_client, tmp_path):
        """Right: 응답에 path, filename, status, phases, progress 필드 존재"""
        plan_file = tmp_path / "schema-plan.md"
        plan_file.write_text("# Plan\n- [ ] item\n", encoding="utf-8")
        encoded = encode_path(str(plan_file))

        with patch("app.modules.dev_runner.services.plan_service.plan_service.validate_path", return_value=True):
            with patch("app.modules.dev_runner.services.plan_service.plan_service.parse_plan_items",
                        return_value=make_plan_detail("schema-plan.md")):
                resp = api_client.get(f"{BASE_URL}/plans/{encoded}/items")

        assert resp.status_code == 200
        data = resp.json()
        for key in ("path", "filename", "status", "phases", "progress"):
            assert key in data, f"필드 누락: {key}"

    def test_boundary_invalid_base64_returns_400(self, api_client):
        """Boundary: 잘못된 base64 인코딩 → 400"""
        resp = api_client.get(f"{BASE_URL}/plans/!!!invalid!!!/items")
        assert resp.status_code == 400

    def test_boundary_nonexistent_file_returns_404(self, api_client):
        """Boundary: 존재하지 않는 파일 경로 → 404"""
        encoded = encode_path("D:/nonexistent/plan.md")

        with patch("app.modules.dev_runner.services.plan_service.plan_service.validate_path", return_value=True):
            resp = api_client.get(f"{BASE_URL}/plans/{encoded}/items")

        assert resp.status_code == 404

    def test_boundary_forbidden_path_returns_403(self, api_client, tmp_path):
        """Boundary: 허용되지 않은 경로 → 403"""
        plan_file = tmp_path / "forbidden.md"
        plan_file.write_text("# Plan\n", encoding="utf-8")
        encoded = encode_path(str(plan_file))

        with patch("app.modules.dev_runner.services.plan_service.plan_service.validate_path", return_value=False):
            resp = api_client.get(f"{BASE_URL}/plans/{encoded}/items")

        assert resp.status_code == 403

    def test_correct_to_thread_used_in_source(self):
        """Correct: get_plan_items 라우트가 asyncio.to_thread를 사용하는지 소스 검증 (이벤트루프 비블로킹)"""
        import inspect
        from app.modules.dev_runner.routes.plans import get_plan_items

        source = inspect.getsource(get_plan_items)
        assert "to_thread" in source, (
            "get_plan_items에서 asyncio.to_thread를 사용하지 않음 — "
            "async def 라우트에서 동기 함수 직접 호출은 이벤트루프를 블로킹합니다"
        )

    def test_correct_pydantic_schema_validation(self):
        """Correct: PlanDetailResponse 스키마 생성 검증"""
        from app.modules.dev_runner.schemas import PlanDetailResponse

        detail = PlanDetailResponse(**make_plan_detail())
        assert detail.filename == "test.md"
        assert detail.progress.percent == 50
        assert len(detail.phases) == 1
        assert detail.phases[0].total_count == 2
