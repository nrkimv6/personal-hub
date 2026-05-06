"""
GET /file-search/status 직접 체크 단위 TC

검증 대상:
    - Everything/ripgrep 즉석 체크 결과를 그대로 반환
    - ripgrep 즉석 실패 시 DB 캐시(24h 이내 + 실파일 존재) 폴백
    - ripgrep 캐시 stale (>24h) 또는 실파일 없을 때 폴백 미적용
    - Everything 실패 메시지 포함
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.file_search.routes import get_status


def _make_status_row(*, ripgrep_ok: bool, ripgrep_path: str | None, age_hours: float = 0.0):
    """file_search_status DB row mock 생성."""
    row = MagicMock()
    row.ripgrep_ok = ripgrep_ok
    row.ripgrep_path = ripgrep_path
    checked = datetime.now() - timedelta(hours=age_hours)
    row.checked_at = checked.strftime("%Y-%m-%d %H:%M:%S")
    return row


def _make_db(row=None):
    """SQLAlchemy Session mock — query().filter_by().first() → row."""
    db = MagicMock()
    db.query.return_value.filter_by.return_value.first.return_value = row
    return db


# ---------------------------------------------------------------------------
# R: 정상 입력 — 둘 다 ok
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_status_R_both_ok_returns_true(tmp_path):
    """Everything=True, ripgrep=(True, path) → 응답에 그대로 반영."""
    rg_file = tmp_path / "rg.exe"
    rg_file.write_bytes(b"")

    with patch(
        "app.modules.file_search.routes.EverythingService"
    ) as mock_everything, patch(
        "app.modules.file_search.routes.RipgrepService"
    ) as mock_ripgrep:
        mock_everything.return_value.is_available = AsyncMock(return_value=(True, "연결됨"))
        mock_ripgrep.return_value.is_available = MagicMock(return_value=(True, str(rg_file)))

        db = _make_db(row=None)  # 즉석 체크 성공 → DB 미조회 (확인은 ripgrep_ok 분기 후)
        resp = await get_status(db=db)

    assert resp.everything_ok is True
    assert resp.everything_message == ""
    assert resp.ripgrep_ok is True
    assert resp.ripgrep_path == str(rg_file)


# ---------------------------------------------------------------------------
# E: Everything 즉석 체크 실패
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_status_E_everything_unavailable(tmp_path):
    """Everything 실패 시 everything_ok=False + 메시지 반환."""
    rg_file = tmp_path / "rg.exe"
    rg_file.write_bytes(b"")

    with patch(
        "app.modules.file_search.routes.EverythingService"
    ) as mock_everything, patch(
        "app.modules.file_search.routes.RipgrepService"
    ) as mock_ripgrep:
        mock_everything.return_value.is_available = AsyncMock(
            return_value=(False, "연결 실패 (포트: 7780)")
        )
        mock_ripgrep.return_value.is_available = MagicMock(return_value=(True, str(rg_file)))

        db = _make_db(row=None)
        resp = await get_status(db=db)

    assert resp.everything_ok is False
    assert "연결 실패" in resp.everything_message
    assert "워커 미실행" not in resp.everything_message
    assert resp.ripgrep_ok is True


# ---------------------------------------------------------------------------
# B: ripgrep 즉석 실패 → 캐시 폴백 적용 (24h 이내 + 실파일 존재)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_status_B_ripgrep_fallback_to_cache(tmp_path):
    """ripgrep 즉석=(False, None) + DB 캐시 유효 → 캐시값으로 응답."""
    cached_rg = tmp_path / "cached_rg.exe"
    cached_rg.write_bytes(b"")

    with patch(
        "app.modules.file_search.routes.EverythingService"
    ) as mock_everything, patch(
        "app.modules.file_search.routes.RipgrepService"
    ) as mock_ripgrep:
        mock_everything.return_value.is_available = AsyncMock(return_value=(True, "연결됨"))
        mock_ripgrep.return_value.is_available = MagicMock(return_value=(False, None))

        row = _make_status_row(ripgrep_ok=True, ripgrep_path=str(cached_rg), age_hours=1.0)
        db = _make_db(row=row)
        resp = await get_status(db=db)

    assert resp.everything_ok is True
    assert resp.ripgrep_ok is True, "DB 캐시 폴백이 적용되어야 한다"
    assert resp.ripgrep_path == str(cached_rg)


# ---------------------------------------------------------------------------
# B: ripgrep 캐시 stale (25h 전) → 폴백 미적용
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_status_B_ripgrep_cache_stale_24h_ignored(tmp_path):
    """DB 캐시가 25h 전이면 폴백 미적용 — 즉석 결과 그대로."""
    cached_rg = tmp_path / "cached_rg.exe"
    cached_rg.write_bytes(b"")

    with patch(
        "app.modules.file_search.routes.EverythingService"
    ) as mock_everything, patch(
        "app.modules.file_search.routes.RipgrepService"
    ) as mock_ripgrep:
        mock_everything.return_value.is_available = AsyncMock(return_value=(True, ""))
        mock_ripgrep.return_value.is_available = MagicMock(return_value=(False, None))

        row = _make_status_row(ripgrep_ok=True, ripgrep_path=str(cached_rg), age_hours=25.0)
        db = _make_db(row=row)
        resp = await get_status(db=db)

    assert resp.ripgrep_ok is False, "25h 전 캐시는 폴백 적용 안 됨"
    assert resp.ripgrep_path is None


# ---------------------------------------------------------------------------
# E: ripgrep 캐시 path가 디스크에 없음 → 폴백 미적용
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_status_E_ripgrep_cache_path_missing(tmp_path):
    """캐시된 ripgrep_path가 디스크에 없으면 폴백 미적용."""
    missing_path = str(tmp_path / "does_not_exist.exe")
    assert not os.path.exists(missing_path)

    with patch(
        "app.modules.file_search.routes.EverythingService"
    ) as mock_everything, patch(
        "app.modules.file_search.routes.RipgrepService"
    ) as mock_ripgrep:
        mock_everything.return_value.is_available = AsyncMock(return_value=(True, ""))
        mock_ripgrep.return_value.is_available = MagicMock(return_value=(False, None))

        row = _make_status_row(ripgrep_ok=True, ripgrep_path=missing_path, age_hours=1.0)
        db = _make_db(row=row)
        resp = await get_status(db=db)

    assert resp.ripgrep_ok is False, "캐시 path가 없는 파일이면 폴백 적용 안 됨"
    assert resp.ripgrep_path is None


# ---------------------------------------------------------------------------
# T3: 재현/통합 TC — mock 없이 실제 service 사용
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_status_integration_real_services():
    """mock 없이 실제 EverythingService/RipgrepService 호출 — graceful fallback 검증.

    Everything 미실행 환경에서는 everything_ok=False로 정상 응답 (예외 없음).
    """
    db = _make_db(row=None)
    resp = await get_status(db=db)

    # 응답 자체는 성공 (예외 없이 StatusResponse)
    assert resp is not None
    # everything_ok는 환경에 따라 다름 — 타입만 검증
    assert isinstance(resp.everything_ok, bool)
    assert isinstance(resp.ripgrep_ok, bool)
    # everything_ok=False여도 fallback message에 "워커 미실행" 표현 절대 없음
    if not resp.everything_ok:
        assert "워커 미실행" not in resp.everything_message


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_status_repeated_calls_under_3s():
    """get_status를 5회 연속 호출, 평균 응답시간 < 3초 (timeout 상한 내) 검증."""
    import time

    db = _make_db(row=None)
    start = time.time()
    for _ in range(5):
        resp = await get_status(db=db)
        assert resp is not None
    elapsed = time.time() - start
    avg = elapsed / 5
    # Everything 정상이면 즉시 응답. 타임아웃이 걸려도 회당 3초 상한.
    assert avg < 3.5, f"평균 응답시간이 너무 김: {avg:.2f}s"
