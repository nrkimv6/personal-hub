"""sync_plans() 단위 테스트 — archive 스캔 제거 검증

대상 함수: PlanService.sync_plans()
수정 내용: include_ignored=True → False (archive 경로 스캔 제거)
"""
import json
import pytest
from pathlib import Path


@pytest.fixture
def svc(tmp_path, dev_runner_config_isolation):
    """격리된 PlanService 인스턴스"""
    from app.modules.dev_runner.services.plan_service import PlanService

    cfg = dev_runner_config_isolation
    cfg.REGISTERED_PATHS_FILE = tmp_path / "registered_paths.json"
    cfg.IGNORED_PLANS_FILE = tmp_path / "ignored_plans.json"
    (tmp_path / "registered_paths.json").write_text("[]", encoding="utf-8")
    (tmp_path / "ignored_plans.json").write_text("[]", encoding="utf-8")

    return PlanService()


def _make_plan(plan_dir: Path, filename: str, status: str = "구현중", done: int = 0, total: int = 5) -> Path:
    """테스트용 plan .md 파일 생성"""
    progress_line = f"> 진행률: {done}/{total} ({int(done/total*100) if total else 0}%)\n"
    content = (
        f"# Test Plan {filename}\n\n"
        f"> 상태: {status}\n"
        f"{progress_line}"
        f"\n## TODO\n\n"
        + "\n".join([f"- {'[x]' if i < done else '[ ]'} 작업{i}" for i in range(total)])
        + "\n"
    )
    p = plan_dir / filename
    p.write_text(content, encoding="utf-8")
    return p


def _register_path(reg_file: Path, path: str, path_type: str = "folder"):
    """registered_paths.json에 경로 추가"""
    paths = json.loads(reg_file.read_text(encoding="utf-8"))
    paths.append({"path": path, "type": path_type})
    reg_file.write_text(json.dumps(paths), encoding="utf-8")


# ---------------------------------------------------------------------------
# Phase T1: RIGHT-BICEP TC
# ---------------------------------------------------------------------------

class TestSyncPlansRight:

    def test_sync_plans_right_excludes_archive(self, svc, tmp_path, dev_runner_config_isolation):
        """R(정상): plan_dir 2개 + archive_dir 3개 → synced 수가 plan만 포함"""
        cfg = dev_runner_config_isolation
        plan_dir = tmp_path / "docs" / "plan"
        archive_dir = tmp_path / "docs" / "archive"
        plan_dir.mkdir(parents=True)
        archive_dir.mkdir(parents=True)

        _make_plan(plan_dir, "2026-01-01_plan-a.md")
        _make_plan(plan_dir, "2026-01-02_plan-b.md")
        _make_plan(archive_dir, "2026-01-01_done-a.md", status="완료", done=5)
        _make_plan(archive_dir, "2026-01-02_done-b.md", status="완료", done=3)
        _make_plan(archive_dir, "2026-01-03_done-c.md", status="구현완료", done=5)

        _register_path(cfg.REGISTERED_PATHS_FILE, str(plan_dir), "folder")
        _register_path(cfg.REGISTERED_PATHS_FILE, str(archive_dir), "archive")
        svc._load_registered_paths()

        result = svc.sync_plans()

        # archive 3개는 포함되지 않아야 함
        assert result["synced"] == 2, f"expected 2, got {result['synced']}"
        assert result["added"] == 0
        assert result["removed"] == 0
        assert result["updated"] == 0

    def test_sync_plans_right_detects_added_plan(self, svc, tmp_path, dev_runner_config_isolation):
        """R(정상): sync 후 plan 추가 → 재 sync에서 added=1"""
        cfg = dev_runner_config_isolation
        plan_dir = tmp_path / "docs" / "plan"
        plan_dir.mkdir(parents=True)

        _make_plan(plan_dir, "2026-01-01_plan-a.md")
        _register_path(cfg.REGISTERED_PATHS_FILE, str(plan_dir), "folder")
        svc._load_registered_paths()

        # 첫 번째 sync
        svc.sync_plans()

        # plan 추가 후 두 번째 sync
        _make_plan(plan_dir, "2026-01-02_plan-b.md")
        result = svc.sync_plans()

        assert result["added"] == 1
        assert result["synced"] == 2

    def test_sync_plans_right_detects_updated_status(self, svc, tmp_path, dev_runner_config_isolation):
        """R(정상): plan 파일 상태 변경 후 sync → updated=1"""
        cfg = dev_runner_config_isolation
        plan_dir = tmp_path / "docs" / "plan"
        plan_dir.mkdir(parents=True)

        plan_file = _make_plan(plan_dir, "2026-01-01_plan-a.md", status="구현중", done=0)
        _register_path(cfg.REGISTERED_PATHS_FILE, str(plan_dir), "folder")
        svc._load_registered_paths()

        # 첫 번째 sync (캐시에 저장됨)
        svc.sync_plans()

        # 파일 상태 변경 (보류는 ignored로 처리되므로 초안으로 변경)
        content = plan_file.read_text(encoding="utf-8")
        plan_file.write_text(content.replace("> 상태: 구현중", "> 상태: 초안"), encoding="utf-8")

        result = svc.sync_plans()
        assert result["updated"] == 1


