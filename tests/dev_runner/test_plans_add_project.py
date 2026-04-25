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

    cfg = dev_runner_config_isolation
    cfg.REGISTERED_PATHS_FILE = tmp_path / "registered_paths.json"
    cfg.IGNORED_PLANS_FILE = tmp_path / "ignored_plans.json"
    (tmp_path / "registered_paths.json").write_text("[]", encoding="utf-8")
    (tmp_path / "ignored_plans.json").write_text("[]", encoding="utf-8")

    return TestClient(app)


@pytest.fixture
def project_root(tmp_path):
    """docs/plan + docs/archive 디렉토리를 갖는 프로젝트 루트 (worktree 없음)"""
    (tmp_path / "docs" / "plan").mkdir(parents=True)
    (tmp_path / "docs" / "archive").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def project_root_dual(tmp_path):
    """docs/* + .worktrees/plans/docs/* 모두 갖는 프로젝트 루트 (4축)"""
    (tmp_path / "docs" / "plan").mkdir(parents=True)
    (tmp_path / "docs" / "archive").mkdir(parents=True)
    (tmp_path / ".worktrees" / "plans" / "docs" / "plan").mkdir(parents=True)
    (tmp_path / ".worktrees" / "plans" / "docs" / "archive").mkdir(parents=True)
    return tmp_path


class TestAddProjectRight:
    """Right: docs만 있을 때 2개, dual-path면 4개 등록"""

    def test_valid_project_returns_two_added(self, client, project_root):
        resp = client.post(f"{BASE}/plans/paths/project", json={"path": str(project_root)})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["added"]) == 2
        assert len(data["skipped"]) == 2  # worktree paths not found

    def test_added_contains_plan_and_archive(self, client, project_root):
        resp = client.post(f"{BASE}/plans/paths/project", json={"path": str(project_root)})
        added = " ".join(resp.json()["added"])
        assert "plan" in added
        assert "archive" in added

    def test_add_project_right_dual_path_returns_four_added(self, client, project_root_dual):
        """Right: docs/plan + docs/archive + worktree/plan + worktree/archive → added 4개"""
        resp = client.post(f"{BASE}/plans/paths/project", json={"path": str(project_root_dual)})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["added"]) == 4
        assert len(data["skipped"]) == 0


class TestAddProjectBoundary:
    """Boundary: 일부 이미 등록된 경우"""

    def test_add_project_boundary_only_worktree_returns_two_added(self, client, tmp_path):
        """Boundary: worktree 측만 존재 → added 2개, skipped 2개 (docs not found)"""
        (tmp_path / ".worktrees" / "plans" / "docs" / "plan").mkdir(parents=True)
        (tmp_path / ".worktrees" / "plans" / "docs" / "archive").mkdir(parents=True)
        resp = client.post(f"{BASE}/plans/paths/project", json={"path": str(tmp_path)})
        data = resp.json()
        assert len(data["added"]) == 2
        assert len(data["skipped"]) == 2
        assert all(".worktrees" in item for item in data["added"])

    def test_add_project_boundary_only_legacy_returns_two_added(self, client, project_root):
        """Boundary: docs/* 만 존재 → added 2개, skipped 2개 (worktree not found)"""
        resp = client.post(f"{BASE}/plans/paths/project", json={"path": str(project_root)})
        data = resp.json()
        assert len(data["added"]) == 2
        assert len(data["skipped"]) == 2

    def test_add_project_error_partial_already_registered(self, client, project_root_dual):
        """Error/duplicate: 일부 이미 등록된 상태에서 호출 시 added + skipped 합 = 4"""
        # plan 경로 하나 미리 등록
        plan_path = str(project_root_dual / "docs" / "plan")
        client.post(f"{BASE}/plans/paths", json={"path": plan_path, "path_type": "plan"})

        resp = client.post(f"{BASE}/plans/paths/project", json={"path": str(project_root_dual)})
        data = resp.json()
        assert len(data["added"]) + len(data["skipped"]) == 4
        assert len(data["added"]) == 3
        assert len(data["skipped"]) == 1

    def test_both_already_registered_all_skipped(self, client, project_root):
        plan_path = str(project_root / "docs" / "plan")
        archive_path = str(project_root / "docs" / "archive")
        client.post(f"{BASE}/plans/paths", json={"path": plan_path, "path_type": "plan"})
        client.post(f"{BASE}/plans/paths", json={"path": archive_path, "path_type": "archive"})

        resp = client.post(f"{BASE}/plans/paths/project", json={"path": str(project_root)})
        data = resp.json()
        # docs 2개 skipped + worktree 2개 not found skipped
        assert len(data["added"]) == 0
        assert len(data["skipped"]) == 4


