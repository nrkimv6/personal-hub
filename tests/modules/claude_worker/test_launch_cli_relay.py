"""launch_cli 엔드포인트 Redis 릴레이 단위 테스트.

profile_routes.py의 async launch_cli 엔드포인트가
Redis 큐에 올바른 payload를 전달하는지 검증한다.
"""
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.modules.claude_worker.services.profile_store as ps
from app.modules.claude_worker.routes.profile_routes import router as profile_router


# ── minimal test app ────────────────────────────────────────────────────────

_test_app = FastAPI()
_test_app.include_router(profile_router, prefix="/api/v1/llm")


@pytest.fixture(autouse=True)
def isolate_profiles(tmp_path, monkeypatch):
    """각 테스트가 독립 profiles 파일을 사용하도록 monkeypatch."""
    monkeypatch.setattr(ps, "LLM_PROFILES_FILE", tmp_path / "llm_profiles.json")
    # default profile 세팅
    ps.save_profiles({
        "selected": {"claude": "default", "gemini": "default"},
        "profiles": [
            {"engine": "claude", "name": "default", "config_dir": None, "extra_env": {}},
            {"engine": "claude", "name": "work", "config_dir": "C:/Users/Narang/.claude-work", "extra_env": {"MY_KEY": "val"}},
            {"engine": "gemini", "name": "default", "config_dir": None, "extra_env": {}},
        ],
    })
    yield tmp_path


@pytest.fixture
def client():
    """auth 없이 TestClient (admin require_admin override)."""
    from app.core.auth import require_admin
    _test_app.dependency_overrides[require_admin] = lambda: MagicMock(username="admin")
    with TestClient(_test_app) as c:
        yield c
    _test_app.dependency_overrides.clear()


_SENTINEL = object()  # None과 "미지정"을 구분하기 위한 sentinel


def _make_redis_mock(brpop_result=_SENTINEL):
    """Redis async client mock 생성 헬퍼.

    brpop_result 미지정 시 → 기본 success 결과 반환.
    brpop_result=None 명시 시 → 타임아웃 시뮬레이션 (None 반환).
    """
    mock_redis = AsyncMock()
    if brpop_result is _SENTINEL:
        brpop_result = (b"worker:launch-cli:results", json.dumps({
            "success": True, "status": "launched", "engine": "claude", "profile": "default"
        }).encode())
    mock_redis.brpop = AsyncMock(return_value=brpop_result)
    mock_redis.delete = AsyncMock()
    mock_redis.lpush = AsyncMock()
    return mock_redis


# ── RIGHT ────────────────────────────────────────────────────────────────────

def test_launch_cli_relay_right(client):
    """R(정상): launch_cli 호출 시 lpush payload에 7개 필드 존재."""
    mock_redis = _make_redis_mock()

    with patch("app.shared.redis.client.RedisClient.get_client", new=AsyncMock(return_value=mock_redis)):
        resp = client.post("/api/v1/llm/profiles/claude/default/launch-cli")

    assert resp.status_code == 200
    assert mock_redis.lpush.called

    raw_payload = mock_redis.lpush.call_args[0][1]
    payload = json.loads(raw_payload)
    for field in ("action", "engine", "name", "config_dir", "extra_env", "engine_cmd", "env_key"):
        assert field in payload, f"payload에 {field!r} 필드 없음"


def test_launch_cli_relay_right_payload_env_key(client):
    """R(정상): engine별 env_key 매핑 검증 — claude=CLAUDE_CONFIG_DIR, gemini=None."""
    mock_redis_claude = _make_redis_mock(
        brpop_result=(b"k", json.dumps({"success": True, "status": "launched"}).encode())
    )
    mock_redis_gemini = _make_redis_mock(
        brpop_result=(b"k", json.dumps({"success": True, "status": "launched"}).encode())
    )

    with patch("app.shared.redis.client.RedisClient.get_client", new=AsyncMock(return_value=mock_redis_claude)):
        client.post("/api/v1/llm/profiles/claude/default/launch-cli")
    claude_payload = json.loads(mock_redis_claude.lpush.call_args[0][1])
    assert claude_payload["env_key"] == "CLAUDE_CONFIG_DIR"

    with patch("app.shared.redis.client.RedisClient.get_client", new=AsyncMock(return_value=mock_redis_gemini)):
        client.post("/api/v1/llm/profiles/gemini/default/launch-cli")
    gemini_payload = json.loads(mock_redis_gemini.lpush.call_args[0][1])
    assert gemini_payload["env_key"] is None


def test_launch_cli_relay_right_profile_lookup(client):
    """R(정상): name=work 지정 시 해당 profile의 config_dir/extra_env가 payload에 포함."""
    mock_redis = _make_redis_mock(
        brpop_result=(b"k", json.dumps({"success": True, "status": "launched", "engine": "claude", "profile": "work"}).encode())
    )

    with patch("app.shared.redis.client.RedisClient.get_client", new=AsyncMock(return_value=mock_redis)):
        resp = client.post("/api/v1/llm/profiles/claude/work/launch-cli")

    assert resp.status_code == 200
    payload = json.loads(mock_redis.lpush.call_args[0][1])
    assert payload["config_dir"] == "C:/Users/Narang/.claude-work"
    assert payload["extra_env"] == {"MY_KEY": "val"}
    assert payload["name"] == "work"


