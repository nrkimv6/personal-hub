"""PlanService registered_paths path_type 관련 테스트 (Phase 5 추가분)

대상 소스: app/modules/dev_runner/services/plan_service.py
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


class TestLoadRegisteredPathsObjectArray:

    def test_load_registered_paths_object_array(self, tmp_path, dev_runner_config_isolation):
        """객체 배열 JSON 로드 정상 동작"""
        from app.modules.dev_runner.services.plan_service import PlanService

        cfg = dev_runner_config_isolation
        reg_file = tmp_path / "registered_paths.json"
        ign_file = tmp_path / "ignored_plans.json"

        data = [
            {"path": "/some/plan/dir", "type": "plan"},
            {"path": "/some/archive/dir", "type": "archive"},
        ]
        reg_file.write_text(json.dumps(data), encoding="utf-8")
        ign_file.write_text("[]", encoding="utf-8")

        cfg.REGISTERED_PATHS_FILE = reg_file
        cfg.IGNORED_PLANS_FILE = ign_file

        svc = PlanService()

        assert len(svc._registered_paths) == 2
        assert svc._registered_paths[0]["path"] == "/some/plan/dir"
        assert svc._registered_paths[0]["type"] == "plan"
        assert svc._registered_paths[1]["type"] == "archive"


class TestAddPathWithType:

    def test_add_path_with_type_archive(self, svc, tmp_path):
        """path_type='archive' → type 포함 저장"""
        folder = tmp_path / "archive_dir"
        folder.mkdir()

        result = svc.add_path(str(folder), path_type="archive")

        assert result is True
        entry = next(e for e in svc._registered_paths if folder.resolve().parts[-1] in e["path"])
        assert entry["type"] == "archive"

    def test_add_path_default_type(self, svc, tmp_path):
        """type 미지정 → 'plan' 기본값 저장"""
        folder = tmp_path / "plan_dir"
        folder.mkdir()

        svc.add_path(str(folder))  # type 미지정

        entry = next(e for e in svc._registered_paths if folder.resolve().parts[-1] in e["path"])
        assert entry["type"] == "plan"

    def test_add_path_duplicate_not_added(self, svc, tmp_path):
        """동일 경로 중복 추가 → False 반환"""
        folder = tmp_path / "dup_dir"
        folder.mkdir()

        assert svc.add_path(str(folder)) is True
        assert svc.add_path(str(folder)) is False


class TestRemovePathObjectArray:

    def test_remove_path_object_array(self, svc, tmp_path):
        """객체 배열에서 path 매칭 삭제"""
        folder = tmp_path / "to_remove"
        folder.mkdir()

        svc.add_path(str(folder), path_type="plan")
        assert len([e for e in svc._registered_paths if folder.resolve().parts[-1] in e["path"]]) == 1

        result = svc.remove_path(str(folder))
        assert result is True
        assert len([e for e in svc._registered_paths if folder.resolve().parts[-1] in e["path"]]) == 0

    def test_remove_path_nonexistent(self, svc, tmp_path):
        """등록되지 않은 경로 제거 → False"""
        result = svc.remove_path(str(tmp_path / "nonexistent"))
        assert result is False


class TestListRegisteredPaths:

    def test_list_plans_with_path_type_plan(self, svc, tmp_path):
        """path_type='plan'인 경로 등록 → list_registered_paths()에서 path_type='plan'"""
        folder = tmp_path / "plan_folder"
        folder.mkdir()
        (folder / "2026-01-01-test.md").write_text("> 상태: 대기\n\n1. [ ] task", encoding="utf-8")

        svc.add_path(str(folder), path_type="plan")

        paths = svc.list_registered_paths()
        matching = [p for p in paths if "plan_folder" in p.path]
        assert len(matching) == 1
        assert matching[0].path_type == "plan"

    def test_list_plans_with_path_type_archive(self, svc, tmp_path):
        """path_type='archive'인 경로 등록 → list_registered_paths()에서 path_type='archive'"""
        folder = tmp_path / "archive_folder"
        folder.mkdir()

        svc.add_path(str(folder), path_type="archive")

        paths = svc.list_registered_paths()
        matching = [p for p in paths if "archive_folder" in p.path]
        assert len(matching) == 1
        assert matching[0].path_type == "archive"

    def test_list_registered_paths_includes_plan_count(self, svc, tmp_path):
        """plan_count 필드 포함 확인"""
        folder = tmp_path / "counted_folder"
        folder.mkdir()
        (folder / "plan1.md").write_text("# Plan 1", encoding="utf-8")
        (folder / "plan2.md").write_text("# Plan 2", encoding="utf-8")

        svc.add_path(str(folder))

        paths = svc.list_registered_paths()
        matching = [p for p in paths if "counted_folder" in p.path]
        assert len(matching) == 1
        assert matching[0].plan_count == 2


class TestJsonStorageAtomicWrite:

    def test_plan_service_registered_paths_write_failure_keeps_file(
        self, tmp_path, dev_runner_config_isolation, monkeypatch
    ):
        """registered_paths 저장 실패 시 기존 JSON을 유지한다."""
        import app.modules.dev_runner.services.plan_service as plan_service_module
        from app.modules.dev_runner.services.plan_service import PlanService

        cfg = dev_runner_config_isolation
        reg_file = tmp_path / "registered_paths.json"
        ign_file = tmp_path / "ignored_plans.json"
        before = [{"path": str(tmp_path / "existing"), "type": "plan"}]
        reg_file.write_text(json.dumps(before), encoding="utf-8")
        ign_file.write_text("[]", encoding="utf-8")
        cfg.REGISTERED_PATHS_FILE = reg_file
        cfg.IGNORED_PLANS_FILE = ign_file

        svc = PlanService()
        svc._registered_paths.append({"path": str(tmp_path / "new"), "type": "plan"})

        def fail_write(path, payload):
            raise OSError("disk full")

        monkeypatch.setattr(plan_service_module, "write_json_atomic", fail_write)

        with pytest.raises(OSError):
            svc._save_registered_paths()

        assert json.loads(reg_file.read_text(encoding="utf-8")) == before

    def test_plan_path_registry_ignored_plans_write_failure_keeps_file(
        self, tmp_path, dev_runner_config_isolation, monkeypatch
    ):
        """ignored_plans 저장 실패 시 기존 JSON을 유지한다."""
        import app.modules.dev_runner.services.plan_path_registry as registry_module

        cfg = dev_runner_config_isolation
        reg_file = tmp_path / "registered_paths.json"
        ign_file = tmp_path / "ignored_plans.json"
        before = [str(tmp_path / "old.md")]
        reg_file.write_text("[]", encoding="utf-8")
        ign_file.write_text(json.dumps(before), encoding="utf-8")
        cfg.REGISTERED_PATHS_FILE = reg_file
        cfg.IGNORED_PLANS_FILE = ign_file

        registry = registry_module.PlanPathRegistry()
        registry._ignored_plans.append(str(tmp_path / "new.md"))

        def fail_write(path, payload):
            raise OSError("disk full")

        monkeypatch.setattr(registry_module, "write_json_atomic", fail_write)

        with pytest.raises(OSError):
            registry._save_ignored_plans()

        assert json.loads(ign_file.read_text(encoding="utf-8")) == before
