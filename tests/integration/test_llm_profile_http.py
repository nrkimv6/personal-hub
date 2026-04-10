"""LLM Profile HTTP 통합 테스트 (TestClient).

FastAPI TestClient를 사용하여 실제 HTTP 요청/응답을 검증합니다.
llm_router만 포함한 minimal app 사용.
mock 범위: RedisClient (launch-cli 전환 이후 subprocess.Popen 직접 mock 불필요).
"""
import json
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.modules.claude_worker.services.profile_store as ps
from app.database import get_db
from app.modules.claude_worker.routes.llm_routes import router as llm_router

# 프로필 라우터만 포함한 minimal test app
_test_app = FastAPI()
_test_app.include_router(llm_router)  # router already has prefix="/api/v1/llm"


@pytest.fixture(autouse=True)
def isolate_profiles(tmp_path, monkeypatch):
    """각 테스트가 독립 profiles 파일을 사용하도록 monkeypatch."""
    monkeypatch.setattr(ps, "LLM_PROFILES_FILE", tmp_path / "llm_profiles.json")
    yield tmp_path


@pytest.fixture
def client(test_db_session):
    """TestClient with DB override."""
    def override_get_db():
        try:
            yield test_db_session
        finally:
            pass
    _test_app.dependency_overrides[get_db] = override_get_db
    with TestClient(_test_app) as c:
        yield c
    _test_app.dependency_overrides.clear()


# ──────────────────────────────────────────
# GET /api/v1/llm/profiles
# ──────────────────────────────────────────

@pytest.mark.http
def test_GET_api_v1_llm_profiles_R_default(client):
    """GET /api/v1/llm/profiles → 200 + default profile 2개."""
    resp = client.get("/api/v1/llm/profiles")
    assert resp.status_code == 200
    data = resp.json()
    engines = [p["engine"] for p in data["profiles"]]
    assert "claude" in engines
    assert "gemini" in engines
    assert data["selected"]["claude"] == "default"
    assert data["selected"]["gemini"] == "default"


# ──────────────────────────────────────────
# PUT /api/v1/llm/profiles
# ──────────────────────────────────────────

@pytest.mark.http
def test_PUT_api_v1_llm_profiles_R_upsert(client):
    """PUT 저장 → GET 동일 값."""
    payload = {
        "selected": {"claude": "work", "gemini": "default"},
        "profiles": [
            {"engine": "claude", "name": "default", "config_dir": None, "extra_env": {}},
            {"engine": "claude", "name": "work", "config_dir": "C:/tmp/.claude-work", "extra_env": {}},
            {"engine": "gemini", "name": "default", "config_dir": None, "extra_env": {}},
        ],
    }
    put_resp = client.put("/api/v1/llm/profiles", json=payload)
    assert put_resp.status_code == 200

    get_resp = client.get("/api/v1/llm/profiles")
    data = get_resp.json()
    assert data["selected"]["claude"] == "work"
    assert any(p["name"] == "work" and p["config_dir"] == "C:/tmp/.claude-work" for p in data["profiles"])


@pytest.mark.http
def test_PUT_api_v1_llm_profiles_E_duplicate_name(client):
    """중복 name → 422."""
    payload = {
        "selected": {"claude": "default", "gemini": "default"},
        "profiles": [
            {"engine": "claude", "name": "default", "config_dir": None, "extra_env": {}},
            {"engine": "claude", "name": "default", "config_dir": None, "extra_env": {}},
            {"engine": "gemini", "name": "default", "config_dir": None, "extra_env": {}},
        ],
    }
    resp = client.put("/api/v1/llm/profiles", json=payload)
    assert resp.status_code == 422


@pytest.mark.http
def test_PUT_api_v1_llm_profiles_E_forbidden_extra_env(client):
    """extra_env 에 PATH → 422."""
    payload = {
        "selected": {"claude": "default", "gemini": "default"},
        "profiles": [
            {"engine": "claude", "name": "default", "config_dir": None, "extra_env": {"PATH": "/evil"}},
            {"engine": "gemini", "name": "default", "config_dir": None, "extra_env": {}},
        ],
    }
    resp = client.put("/api/v1/llm/profiles", json=payload)
    assert resp.status_code == 422


# ──────────────────────────────────────────
# POST /api/v1/llm/profiles/{engine}/select
# ──────────────────────────────────────────

