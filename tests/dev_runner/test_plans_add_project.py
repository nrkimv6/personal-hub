"""POST /plans/paths/project Right-BICEP TC

대상: app/modules/dev_runner/routes/plans.py → add_project()
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock


BASE = "/api/v1/dev-runner"


@pytest.fixture
def client(tmp_path, dev_runner_config_isolation):
    """격리된 TestClient — plan_service를 tmp 경로로 격리"""
    from app.main import app
    from app.modules.dev_runner.services.plan_service import PlanService

    cfg = dev_runner_config_isolation
    cfg.REGISTERED_PATHS_FILE = tmp_path / "registered_paths.json"
    cfg.IGNORED_PLANS_FILE = tmp_path / "ignored_plans.json"
    (tmp_path / "registered_paths.json").write_text("[]", encoding="utf-8")
    (tmp_path / "ignored_plans.json").write_text("[]", encoding="utf-8")

    return TestClient(app)


@pytest.fixture
def project_root(tmp_path):
    """docs/plan + docs/archive 디렉토리를 갖는 프로젝트 루트"""
    plan_dir = tmp_path / "docs" / "plan"
    archive_dir = tmp_path / "docs" / "archive"
    plan_dir.mkdir(parents=True)
    archive_dir.mkdir(parents=True)
    return tmp_path


class TestAddProjectRight:
    """Right: 정상 경로 → added 2개, skipped 0개"""

    def test_valid_project_returns_two_added(self, client, project_root):
        resp = client.post(f"{BASE}/plans/paths/project", json={"path": str(project_root)})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["added"]) == 2
        assert len(data["skipped"]) == 0

    def test_added_contains_plan_and_archive(self, client, project_root):
        resp = client.post(f"{BASE}/plans/paths/project", json={"path": str(project_root)})
        added = " ".join(resp.json()["added"])
        assert "plan" in added
        assert "archive" in added


class TestAddProjectBoundary:
    """Boundary: 일부 이미 등록된 경우"""

    def test_plan_already_registered_skipped(self, client, project_root):
        # plan 경로 먼저 등록
        plan_path = str(project_root / "docs" / "plan")
        client.post(f"{BASE}/plans/paths", json={"path": plan_path, "path_type": "plan"})

        resp = client.post(f"{BASE}/plans/paths/project", json={"path": str(project_root)})
        data = resp.json()
        assert len(data["added"]) == 1      # archive만 추가
        assert len(data["skipped"]) == 1    # plan은 skipped

    def test_both_already_registered_all_skipped(self, client, project_root):
        plan_path = str(project_root / "docs" / "plan")
        archive_path = str(project_root / "docs" / "archive")
        client.post(f"{BASE}/plans/paths", json={"path": plan_path, "path_type": "plan"})
        client.post(f"{BASE}/plans/paths", json={"path": archive_path, "path_type": "archive"})

        resp = client.post(f"{BASE}/plans/paths/project", json={"path": str(project_root)})
        data = resp.json()
        assert len(data["added"]) == 0
        assert len(data["skipped"]) == 2


class TestAddProjectInverse:
    """Inverse: 추가 전후 GET /plans/paths 경로 수 diff 확인"""

    def test_paths_count_increases_by_two(self, client, project_root):
        before = client.get(f"{BASE}/plans/paths").json()
        client.post(f"{BASE}/plans/paths/project", json={"path": str(project_root)})
        after = client.get(f"{BASE}/plans/paths").json()
        assert len(after) - len(before) == 2


class TestAddProjectError:
    """Error: 유효하지 않은 입력"""

    def test_empty_path_returns_error(self, client):
        # 빈 경로 → validate_path 실패 → 403 또는 404
        resp = client.post(f"{BASE}/plans/paths/project", json={"path": ""})
        assert resp.status_code in (403, 404, 422)

    def test_not_allowed_path_returns_403(self, client):
        # ALLOWED_PATHS 밖의 경로 → 403 Forbidden
        resp = client.post(f"{BASE}/plans/paths/project", json={"path": "/nonexistent/project/path"})
        assert resp.status_code == 403

    def test_allowed_but_nonexistent_returns_404(self, client, tmp_path):
        # 허용 경로(tmp_path 하위)이지만 실제로 존재하지 않는 경로 → 404
        nonexistent = str(tmp_path / "does_not_exist")
        resp = client.post(f"{BASE}/plans/paths/project", json={"path": nonexistent})
        assert resp.status_code == 404


class TestAddProjectCrossCheck:
    """Cross-check: added + skipped == 등록 대상 수 (plan + archive = 2)"""

    def test_added_plus_skipped_equals_two(self, client, project_root):
        resp = client.post(f"{BASE}/plans/paths/project", json={"path": str(project_root)})
        data = resp.json()
        assert len(data["added"]) + len(data["skipped"]) == 2

    def test_second_call_all_skipped_still_two(self, client, project_root):
        client.post(f"{BASE}/plans/paths/project", json={"path": str(project_root)})
        resp2 = client.post(f"{BASE}/plans/paths/project", json={"path": str(project_root)})
        data = resp2.json()
        assert len(data["added"]) + len(data["skipped"]) == 2
