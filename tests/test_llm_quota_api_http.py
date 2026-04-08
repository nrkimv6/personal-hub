"""LLM Quota Admin API HTTP 테스트 (TestClient).

GET /api/v1/llm/quota, POST /api/v1/llm/quota/report, POST /api/v1/llm/quota/clear
"""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.shared.llm_registry as reg_mod
from app.database import get_db
from app.modules.claude_worker.routes.llm_routes import router as llm_router

# LLM 라우터만 포함한 minimal test app
_app = FastAPI()
_app.include_router(llm_router)


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
    """registry/state 파일을 tmp_path로 격리."""
    SAMPLE_REGISTRY = {
        "steps": {
            "plan_expand": [
                {"provider": "claude", "model": "claude-opus-4-6"},
            ],
            "status_tracking": [
                {"provider": "claude", "model": "claude-haiku-4-5"},
                {"provider": "gemini", "model": "gemini-3-flash"},
            ],
        }
    }
    registry_file = tmp_path / "llm_model_registry.json"
    state_file = tmp_path / "llm_quota_state.json"
    registry_file.write_text(json.dumps(SAMPLE_REGISTRY), encoding="utf-8")
    state_file.write_text(json.dumps({"entries": {}}), encoding="utf-8")
    monkeypatch.setattr(reg_mod, "REGISTRY_FILE", registry_file)
    monkeypatch.setattr(reg_mod, "QUOTA_STATE_FILE", state_file)


class TestGetQuota:
    def test_GET_quota_200_snapshot_structure(self, client):
        """GET /quota → 200, entries/picker_by_step 키 존재."""
        resp = client.get("/api/v1/llm/quota")
        assert resp.status_code == 200
        data = resp.json()
        assert "entries" in data
        assert "picker_by_step" in data

    def test_GET_quota_picker_by_step_has_registered_steps(self, client):
        """GET /quota → picker_by_step에 registry 등록 step 포함."""
        resp = client.get("/api/v1/llm/quota")
        assert resp.status_code == 200
        picker = resp.json()["picker_by_step"]
        assert "plan_expand" in picker
        assert "status_tracking" in picker


class TestPostQuotaReport:
    def test_POST_quota_report_absolute_value_persists(self, client):
        """POST /quota/report absolute → GET으로 재확인."""
        resp = client.post("/api/v1/llm/quota/report", json={
            "provider": "claude",
            "model": "claude-opus-4-6",
            "weekly_used_pct": 50,
        })
        assert resp.status_code == 200

        get = client.get("/api/v1/llm/quota")
        entries = get.json()["entries"]
        assert "claude/claude-opus-4-6" in entries
        assert entries["claude/claude-opus-4-6"]["weekly_used_pct"] == 50.0

    def test_POST_quota_report_delta_adds_to_current(self, client):
        """delta +15 → 현재+15."""
        client.post("/api/v1/llm/quota/report", json={
            "provider": "claude", "model": "claude-opus-4-6", "weekly_used_pct": 30
        })
        resp = client.post("/api/v1/llm/quota/report", json={
            "provider": "claude", "model": "claude-opus-4-6", "delta_weekly_pct": 15
        })
        assert resp.status_code == 200
        entries = client.get("/api/v1/llm/quota").json()["entries"]
        assert entries["claude/claude-opus-4-6"]["weekly_used_pct"] == 45.0

    def test_POST_quota_report_delta_clamped_at_100(self, client):
        """delta 100 초과 → 100 clamp."""
        client.post("/api/v1/llm/quota/report", json={
            "provider": "claude", "model": "claude-opus-4-6", "weekly_used_pct": 95
        })
        resp = client.post("/api/v1/llm/quota/report", json={
            "provider": "claude", "model": "claude-opus-4-6", "delta_weekly_pct": 20
        })
        assert resp.status_code == 200
        entries = client.get("/api/v1/llm/quota").json()["entries"]
        assert entries["claude/claude-opus-4-6"]["weekly_used_pct"] == 100.0

    def test_POST_quota_report_omit_model_propagates_claude_group(self, client):
        """provider=claude, model 생략 → claude/* 동기화."""
        client.post("/api/v1/llm/quota/report", json={
            "provider": "claude", "model": "claude-opus-4-6", "weekly_used_pct": 30
        })
        client.post("/api/v1/llm/quota/report", json={
            "provider": "claude", "model": "claude-haiku-4-5", "weekly_used_pct": 10
        })
        resp = client.post("/api/v1/llm/quota/report", json={
            "provider": "claude", "weekly_used_pct": 75
        })
        assert resp.status_code == 200
        entries = client.get("/api/v1/llm/quota").json()["entries"]
        for key in ["claude/claude-opus-4-6", "claude/claude-haiku-4-5"]:
            if key in entries:
                assert entries[key]["weekly_used_pct"] == 75.0

    def test_POST_quota_report_gemini_pro_not_affect_flash(self, client):
        """Pro 설정 → Flash 무영향."""
        client.post("/api/v1/llm/quota/report", json={
            "provider": "gemini", "model": "gemini-3-flash", "weekly_used_pct": 10
        })
        client.post("/api/v1/llm/quota/report", json={
            "provider": "gemini", "model": "gemini-3.1-pro", "weekly_used_pct": 90
        })
        entries = client.get("/api/v1/llm/quota").json()["entries"]
        assert entries["gemini/gemini-3-flash"]["weekly_used_pct"] == 10.0
        assert entries["gemini/gemini-3.1-pro"]["weekly_used_pct"] == 90.0

    def test_POST_quota_report_both_fields_returns_400(self, client):
        """weekly_used_pct + delta 동시 → 400."""
        resp = client.post("/api/v1/llm/quota/report", json={
            "provider": "claude", "model": "claude-opus-4-6",
            "weekly_used_pct": 50, "delta_weekly_pct": 10
        })
        assert resp.status_code == 400

    def test_POST_quota_report_invalid_provider_returns_400(self, client):
        """존재하지 않는 provider → 400."""
        resp = client.post("/api/v1/llm/quota/report", json={
            "provider": "unknown_llm", "weekly_used_pct": 50
        })
        assert resp.status_code == 400


class TestPostQuotaClear:
    def test_POST_quota_clear_resets_entries(self, client):
        """clear → 해당 항목 삭제(=0%) 또는 0%로 리셋."""
        client.post("/api/v1/llm/quota/report", json={
            "provider": "claude", "model": "claude-opus-4-6", "weekly_used_pct": 80
        })
        # 80%로 설정됐는지 확인
        entries_before = client.get("/api/v1/llm/quota").json()["entries"]
        assert entries_before.get("claude/claude-opus-4-6", {}).get("weekly_used_pct", 0) == 80.0

        resp = client.post("/api/v1/llm/quota/clear", json={
            "provider": "claude", "model": "claude-opus-4-6"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True

        entries_after = client.get("/api/v1/llm/quota").json()["entries"]
        # clear는 entry 삭제(=암묵적 0%) 또는 0%로 설정
        entry = entries_after.get("claude/claude-opus-4-6")
        pct_after = entry["weekly_used_pct"] if entry else 0.0
        assert pct_after == 0.0