class TestSyncPlansBoundary:

    def test_sync_plans_boundary_empty_plan_dir(self, svc, tmp_path, dev_runner_config_isolation):
        """B(경계): 등록 경로에 .md 파일 없음 → synced=0"""
        cfg = dev_runner_config_isolation
        plan_dir = tmp_path / "docs" / "plan"
        plan_dir.mkdir(parents=True)

        _register_path(cfg.REGISTERED_PATHS_FILE, str(plan_dir), "folder")
        svc._load_registered_paths()

        result = svc.sync_plans()

        assert result == {"synced": 0, "added": 0, "removed": 0, "updated": 0}


class TestSyncPlansError:

    def test_sync_plans_error_nonexistent_path(self, svc, tmp_path, dev_runner_config_isolation):
        """E(에러): 존재하지 않는 경로 등록 → 에러 없이 synced=0 반환"""
        cfg = dev_runner_config_isolation
        nonexistent = tmp_path / "no_such_dir"
        _register_path(cfg.REGISTERED_PATHS_FILE, str(nonexistent), "folder")
        svc._load_registered_paths()

        result = svc.sync_plans()

        assert result["synced"] == 0


# ---------------------------------------------------------------------------
# Phase T3: 통합 TC (실제 파일시스템, mock 없음)
# ---------------------------------------------------------------------------

class TestSyncPlansIntegration:

    def test_sync_plans_integration_real_filesystem(self, svc, tmp_path, dev_runner_config_isolation):
        """통합: 실제 tmp 파일시스템으로 archive 미포함 검증"""
        cfg = dev_runner_config_isolation
        plan_dir = tmp_path / "docs" / "plan"
        archive_dir = tmp_path / "docs" / "archive"
        plan_dir.mkdir(parents=True)
        archive_dir.mkdir(parents=True)

        # plan 2개, archive 5개
        for i in range(2):
            _make_plan(plan_dir, f"2026-01-0{i+1}_plan.md")
        for i in range(5):
            _make_plan(archive_dir, f"2026-01-0{i+1}_done.md", status="완료", done=5)

        _register_path(cfg.REGISTERED_PATHS_FILE, str(plan_dir), "folder")
        _register_path(cfg.REGISTERED_PATHS_FILE, str(archive_dir), "archive")
        svc._load_registered_paths()

        result = svc.sync_plans()

        # archive 5개는 synced에 포함되지 않아야 함
        assert result["synced"] == 2
        # archive 수(5) < total scanned 이어야 함 (이전처럼 7이 아님)
        assert result["synced"] < 7


# ---------------------------------------------------------------------------
# Phase T5: HTTP 통합 테스트
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def api_client():
    from app.main import app
    from fastapi.testclient import TestClient
    return TestClient(app)


class TestSyncPlansHTTP:
    """POST /api/v1/dev-runner/plans/sync HTTP 통합 테스트"""

    pytestmark = pytest.mark.http

    def test_http_post_sync_plans_response_structure(self, api_client):
        """T5: POST /plans/sync → 200 응답, 필수 키 존재 확인"""
        resp = api_client.post("/api/v1/dev-runner/plans/sync")
        assert resp.status_code == 200
        data = resp.json()
        assert "synced" in data
        assert "added" in data
        assert "removed" in data
        assert "updated" in data
        assert isinstance(data["synced"], int)

    def test_http_post_sync_plans_excludes_archive_count(self, api_client):
        """T5: POST /plans/sync → synced 값이 GET /plans 활성 count와 일치 (archive 미포함)"""
        # GET /plans 로 활성 plan 수 확인
        get_resp = api_client.get("/api/v1/dev-runner/plans")
        assert get_resp.status_code == 200
        active_count = len(get_resp.json())

        # sync 실행
        sync_resp = api_client.post("/api/v1/dev-runner/plans/sync")
        assert sync_resp.status_code == 200
        synced_count = sync_resp.json()["synced"]

        # synced는 활성 plan 수와 같아야 함 (archive 포함 시 훨씬 클 것)
        assert synced_count == active_count
