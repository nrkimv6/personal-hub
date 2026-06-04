"""
GET /file-search/status Redis 위임 TC

검증 대상:
    - 직접 탐지 실패 + Redis 키 있으면 즉시 ripgrep_ok:true 반환 (TC-RK-hit)
    - Redis 키 없으면 큐 push + 대기 후 키 갱신 시 ripgrep_ok:true 반환 (TC-RK-miss-then-hit)
    - 4초 대기 후에도 Redis 키 없으면 DB 캐시 폴백 경로 진입 (TC-RK-timeout-db-fallback)
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.modules.file_search.routes as routes_module
from app.modules.file_search.routes import get_status


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_redis_module_state():
    """각 테스트 전후 모듈 수준 Redis 상태 초기화."""
    routes_module._redis_checked = False
    routes_module._redis_queue = None
    routes_module._open_queue = None
    routes_module._status_check_queue = None
    yield
    routes_module._redis_checked = False
    routes_module._redis_queue = None
    routes_module._open_queue = None
    routes_module._status_check_queue = None


def _make_db(row=None):
    db = MagicMock()
    db.query.return_value.filter_by.return_value.first.return_value = row
    return db


def _make_status_row(*, ripgrep_ok: bool, ripgrep_path: str, age_hours: float = 1.0):
    row = MagicMock()
    row.ripgrep_ok = ripgrep_ok
    row.ripgrep_path = ripgrep_path
    checked = datetime.now() - timedelta(hours=age_hours)
    row.checked_at = checked.strftime("%Y-%m-%d %H:%M:%S")
    return row


# ---------------------------------------------------------------------------
# TC-RK-hit: Redis 키 있으면 즉시 ripgrep_ok:true 반환
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_status_route_uses_redis_key_when_direct_fails():
    """직접 탐지 실패 + Redis 키 file_search:status_cache 있으면 즉시 ripgrep_ok:true 반환."""
    cache_data = json.dumps({
        "ripgrep_ok": True,
        "ripgrep_path": "C:\\fake\\rg.exe",
        "everything_ok": False,
    })

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=cache_data.encode())

    with patch("app.modules.file_search.routes.EverythingService") as mock_everything, \
         patch("app.modules.file_search.routes.RipgrepService") as mock_ripgrep, \
         patch("app.shared.redis.RedisClient.get_client",
               new_callable=AsyncMock, return_value=mock_redis):

        mock_everything.return_value.is_available = AsyncMock(return_value=(False, "미연결"))
        mock_ripgrep.return_value.is_available = MagicMock(return_value=(False, None))

        db = _make_db(row=None)
        resp = await get_status(db=db)

    assert resp.ripgrep_ok is True, \
        f"Redis 키 있을 때 ripgrep_ok=True여야 함. 실제: {resp.ripgrep_ok}"
    assert resp.ripgrep_path == "C:\\fake\\rg.exe"
    # DB는 조회하지 않음
    db.query.assert_not_called()


# ---------------------------------------------------------------------------
# TC-RK-miss-then-hit: Redis 키 없으면 큐 push + 대기 후 키 갱신 시 ripgrep_ok:true
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_status_route_pushes_queue_and_waits_when_redis_key_missing():
    """Redis 키 없으면 큐에 push하고, 대기 중 키가 갱신되면 ripgrep_ok:true 반환."""
    cache_data = json.dumps({
        "ripgrep_ok": True,
        "ripgrep_path": "C:\\fake\\rg.exe",
        "everything_ok": False,
    })

    call_count = 0

    async def _get_side_effect(key):
        nonlocal call_count
        call_count += 1
        if call_count <= 1:
            return None  # 첫 호출: 키 없음
        return cache_data.encode()  # 두 번째 호출부터: 키 있음

    mock_redis = AsyncMock()
    mock_redis.get = _get_side_effect
    mock_redis.lpush = AsyncMock()

    with patch("app.modules.file_search.routes.EverythingService") as mock_everything, \
         patch("app.modules.file_search.routes.RipgrepService") as mock_ripgrep, \
         patch("app.shared.redis.RedisClient.get_client",
               new_callable=AsyncMock, return_value=mock_redis), \
         patch("app.modules.file_search.routes.asyncio.sleep",
               new_callable=AsyncMock):  # sleep을 no-op으로 만들어 빠른 테스트

        mock_everything.return_value.is_available = AsyncMock(return_value=(False, "미연결"))
        mock_ripgrep.return_value.is_available = MagicMock(return_value=(False, None))

        db = _make_db(row=None)
        resp = await get_status(db=db)

    assert resp.ripgrep_ok is True, \
        f"큐 push 후 키 갱신 시 ripgrep_ok=True여야 함. 실제: {resp.ripgrep_ok}"
    # 큐 push가 발생했는지 확인 (lpush = RedisQueue 내부 구현)
    assert mock_redis.lpush.called, "큐에 push가 발생해야 한다"


# ---------------------------------------------------------------------------
# TC-RK-timeout-db-fallback: 4초 대기 후 Redis 키 없으면 DB 캐시 폴백
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_status_route_falls_back_to_db_on_timeout():
    """Redis 키가 4초 대기 후에도 갱신되지 않으면 DB 캐시 폴백 경로 진입."""
    import tempfile, os

    # 실제 경로의 임시 파일 생성 (os.path.exists 통과용)
    with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)  # 항상 None — 타임아웃 시뮬레이션
        mock_redis.lpush = AsyncMock()

        db_row = _make_status_row(ripgrep_ok=True, ripgrep_path=tmp_path, age_hours=1.0)
        db = _make_db(row=db_row)

        with patch("app.modules.file_search.routes.EverythingService") as mock_everything, \
             patch("app.modules.file_search.routes.RipgrepService") as mock_ripgrep, \
             patch("app.shared.redis.RedisClient.get_client",
                   new_callable=AsyncMock, return_value=mock_redis), \
             patch("app.modules.file_search.routes.asyncio.sleep",
                   new_callable=AsyncMock):  # sleep no-op → 40회 즉시 완료

            mock_everything.return_value.is_available = AsyncMock(return_value=(False, "미연결"))
            mock_ripgrep.return_value.is_available = MagicMock(return_value=(False, None))

            resp = await get_status(db=db)

        assert resp.ripgrep_ok is True, \
            f"Redis 타임아웃 후 DB 캐시 폴백으로 ripgrep_ok=True여야 함. 실제: {resp.ripgrep_ok}"
        assert resp.ripgrep_path == tmp_path

    finally:
        os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# Phase T3: 통합 TC (실 Redis 없이 in-memory로 전체 흐름 검증)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_status_route_full_ondemand_flow():
    """Redis 키 없는 상태에서 큐 push → 즉시 키 갱신 → ripgrep_ok:true 전체 흐름.

    asyncio.sleep mock으로 빠르게 실행.
    """
    cache_data = json.dumps({
        "ripgrep_ok": True,
        "ripgrep_path": "C:\\fake\\rg.exe",
        "everything_ok": True,
    })

    call_count = 0

    async def _get_side_effect(key):
        nonlocal call_count
        call_count += 1
        # 최초 조회 + 루프 첫 번째까지 None, 두 번째부터 갱신
        if call_count <= 2:
            return None
        return cache_data.encode()

    mock_redis = AsyncMock()
    mock_redis.get = _get_side_effect
    mock_redis.lpush = AsyncMock()

    with patch("app.modules.file_search.routes.EverythingService") as mock_everything, \
         patch("app.modules.file_search.routes.RipgrepService") as mock_ripgrep, \
         patch("app.shared.redis.RedisClient.get_client",
               new_callable=AsyncMock, return_value=mock_redis), \
         patch("app.modules.file_search.routes.asyncio.sleep",
               new_callable=AsyncMock):

        mock_everything.return_value.is_available = AsyncMock(return_value=(True, ""))
        mock_ripgrep.return_value.is_available = MagicMock(return_value=(False, None))

        db = _make_db(row=None)
        resp = await get_status(db=db)

    assert resp.ripgrep_ok is True
    assert resp.ripgrep_path == "C:\\fake\\rg.exe"
    assert mock_redis.lpush.called, "on-demand 큐 push가 발생해야 한다"
