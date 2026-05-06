"""PlanPathRegistry JSON 저장 정책 테스트."""

import json

import pytest


@pytest.fixture
def registry(tmp_path, monkeypatch):
    import app.modules.dev_runner.services.plan_path_registry as registry_module

    reg_file = tmp_path / "registered_paths.json"
    ignored_file = tmp_path / "ignored_plans.json"
    reg_file.write_text("[]", encoding="utf-8")
    ignored_file.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(registry_module.config, "REGISTERED_PATHS_FILE", reg_file)
    monkeypatch.setattr(registry_module.config, "IGNORED_PLANS_FILE", ignored_file)

    return registry_module.PlanPathRegistry()


class TestPlanPathRegistryJsonStorage:

    def test_save_registered_paths_write_failure_keeps_file(
        self, registry, tmp_path, monkeypatch
    ):
        import app.modules.dev_runner.services.plan_path_registry as registry_module

        reg_file = registry_module.config.REGISTERED_PATHS_FILE
        before = [{"path": str(tmp_path / "existing"), "type": "plan"}]
        reg_file.write_text(json.dumps(before), encoding="utf-8")
        registry._registered_paths.append({"path": str(tmp_path / "new"), "type": "plan"})

        def fail_write(path, payload):
            raise OSError("disk full")

        monkeypatch.setattr(registry_module, "write_json_atomic", fail_write)

        with pytest.raises(OSError):
            registry._save_registered_paths()

        assert json.loads(reg_file.read_text(encoding="utf-8")) == before

    def test_save_ignored_plans_write_failure_keeps_file(
        self, registry, tmp_path, monkeypatch
    ):
        import app.modules.dev_runner.services.plan_path_registry as registry_module

        ignored_file = registry_module.config.IGNORED_PLANS_FILE
        before = [str(tmp_path / "old.md")]
        ignored_file.write_text(json.dumps(before), encoding="utf-8")
        registry._ignored_plans.append(str(tmp_path / "new.md"))

        def fail_write(path, payload):
            raise OSError("disk full")

        monkeypatch.setattr(registry_module, "write_json_atomic", fail_write)

        with pytest.raises(OSError):
            registry._save_ignored_plans()

        assert json.loads(ignored_file.read_text(encoding="utf-8")) == before
