"""Plans API 스키마 테스트 (Phase 6 — path_type 필드 검증)

엔드포인트: /api/v1/plans/paths (GET/POST/DELETE)
plan_service를 직접 테스트 (HTTP 대신 서비스 레이어 테스트)
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
    cfg.ALLOWED_PATHS = [str(tmp_path)]

    return PlanService()


class TestAddPathWithTypeField:

    def test_add_path_with_type_field_archive(self, svc, tmp_path):
        """path_type='archive' → add_path에 type='archive'로 저장"""
        folder = tmp_path / "archive_test"
        folder.mkdir()

        result = svc.add_path(str(folder), path_type="archive")
        assert result is True

        # 저장된 항목에 type='archive'가 있어야 함
        matching = [e for e in svc._registered_paths if "archive_test" in e["path"]]
        assert len(matching) == 1
        assert matching[0]["type"] == "archive"

    def test_add_path_default_type(self, svc, tmp_path):
        """path_type 미지정 → 기본값 'plan' 저장"""
        folder = tmp_path / "plan_default"
        folder.mkdir()

        svc.add_path(str(folder))  # path_type 미지정

        matching = [e for e in svc._registered_paths if "plan_default" in e["path"]]
        assert len(matching) == 1
        assert matching[0]["type"] == "plan"

    def test_add_path_persisted_to_file(self, svc, tmp_path, dev_runner_config_isolation):
        """add_path 후 JSON 파일에 영속화 확인"""
        folder = tmp_path / "persist_test"
        folder.mkdir()

        svc.add_path(str(folder), path_type="archive")

        reg_file = dev_runner_config_isolation.REGISTERED_PATHS_FILE
        data = json.loads(reg_file.read_text(encoding="utf-8"))
        matching = [e for e in data if "persist_test" in e["path"]]
        assert len(matching) == 1
        assert matching[0]["type"] == "archive"

    def test_add_duplicate_path_returns_false(self, svc, tmp_path):
        """동일 경로 중복 등록 → False"""
        folder = tmp_path / "dup_test"
        folder.mkdir()

        assert svc.add_path(str(folder)) is True
        assert svc.add_path(str(folder), path_type="archive") is False  # 중복

    def test_add_path_canonicalizes_wtools_legacy_common_root(self, svc, tmp_path, dev_runner_config_isolation):
        """legacy wtools common/docs/plan 추가 요청은 canonical plans worktree root로 저장된다."""
        cfg = dev_runner_config_isolation
        cfg.WTOOLS_BASE_DIR = tmp_path / "wtools"
        legacy_common = cfg.WTOOLS_BASE_DIR / "common" / "docs" / "plan"
        canonical_worktree = cfg.WTOOLS_BASE_DIR / ".worktrees" / "plans" / "docs" / "plan"
        legacy_common.mkdir(parents=True)
        canonical_worktree.mkdir(parents=True)
        cfg.ALLOWED_PATHS = [str(tmp_path)]

        result = svc.add_path(str(legacy_common), path_type="plan")

        assert result is True
        matching = [e for e in svc._registered_paths if e["path"] == str(canonical_worktree.resolve())]
        assert len(matching) == 1
        assert all(e["path"] != str(legacy_common.resolve()) for e in svc._registered_paths)


class TestRemovePathObjectArray:

    def test_remove_path_object_array(self, svc, tmp_path):
        """객체 배열에서 path 매칭으로 삭제"""
        folder = tmp_path / "to_remove"
        folder.mkdir()

        svc.add_path(str(folder), path_type="plan")
        assert len([e for e in svc._registered_paths if "to_remove" in e["path"]]) == 1

        result = svc.remove_path(str(folder))
        assert result is True
        assert len([e for e in svc._registered_paths if "to_remove" in e["path"]]) == 0

    def test_remove_path_nonexistent(self, svc, tmp_path):
        """미등록 경로 제거 → False"""
        result = svc.remove_path(str(tmp_path / "nonexistent"))
        assert result is False


class TestListPathsIncludesType:

    def test_list_paths_includes_path_type(self, svc, tmp_path):
        """list_registered_paths() → path_type 필드 포함"""
        folder = tmp_path / "my_archive"
        folder.mkdir()
        svc.add_path(str(folder), path_type="archive")

        paths = svc.list_registered_paths()
        matching = [p for p in paths if "my_archive" in p.path]
        assert len(matching) == 1
        assert matching[0].path_type == "archive"

    def test_list_paths_default_type_is_plan(self, svc, tmp_path):
        """기본값 추가 → path_type='plan'"""
        folder = tmp_path / "default_type_test"
        folder.mkdir()
        svc.add_path(str(folder))  # 기본값

        paths = svc.list_registered_paths()
        matching = [p for p in paths if "default_type_test" in p.path]
        assert len(matching) == 1
        assert matching[0].path_type == "plan"

    def test_list_paths_mixed_types(self, svc, tmp_path):
        """plan + archive 혼합 등록 → 각각 올바른 path_type"""
        plan_dir = tmp_path / "plan_mix"
        archive_dir = tmp_path / "archive_mix"
        plan_dir.mkdir()
        archive_dir.mkdir()

        svc.add_path(str(plan_dir), path_type="plan")
        svc.add_path(str(archive_dir), path_type="archive")

        paths = svc.list_registered_paths()
        plan_entries = [p for p in paths if "plan_mix" in p.path]
        archive_entries = [p for p in paths if "archive_mix" in p.path]

        assert plan_entries[0].path_type == "plan"
        assert archive_entries[0].path_type == "archive"