class TestAddProjectInverse:
    """Inverse: 추가 전후 GET /plans/paths 경로 수 diff 확인"""

    def test_paths_count_increases_by_two(self, client, project_root):
        before = client.get(f"{BASE}/plans/paths").json()
        client.post(f"{BASE}/plans/paths/project", json={"path": str(project_root)})
        after = client.get(f"{BASE}/plans/paths").json()
        assert len(after) - len(before) == 2

    def test_paths_count_increases_by_four_for_dual(self, client, project_root_dual):
        before = client.get(f"{BASE}/plans/paths").json()
        client.post(f"{BASE}/plans/paths/project", json={"path": str(project_root_dual)})
        after = client.get(f"{BASE}/plans/paths").json()
        assert len(after) - len(before) == 4


class TestAddProjectError:
    """Error: 유효하지 않은 입력"""

    def test_empty_path_returns_error(self, client):
        resp = client.post(f"{BASE}/plans/paths/project", json={"path": ""})
        assert resp.status_code in (403, 404, 422)

    def test_not_allowed_path_returns_403(self, client):
        resp = client.post(f"{BASE}/plans/paths/project", json={"path": "/nonexistent/project/path"})
        assert resp.status_code == 403

    def test_allowed_but_nonexistent_returns_404(self, client, tmp_path):
        nonexistent = str(tmp_path / "does_not_exist")
        resp = client.post(f"{BASE}/plans/paths/project", json={"path": nonexistent})
        assert resp.status_code == 404


class TestAddProjectCrossCheck:
    """Cross-check: added + skipped == 4 (전체 후보 수)"""

    def test_added_plus_skipped_equals_four(self, client, project_root):
        resp = client.post(f"{BASE}/plans/paths/project", json={"path": str(project_root)})
        data = resp.json()
        assert len(data["added"]) + len(data["skipped"]) == 4

    def test_second_call_all_skipped_still_four(self, client, project_root):
        client.post(f"{BASE}/plans/paths/project", json={"path": str(project_root)})
        resp2 = client.post(f"{BASE}/plans/paths/project", json={"path": str(project_root)})
        data = resp2.json()
        assert len(data["added"]) + len(data["skipped"]) == 4


class TestAddProjectPlansWorktree:
    """plans worktree가 있으면 worktree 경로도 추가 등록 (dual-path contract)"""

    def test_prefers_plans_worktree_paths(self, client, tmp_path):
        """기존 TC 업데이트: dual-path 환경에서 4개 모두 등록"""
        project_root = tmp_path / "monitor-page"
        (project_root / ".worktrees" / "plans" / "docs" / "plan").mkdir(parents=True)
        (project_root / ".worktrees" / "plans" / "docs" / "archive").mkdir(parents=True)
        (project_root / "docs" / "plan").mkdir(parents=True)
        (project_root / "docs" / "archive").mkdir(parents=True)

        resp = client.post(f"{BASE}/plans/paths/project", json={"path": str(project_root)})
        assert resp.status_code == 200
        data = resp.json()

        assert any(".worktrees" in item for item in data["added"])
        assert len(data["added"]) == 4  # docs + worktree 모두 등록
        assert len(data["skipped"]) == 0
