"""app/shared/tests conftest — registry/state 파일 monkeypatch fixture."""
import json
from pathlib import Path

import pytest

import app.shared.llm_registry as llm_registry_module

SAMPLE_REGISTRY = {
    "steps": {
        "plan_feat": [
            {"provider": "claude", "model": "claude-sonnet-4-6"},
            {"provider": "openai", "model": "gpt-5.4"},
            {"provider": "gemini", "model": "gemini-3.1-pro", "oneshot": True},
        ],
        "plan_fix": [
            {"provider": "claude", "model": "claude-opus-4-6"},
        ],
        "status_tracking": [
            {"provider": "claude", "model": "claude-haiku-4-5"},
            {"provider": "gemini", "model": "gemini-3-flash"},
        ],
    }
}


@pytest.fixture
def tmp_registry_state(tmp_path, monkeypatch):
    """REGISTRY_FILE / QUOTA_STATE_FILE을 tmp_path로 monkeypatch."""
    registry_file = tmp_path / "llm_model_registry.json"
    state_file = tmp_path / "llm_quota_state.json"

    registry_file.write_text(json.dumps(SAMPLE_REGISTRY), encoding="utf-8")
    state_file.write_text(json.dumps({"entries": {}}), encoding="utf-8")

    monkeypatch.setattr(llm_registry_module, "REGISTRY_FILE", registry_file)
    monkeypatch.setattr(llm_registry_module, "QUOTA_STATE_FILE", state_file)

    return registry_file, state_file
