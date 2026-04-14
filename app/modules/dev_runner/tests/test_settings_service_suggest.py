"""dev-runner suggest_engine 단위 TC."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

import app.shared.llm_registry as reg_mod
from app.modules.dev_runner.services.settings_service import SettingsService
from app.shared.llm_registry import NoAvailableModelError

SAMPLE_REGISTRY = {
    "steps": {
        "plan_feat": [
            {"provider": "claude", "model": "claude-sonnet-4-6"},
            {"provider": "openai", "model": "gpt-5.4"},
        ],
        "plan_fix": [
            {"provider": "gemini", "model": "gemini-3-flash"},
        ],
    }
}


@pytest.fixture
def tmp_reg_state(tmp_path, monkeypatch):
    registry_file = tmp_path / "reg.json"
    state_file = tmp_path / "state.json"
    registry_file.write_text(json.dumps(SAMPLE_REGISTRY), encoding="utf-8")
    state_file.write_text(json.dumps({"entries": {}}), encoding="utf-8")
    monkeypatch.setattr(reg_mod, "REGISTRY_FILE", registry_file)
    monkeypatch.setattr(reg_mod, "QUOTA_STATE_FILE", state_file)
    return registry_file, state_file


@pytest.fixture
def svc(tmp_path, tmp_reg_state):
    return SettingsService(settings_file=tmp_path / "settings.json")


class TestSuggestEngine:
    def test_suggest_engine_R_feat_maps_to_claude_engine(self, svc, tmp_reg_state):
        """R: claude picker 결과 → suggested_engine='claude'."""
        result = svc.suggest_engine("feat")
        assert result["suggested_engine"] == "claude"
        assert result["provider"] == "claude"
        assert "quota_snapshot" in result

    def test_suggest_engine_R_openai_allowed_maps_to_codex(self, svc, tmp_reg_state, monkeypatch):
        """R(O-2): openai 반환 시 'codex' 매핑."""
        import app.modules.dev_runner.services.settings_service as svc_mod
        monkeypatch.setattr(svc_mod, "pick_model", lambda step, **kw: ("openai", "gpt-5.4"))
        result = svc.suggest_engine("feat")
        assert result["suggested_engine"] == "codex"
        assert result["provider"] == "openai"

    def test_suggest_engine_E_no_available_returns_default_engine(self, svc, tmp_reg_state, monkeypatch):
        """E: NoAvailableModelError → default_engine fallback."""
        import app.modules.dev_runner.services.settings_service as svc_mod
        def _raise(*a, **kw):
            raise NoAvailableModelError("plan_feat")
        monkeypatch.setattr(svc_mod, "pick_model", _raise)
        result = svc.suggest_engine("feat")
        # fallback: settings_service.get().default_engine = "claude"
        assert result["suggested_engine"] == "claude"
        assert "NoAvailable" in result["reason"]

    def test_suggest_engine_E_unknown_provider_raises(self, svc, tmp_reg_state, monkeypatch):
        """E: 매핑 불가 provider → ValueError."""
        import app.modules.dev_runner.services.settings_service as svc_mod
        monkeypatch.setattr(svc_mod, "pick_model", lambda step, **kw: ("unknown_llm", "some-model"))
        with pytest.raises(ValueError, match="engine 매핑"):
            svc.suggest_engine("feat")