@pytest.mark.http
def test_POST_api_v1_llm_profiles_engine_select_R(client):
    """POST /{engine}/select → selected 전환."""
    # 먼저 work profile 저장
    payload = {
        "selected": {"claude": "default", "gemini": "default"},
        "profiles": [
            {"engine": "claude", "name": "default", "config_dir": None, "extra_env": {}},
            {"engine": "claude", "name": "work", "config_dir": "C:/tmp/.claude-work", "extra_env": {}},
            {"engine": "gemini", "name": "default", "config_dir": None, "extra_env": {}},
        ],
    }
    client.put("/api/v1/llm/profiles", json=payload)

    # select work
    resp = client.post("/api/v1/llm/profiles/claude/select", json={"name": "work"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["selected"]["claude"] == "work"


@pytest.mark.http
def test_POST_api_v1_llm_profiles_engine_select_E_unknown_name(client):
    """존재하지 않는 name → 404."""
    resp = client.post("/api/v1/llm/profiles/claude/select", json={"name": "nonexistent"})
    assert resp.status_code == 404


# ──────────────────────────────────────────
# DELETE /api/v1/llm/profiles/{engine}/{name}
# ──────────────────────────────────────────

@pytest.mark.http
def test_DELETE_api_v1_llm_profiles_R_selected_fallback(client):
    """삭제 후 GET 시 selected 가 default."""
    # work 저장 + 선택
    payload = {
        "selected": {"claude": "work", "gemini": "default"},
        "profiles": [
            {"engine": "claude", "name": "default", "config_dir": None, "extra_env": {}},
            {"engine": "claude", "name": "work", "config_dir": "C:/tmp/.claude-work", "extra_env": {}},
            {"engine": "gemini", "name": "default", "config_dir": None, "extra_env": {}},
        ],
    }
    client.put("/api/v1/llm/profiles", json=payload)

    # work 삭제
    resp = client.delete("/api/v1/llm/profiles/claude/work")
    assert resp.status_code == 200
    data = resp.json()
    assert data["selected"]["claude"] == "default"


# ──────────────────────────────────────────
# POST /api/v1/llm/profiles/{engine}/{name}/launch-cli
# ──────────────────────────────────────────

@pytest.mark.http
def test_POST_launch_cli_R_admin(client):
    """admin(localhost=TestClient) 으로 200 + status=launched (Redis mock)."""
    mock_redis = AsyncMock()
    mock_redis.delete = AsyncMock()
    mock_redis.lpush = AsyncMock()
    mock_redis.brpop = AsyncMock(return_value=(
        b"worker:launch-cli:results",
        json.dumps({"success": True, "status": "launched", "engine": "claude", "profile": "default"}).encode()
    ))
    with patch("app.shared.redis.client.RedisClient.get_client", new=AsyncMock(return_value=mock_redis)):
        resp = client.post("/api/v1/llm/profiles/claude/default/launch-cli")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") == "launched"
    assert data.get("engine") == "claude"


@pytest.mark.http
def test_POST_launch_cli_E_redis_unavailable(client):
    """Redis 연결 없음 → status=redis_unavailable + message 포함."""
    with patch("app.shared.redis.client.RedisClient.get_client", new=AsyncMock(return_value=None)):
        resp = client.post("/api/v1/llm/profiles/claude/default/launch-cli")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") == "redis_unavailable"
    assert "message" in data


@pytest.mark.http
def test_POST_launch_cli_B_timeout(client):
    """Redis brpop 타임아웃 → status=timeout."""
    mock_redis = AsyncMock()
    mock_redis.delete = AsyncMock()
    mock_redis.lpush = AsyncMock()
    mock_redis.brpop = AsyncMock(return_value=None)
    with patch("app.shared.redis.client.RedisClient.get_client", new=AsyncMock(return_value=mock_redis)):
        resp = client.post("/api/v1/llm/profiles/claude/default/launch-cli")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") == "timeout"


@pytest.mark.http
def test_POST_launch_cli_E_unknown_engine(client):
    """화이트리스트 외 engine → 422."""
    resp = client.post("/api/v1/llm/profiles/codex/default/launch-cli")
    assert resp.status_code == 422


@pytest.mark.http
def test_POST_launch_cli_E_unknown_profile_name(client):
    """존재하지 않는 profile → 404."""
    resp = client.post("/api/v1/llm/profiles/claude/nonexistent/launch-cli")
    assert resp.status_code == 404


@pytest.mark.http
def test_POST_launch_cli_B_socket_timeout_returns_error(client):
    """B(경계): brpop에서 asyncio.TimeoutError → 500이 아닌 200 + status:error.

    재발 방어 TC: socket_timeout < brpop_timeout 불일치 시 발생하던 500 에러.
    수정 후: try-except로 포획 → {"status": "error"} 반환.
    """
    import asyncio
    mock_redis = AsyncMock()
    mock_redis.delete = AsyncMock()
    mock_redis.lpush = AsyncMock()
    mock_redis.brpop = AsyncMock(
        side_effect=asyncio.TimeoutError("Timeout reading from localhost:6379")
    )
    with patch("app.shared.redis.client.RedisClient.get_client", new=AsyncMock(return_value=mock_redis)):
        resp = client.post("/api/v1/llm/profiles/claude/default/launch-cli")
    assert resp.status_code == 200, f"socket timeout 시 500 발생 (try-except 미처리): {resp.text}"
    data = resp.json()
    assert data.get("status") == "error", f"status가 error가 아님: {data}"
