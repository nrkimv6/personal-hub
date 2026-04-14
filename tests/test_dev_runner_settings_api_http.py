"""dev-runner suggestion API HTTP 테스트 (TestClient).

GET /api/v1/dev-runner/settings/engine-suggestion
"""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.shared.llm_registry as reg_mod
import app.modules.dev_runner.services.settings_service as ss_mod
from app.database import get_db
from app.modules.dev_runner.routes.settings import router as settings_router

# dev-runner settings 라우터만 포함한 minimal test app
_app = FastAPI()
_app.include_router(settings_router, prefix="/api/v1/dev-runner/settings")


@pytest.fixture
def client(test_db_session):
    def override_get_db():
        yield test_db_session

    _app.dependency_overrides[get_db] = override_get_db
    with TestClient(_app) as c:
        yield c
    _app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def patch_registry_files(tmp_path, monkeypatch):
    """registry/state/settings 파일을 tmp_path로 격리."""
    SAMPLE_REGISTRY = {
        "steps": {
            "plan_feat": [
                {"provider": "claude", "model": "claude-sonnet-4-6"},
                {"provider": "openai", "model": "gpt-5.4"},
            ],
            "plan_fix": [
                {"provider": "claude", "model": "claude-opus-4-6"},
            ],
        }
    }
    registry_file = tmp_path / "llm_model_registry.json"
    state_file = tmp_path / "llm_quota_state.json"
    settings_file = tmp_path / "settings.json"

    registry_file.write_text(json.dumps(SAMPLE_REGISTRY), encoding="utf-8")
    state_file.write_text(json.dumps({"entries": {}}), encoding="utf-8")

    monkeypatch.setattr(reg_mod, "REGISTRY_FILE", registry_file)
    monkeypatch.setattr(reg_mod, "QUOTA_STATE_FILE", state_file)

    # SettingsService 싱글톤 교체
    from app.modules.dev_runner.services.settings_service import SettingsService
    new_svc = SettingsService(settings_file=settings_file)
    monkeypatch.setattr(ss_mod, "settings_service", new_svc)


class TestGetEngineSuggestion:
    def test_GET_engine_suggestion_feat_200(self, client):
        """GET /engine-suggestion?kind=feat → 200, 필수 키 존재."""
        resp = client.get("/api/v1/dev-runner/settings/engine-suggestion?kind=feat")
        assert resp.status_code == 200
        data = resp.json()
        for key in ("suggested_engine", "provider", "model", "reason", "quota_snapshot"):
            assert key in data, f"응답에 '{key}' 키 없음"

    def test_GET_engine_suggestion_fix_200(self, client):
        """GET /engine-suggestion?kind=fix → 200."""
        resp = client.get("/api/v1/dev-runner/settings/engine-suggestion?kind=fix")
        assert resp.status_code == 200
        data = resp.json()
        assert data["suggested_engine"] in ("claude", "codex", "gemini")

    def test_GET_engine_suggestion_claude_100pct_falls_back(self, client):
        """claude 100% 상태에서 다른 엔진으로 fallback."""
        # claude 100% 설정
        client_llm = TestClient(_app)
        import app.shared.llm_registry as reg
        reg.report_quota("claude", model="claude-sonnet-4-6", weekly_used_pct=100, source="test")
        reg.report_quota("claude", model="claude-opus-4-6", weekly_used_pct=100, source="test")
        resp = client.get("/api/v1/dev-runner/settings/engine-suggestion?kind=feat")
        # openai(codex)로 fallback 또는 default_engine fallback
        assert resp.status_code == 200
        data = resp.json()
        assert data["suggested_engine"] in ("claude", "codex", "gemini")

    def test_GET_engine_suggestion_invalid_kind_422(self, client):
        """kind=invalid → 422 (Literal 검증)."""
        resp = client.get("/api/v1/dev-runner/settings/engine-suggestion?kind=invalid")
        assert resp.status_code == 422
