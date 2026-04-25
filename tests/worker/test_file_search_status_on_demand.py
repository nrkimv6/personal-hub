"""
FileSearchWorker 시드 상태 체크 TC

검증 대상:
    - 워커 초기화 시 도구 상태 1회 호출 (DB 캐시 시드)
    - 메인 루프에서 검색 요청 없이 상태 체크 미호출

GET /status는 더 이상 워커 캐시를 폴링하지 않고 API에서 직접 체크하므로
_execute_search 내부의 30초 룰은 제거됨 (TC3/TC4 삭제).
"""
import time
from unittest.mock import MagicMock

import pytest

from app.worker.file_search_worker import FileSearchWorker


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_worker() -> FileSearchWorker:
    worker = FileSearchWorker.__new__(FileSearchWorker)
    # BaseWorker.__init__ 없이 필요한 속성만 직접 세팅
    worker.name = "file_search_worker"
    worker.use_redis = False
    worker.redis_queue = None
    worker.open_queue = None
    worker._redis_initialized = True  # Redis 초기화 생략
    worker._last_status_check = 0.0
    worker._last_db_poll = 0.0
    return worker


async def _mock_safe_execute(name, coro_fn):
    """BaseWorker._safe_execute 대역: 바로 호출."""
    await coro_fn()


# ---------------------------------------------------------------------------
# TC1: 워커 초기화 시 상태 체크 1회 호출
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_initialize_calls_status_check():
    """_initialize() 호출 시 _check_tool_status()가 정확히 1회 실행된다."""
    worker = _make_worker()

    check_calls = []

    async def _fake_check():
        check_calls.append(1)

    async def _fake_cleanup():
        pass

    worker._cleanup_stale_requests = _fake_cleanup
    worker._check_tool_status = _fake_check
    worker._safe_execute = _mock_safe_execute

    await worker._initialize()

    assert len(check_calls) == 1, "초기화 시 _check_tool_status()가 1회 호출되어야 한다"
    assert worker._last_status_check > 0, "_last_status_check가 갱신되어야 한다"


# ---------------------------------------------------------------------------
# TC2: 메인 루프에서 상태 체크 미호출
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_main_loop_no_periodic_status_check():
    """_main_loop_iteration()은 상태 체크를 수행하지 않는다."""
    worker = _make_worker()
    worker._last_status_check = time.time() - 3600  # 오래 됐어도 호출 X

    check_calls = []

    async def _fake_check():
        check_calls.append(1)

    async def _fake_process_db():
        pass  # DB 폴링 noop

    worker._check_tool_status = _fake_check
    worker._process_db_pending = _fake_process_db

    safe_calls = []

    async def _tracking_safe_execute(name, coro_fn):
        safe_calls.append(name)
        await coro_fn()

    worker._safe_execute = _tracking_safe_execute
    worker._last_db_poll = 0.0

    await worker._main_loop_iteration()

    assert "check_tool_status" not in safe_calls, \
        "_main_loop_iteration()에서 check_tool_status가 호출되면 안 된다"
    assert len(check_calls) == 0, "_main_loop_iteration()에서 _check_tool_status가 직접 호출되면 안 된다"
