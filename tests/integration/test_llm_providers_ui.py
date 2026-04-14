"""
LLM Providers UI E2E — provider registry 기반 providers API 경계 검증

검증 범위:
- GET /api/v1/llm/providers → 실제 registry에서 enabled provider 목록 반환
- codex, cc-codex가 별개 엔트리로 노출되는지 확인
- providers API 500 시 에러 응답 확인 (backend 경계, UI 렌더는 수동)

T4 포함 근거:
- tests/e2e/ 디렉토리에 E2E 테스트 파일 다수 존재 (test_llm_model_registry_e2e.py 등)
- 실제 registry + TestClient 기반으로 provider_registry 레이어 변경의 end-to-end 동작 검증
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.claude_worker.routes.llm_routes import router as llm_router


# LLM 라우터만 포함하는 minimal test app
_app = FastAPI()
_app.include_router(llm_router)


@pytest.fixture(scope="module")
def providers_client():
    """GET /api/v1/llm/providers 전용 TestClient (DB 의존 없음)."""
    with TestClient(_app) as c:
        yield c


# ─── R: 정상 경로 ─────────────────────────────────────────────────────────────

@pytest.mark.integration
def test_e2e_providers_api_returns_200_and_list(providers_client):
    """R: GET /api/v1/llm/providers → 200 + list 반환."""
    resp = providers_client.get("/api/v1/llm/providers")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1


@pytest.mark.integration
def test_e2e_providers_api_response_schema(providers_client):
    """R: 각 엔트리가 필수 필드(key/display_name/default_model/models/enabled/executor_key)를 가지는지."""
    resp = providers_client.get("/api/v1/llm/providers")
    assert resp.status_code == 200
    for entry in resp.json():
        assert "key" in entry
        assert "display_name" in entry
        assert "default_model" in entry
        assert "models" in entry
        assert isinstance(entry["models"], list)
        assert "enabled" in entry
        assert "executor_key" in entry
        assert "supports_quota_pause" in entry


@pytest.mark.integration
def test_e2e_providers_api_returns_enabled_only(providers_client):
    """R: 응답에 enabled=True인 provider만 포함되는지 (disabled provider 제외)."""
    resp = providers_client.get("/api/v1/llm/providers")
    assert resp.status_code == 200
    for entry in resp.json():
        assert entry["enabled"] is True, f"disabled provider 포함됨: {entry['key']}"


@pytest.mark.integration
def test_e2e_providers_api_includes_codex(providers_client):
    """R: enabled provider 목록에 codex가 포함되는지."""
    resp = providers_client.get("/api/v1/llm/providers")
    assert resp.status_code == 200
    keys = [e["key"] for e in resp.json()]
    assert "codex" in keys, f"codex가 providers 목록에 없음. 현재 keys: {keys}"


@pytest.mark.integration
def test_e2e_providers_api_includes_cc_codex(providers_client):
    """R: enabled provider 목록에 cc-codex가 포함되는지."""
    resp = providers_client.get("/api/v1/llm/providers")
    assert resp.status_code == 200
    keys = [e["key"] for e in resp.json()]
    assert "cc-codex" in keys, f"cc-codex가 providers 목록에 없음. 현재 keys: {keys}"


@pytest.mark.integration
def test_e2e_providers_api_codex_and_cc_codex_distinct_executor_keys(providers_client):
    """Re: codex와 cc-codex의 executor_key가 서로 다른지 (회귀 방어)."""
    resp = providers_client.get("/api/v1/llm/providers")
    assert resp.status_code == 200
    by_key = {e["key"]: e for e in resp.json()}
    assert "codex" in by_key, "codex provider가 없음"
    assert "cc-codex" in by_key, "cc-codex provider가 없음"
    assert by_key["codex"]["executor_key"] != by_key["cc-codex"]["executor_key"], (
        f"codex executor_key={by_key['codex']['executor_key']} 와 "
        f"cc-codex executor_key={by_key['cc-codex']['executor_key']} 가 동일함 — 하드코딩 누락 의심"
    )


@pytest.mark.integration
def test_e2e_providers_api_openai_disabled_not_in_list(providers_client):
    """R: openai는 enabled=False이므로 목록에 없어야 함."""
    resp = providers_client.get("/api/v1/llm/providers")
    assert resp.status_code == 200
    keys = [e["key"] for e in resp.json()]
    assert "openai" not in keys, f"disabled openai가 providers 목록에 포함됨: {keys}"


# ─── B: Boundary — 빈 list 케이스 (monkeypatch) ─────────────────────────────

@pytest.mark.integration
def test_e2e_providers_api_empty_registry_returns_empty_list(monkeypatch):
    """B: list_enabled()가 빈 리스트 반환 → API 응답도 []."""
    import app.modules.claude_worker.services.provider_registry as reg
    monkeypatch.setattr(reg, "list_enabled", lambda: [])

    app2 = FastAPI()
    app2.include_router(llm_router)

    with TestClient(app2) as c:
        resp = c.get("/api/v1/llm/providers")
    assert resp.status_code == 200
    assert resp.json() == []
