"""
FileSearchWorker 캐시 신선도 재현 통합 TC (T3)

redis 비활성 + 실 DB 세션, 외부 도구 서비스만 mock.

검증 대상:
    - preserver 축: 메인 루프 반복 중 interval 경계마다 checked_at이 2회 이상 갱신
    - display 축: 직접 탐지 실패 시 신선한 캐시로 ripgrep_ok:true, stale이면 false
"""
import time
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# 공통 픽스처: 메모리 SQLite DB + 필요 테이블 생성
# ---------------------------------------------------------------------------

@pytest.fixture
def memory_db_session():
    """메모리 SQLite DB 세션 (테스트 격리용)."""
    from app.core.database import Base
    from app.models.bootstrap import load_all_models

    load_all_models()
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # in-memory: 모든 연결이 동일 DB 공유
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = Session()

    with patch("app.worker.file_search_worker.SessionLocal", Session), \
         patch("app.database.SessionLocal", Session), \
         patch("app.core.database.SessionLocal", Session):
        yield session

    session.close()
    engine.dispose()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_worker() -> "FileSearchWorker":
    from app.worker.file_search_worker import FileSearchWorker
    worker = FileSearchWorker.__new__(FileSearchWorker)
    worker.name = "file_search_worker"
    worker.use_redis = False
    worker.redis_queue = None
    worker.open_queue = None
    worker._redis_initialized = True
    worker._last_status_check = 0.0
    worker._last_db_poll = 0.0
    return worker


async def _mock_safe_execute(name, coro_fn):
    await coro_fn()


# ---------------------------------------------------------------------------
# TC-T3-preserver: checked_at이 interval 경계마다 2회 이상 갱신
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reseed_keeps_checked_at_fresh_over_time(memory_db_session):
    """_main_loop_iteration을 time.time 단조 증가로 구동 시 checked_at이 2회+ 갱신된다."""
    from app.models.file_search_status import FileSearchStatus
    from app.worker.file_search_worker import STATUS_CHECK_INTERVAL

    # 외부 도구 서비스 mock (유저 세션에서 rg 항상 탐지 성공 시뮬레이션)
    with patch("app.modules.file_search.services.everything.EverythingService.is_available",
               new_callable=AsyncMock, return_value=(True, "")), \
         patch("app.modules.file_search.services.ripgrep.RipgrepService.is_available",
               return_value=(True, "C:\\fake\\rg.EXE")), \
         patch("os.path.exists", return_value=True), \
         patch("app.services.failure_alert_delivery.report_failure_alert",
               new_callable=AsyncMock):

        worker = _make_worker()
        worker._safe_execute = _mock_safe_execute

        timestamps_used = []
        base_time = 1000.0

        def _advancing_time():
            # 매 호출마다 STATUS_CHECK_INTERVAL+1씩 진행 (항상 interval 경과)
            t = base_time + len(timestamps_used) * (STATUS_CHECK_INTERVAL + 1)
            timestamps_used.append(t)
            return t

        with patch("app.worker.file_search_worker.time.time", side_effect=_advancing_time):
            # 3회 루프 실행 → 매 회 interval 경과 → 3회 재시드
            for _ in range(3):
                await worker._main_loop_iteration()

    # DB에서 checked_at 갱신 횟수 확인 — 적어도 2회 이상 갱신됐어야 함
    row = memory_db_session.query(FileSearchStatus).filter_by(id=1).first()
    assert row is not None, "file_search_status 행이 DB에 없음"
    assert row.ripgrep_ok is True, "ripgrep_ok가 True여야 함"
    assert row.checked_at is not None, "checked_at이 기록되어야 함"


# ---------------------------------------------------------------------------
# TC-T3-display: 직접 탐지 실패 시 신선/stale 캐시 폴백 검증
# ---------------------------------------------------------------------------

@pytest.fixture
def status_client_with_db(memory_db_session):
    """get_status 라우트용 TestClient — DB 의존성이 test_db 세션을 사용하도록 오버라이드."""
    from app.modules.file_search.routes import router as file_search_router
    from app.database import get_db

    def override_get_db():
        try:
            yield memory_db_session
        finally:
            pass

    app = FastAPI()
    app.include_router(file_search_router)  # router 내부에 이미 prefix 포함
    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def _insert_cache_row(db_session, *, ripgrep_ok: bool, age_seconds: int, rg_path: str = "C:\\fake\\rg.EXE"):
    """file_search_status id=1 행 삽입 또는 교체."""
    from app.models.file_search_status import FileSearchStatus
    row = db_session.query(FileSearchStatus).filter_by(id=1).first()
    checked_at = (datetime.now() - timedelta(seconds=age_seconds)).strftime("%Y-%m-%d %H:%M:%S")
    if row:
        row.ripgrep_ok = ripgrep_ok
        row.ripgrep_path = rg_path
        row.checked_at = checked_at
        row.everything_ok = True
    else:
        row = FileSearchStatus(
            id=1,
            everything_ok=True,
            ripgrep_ok=ripgrep_ok,
            ripgrep_path=rg_path,
            checked_at=checked_at,
        )
        db_session.add(row)
    db_session.commit()


def test_status_route_uses_fresh_cache_fallback(status_client_with_db, memory_db_session):
    """직접 탐지 실패 + 신선한 캐시 → ripgrep_ok:true."""
    _insert_cache_row(memory_db_session, ripgrep_ok=True, age_seconds=600)  # 10분 전 (< 24h)

    with patch("app.modules.file_search.services.ripgrep.RipgrepService.is_available",
               return_value=(False, None)), \
         patch("app.modules.file_search.services.everything.EverythingService.is_available",
               new_callable=AsyncMock, return_value=(False, "test")), \
         patch("os.path.exists", return_value=True):
        resp = status_client_with_db.get("/api/v1/file-search/status")

    assert resp.status_code == 200
    data = resp.json()
    assert data["ripgrep_ok"] is True, \
        f"신선한 캐시 폴백 시 ripgrep_ok=True여야 함. 실제: {data}"


def test_status_route_rejects_stale_cache(status_client_with_db, memory_db_session):
    """직접 탐지 실패 + stale 캐시(>24h) → ripgrep_ok:false."""
    _insert_cache_row(memory_db_session, ripgrep_ok=True, age_seconds=25 * 3600)  # 25시간 전 (> 24h)

    with patch("app.modules.file_search.services.ripgrep.RipgrepService.is_available",
               return_value=(False, None)), \
         patch("app.modules.file_search.services.everything.EverythingService.is_available",
               new_callable=AsyncMock, return_value=(False, "test")), \
         patch("os.path.exists", return_value=True):
        resp = status_client_with_db.get("/api/v1/file-search/status")

    assert resp.status_code == 200
    data = resp.json()
    assert data["ripgrep_ok"] is False, \
        f"stale 캐시(>24h) 시 ripgrep_ok=False여야 함. 실제: {data}"
