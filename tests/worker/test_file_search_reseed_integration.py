"""
FileSearchWorker on-demand 상태 체크 + DB 폴백 통합 TC (T3)

Redis 비활성 + 실 DB 세션, 외부 도구 서비스만 mock.

검증 대상:
    - on-demand 축: 큐 push → 워커 처리 → Redis 키 갱신 흐름 (TC-T3-ondemand)
    - display 축: 직접 탐지 실패 시 신선한 DB 캐시로 ripgrep_ok:true (TC-T3-display-fresh)
    - display 축: stale 캐시(>24h)이면 ripgrep_ok:false (TC-T3-display-stale)
"""
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
        poolclass=StaticPool,
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
    worker.status_check_queue = None
    worker._redis_initialized = True
    worker._last_status_check = 0.0
    worker._last_db_poll = 0.0
    return worker


async def _mock_safe_execute(name, coro_fn):
    await coro_fn()


# ---------------------------------------------------------------------------
# TC-T3-ondemand: 큐 push → 워커 처리 → Redis 키 갱신
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ondemand_status_check_via_queue(memory_db_session):
    """status_check_queue에 요청 push → 워커가 처리 → Redis 키와 DB 행이 갱신된다."""
    from app.models.file_search_status import FileSearchStatus

    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock()

    mock_queue = AsyncMock()
    mock_queue.pop_nowait = AsyncMock(return_value={"request": "status_check"})

    with patch("app.modules.file_search.services.everything.EverythingService.is_available",
               new_callable=AsyncMock, return_value=(True, "")), \
         patch("app.modules.file_search.services.ripgrep.RipgrepService.is_available",
               return_value=(True, "C:\\fake\\rg.exe")), \
         patch("os.path.exists", return_value=True), \
         patch("app.shared.redis.RedisClient.get_client",
               new_callable=AsyncMock, return_value=mock_redis), \
         patch("app.services.failure_alert_delivery.report_failure_alert",
               new_callable=AsyncMock):

        worker = _make_worker()
        worker.status_check_queue = mock_queue
        worker._safe_execute = _mock_safe_execute

        # on-demand 요청 처리 1사이클
        await worker._main_loop_iteration()

    # DB에 상태 행이 생성됐는지 확인
    row = memory_db_session.query(FileSearchStatus).filter_by(id=1).first()
    assert row is not None, "file_search_status 행이 DB에 없음"
    assert row.ripgrep_ok is True, "ripgrep_ok=True여야 함"

    # Redis 키도 갱신됐는지 확인
    mock_redis.set.assert_called_once()
    args, kwargs = mock_redis.set.call_args
    assert args[0] == "file_search:status_cache"
    assert kwargs.get("ex") == 60


# ---------------------------------------------------------------------------
# TC-T3-display-fresh: 직접 탐지 실패 + 신선한 DB 캐시 → ripgrep_ok:true
# ---------------------------------------------------------------------------

@pytest.fixture
def status_client_with_db(memory_db_session):
    """get_status 라우트용 TestClient — DB 의존성이 test_db 세션을 사용하도록 오버라이드."""
    from app.modules.file_search.routes import router as file_search_router
    from app.database import get_db
    import app.modules.file_search.routes as routes_module

    # 모듈 Redis 상태 초기화
    routes_module._redis_checked = False
    routes_module._redis_queue = None
    routes_module._open_queue = None
    routes_module._status_check_queue = None

    def override_get_db():
        try:
            yield memory_db_session
        finally:
            pass

    app = FastAPI()
    app.include_router(file_search_router)
    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def _insert_cache_row(db_session, *, ripgrep_ok: bool, age_seconds: int, rg_path: str = "C:\\fake\\rg.exe"):
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
    """직접 탐지 실패 + 신선한 DB 캐시 → ripgrep_ok:true (Redis 미연결 환경)."""
    _insert_cache_row(memory_db_session, ripgrep_ok=True, age_seconds=600)

    with patch("app.modules.file_search.services.ripgrep.RipgrepService.is_available",
               return_value=(False, None)), \
         patch("app.modules.file_search.services.everything.EverythingService.is_available",
               new_callable=AsyncMock, return_value=(False, "test")), \
         patch("os.path.exists", return_value=True), \
         patch("app.shared.redis.RedisClient.get_client",
               new_callable=AsyncMock, return_value=None):  # Redis 없음
        resp = status_client_with_db.get("/api/v1/file-search/status")

    assert resp.status_code == 200
    data = resp.json()
    assert data["ripgrep_ok"] is True, \
        f"신선한 DB 캐시 폴백 시 ripgrep_ok=True여야 함. 실제: {data}"


def test_status_route_rejects_stale_cache(status_client_with_db, memory_db_session):
    """직접 탐지 실패 + stale 캐시(>24h) → ripgrep_ok:false (Redis 미연결 환경)."""
    _insert_cache_row(memory_db_session, ripgrep_ok=True, age_seconds=25 * 3600)

    with patch("app.modules.file_search.services.ripgrep.RipgrepService.is_available",
               return_value=(False, None)), \
         patch("app.modules.file_search.services.everything.EverythingService.is_available",
               new_callable=AsyncMock, return_value=(False, "test")), \
         patch("os.path.exists", return_value=True), \
         patch("app.shared.redis.RedisClient.get_client",
               new_callable=AsyncMock, return_value=None):  # Redis 없음
        resp = status_client_with_db.get("/api/v1/file-search/status")

    assert resp.status_code == 200
    data = resp.json()
    assert data["ripgrep_ok"] is False, \
        f"stale 캐시(>24h) 시 ripgrep_ok=False여야 함. 실제: {data}"