# ── BOUNDARY ─────────────────────────────────────────────────────────────────

def test_launch_cli_relay_boundary_unsupported_engine(client):
    """B(경계): 지원하지 않는 engine → 422."""
    resp = client.post("/api/v1/llm/profiles/codex/default/launch-cli")
    assert resp.status_code == 422


def test_launch_cli_relay_boundary_missing_profile(client):
    """B(경계): 존재하지 않는 profile name → 404."""
    resp = client.post("/api/v1/llm/profiles/claude/nonexistent/launch-cli")
    assert resp.status_code == 404


# ── ERROR ─────────────────────────────────────────────────────────────────────

def test_launch_cli_relay_error_redis_unavailable(client):
    """E(에러): RedisClient.get_client() → None → 수동 실행 명령 포함 응답."""
    with patch("app.shared.redis.client.RedisClient.get_client", new=AsyncMock(return_value=None)):
        resp = client.post("/api/v1/llm/profiles/claude/default/launch-cli")

    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") == "redis_unavailable"
    assert "message" in data
    assert "claude" in data["message"].lower() or "수동" in data["message"]


def test_launch_cli_relay_error_redis_timeout(client):
    """E(에러): brpop → None (타임아웃) → status: timeout 응답."""
    mock_redis = _make_redis_mock(brpop_result=None)

    with patch("app.shared.redis.client.RedisClient.get_client", new=AsyncMock(return_value=mock_redis)):
        resp = client.post("/api/v1/llm/profiles/claude/default/launch-cli")

    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") == "timeout"


# ── socket timeout 재발 방지 ──────────────────────────────────────────────────

def test_launch_cli_B_socket_timeout(client):
    """B(경계): brpop에서 asyncio.TimeoutError 발생 시 500이 아닌 status:error 반환."""
    mock_redis = _make_redis_mock()
    mock_redis.brpop = AsyncMock(side_effect=asyncio.TimeoutError("Timeout reading from localhost:6379"))

    with patch("app.shared.redis.client.RedisClient.get_client", new=AsyncMock(return_value=mock_redis)):
        resp = client.post("/api/v1/llm/profiles/claude/default/launch-cli")

    assert resp.status_code == 200, f"500이 반환됨 (socket timeout 미처리): {resp.text}"
    data = resp.json()
    assert data.get("status") == "error"


def test_launch_cli_B_connection_error(client):
    """B(경계): brpop에서 ConnectionError 발생 시 500이 아닌 status:error 반환."""
    mock_redis = _make_redis_mock()
    mock_redis.brpop = AsyncMock(side_effect=ConnectionError("Redis connection closed"))

    with patch("app.shared.redis.client.RedisClient.get_client", new=AsyncMock(return_value=mock_redis)):
        resp = client.post("/api/v1/llm/profiles/claude/default/launch-cli")

    assert resp.status_code == 200, f"500이 반환됨 (ConnectionError 미처리): {resp.text}"
    data = resp.json()
    assert data.get("status") == "error"


def test_launch_cli_R_brpop_timeout_constant():
    """Co(준수): _BRPOP_TIMEOUT_SEC < REDIS_CONNECTION_TIMEOUT (socket_timeout) 검증.

    brpop timeout이 socket_timeout 이상이면 소켓 레벨 TimeoutError가 먼저 발생하여 500 에러.
    """
    from app.modules.claude_worker.routes.profile_routes import _BRPOP_TIMEOUT_SEC
    from app.core.config import settings

    assert _BRPOP_TIMEOUT_SEC < settings.REDIS_CONNECTION_TIMEOUT, (
        f"_BRPOP_TIMEOUT_SEC({_BRPOP_TIMEOUT_SEC}) >= REDIS_CONNECTION_TIMEOUT({settings.REDIS_CONNECTION_TIMEOUT}). "
        "socket_timeout보다 짧게 설정해야 소켓 레벨 TimeoutError가 먼저 발생하지 않음."
    )


# ── T3: 근본 원인 재현 TC ─────────────────────────────────────────────────────

def test_launch_cli_T3_socket_timeout_returns_error_not_500(client):
    """T3: 근본 원인 재현 — socket timeout 시 500이 아닌 200 + status:error 반환.

    재현 조건: brpop에서 asyncio.TimeoutError 발생
    (실제 운영 환경: socket_timeout=5s < brpop_timeout=10s 일 때 5초 후 발생)
    수정 후: try-except로 예외 포획 → {"status": "error"} 반환
    """
    mock_redis = _make_redis_mock()
    mock_redis.brpop = AsyncMock(
        side_effect=asyncio.TimeoutError("Timeout reading from localhost:6379")
    )

    with patch("app.shared.redis.client.RedisClient.get_client", new=AsyncMock(return_value=mock_redis)):
        resp = client.post("/api/v1/llm/profiles/claude/default/launch-cli")

    # 핵심 검증: 500이 아니어야 한다
    assert resp.status_code == 200, (
        f"[T3 실패] socket timeout 시 500 발생. "
        f"try-except 미처리 또는 예외 누락. 응답: {resp.text}"
    )
    data = resp.json()
    assert data.get("status") == "error", f"[T3] status가 error가 아님: {data}"
