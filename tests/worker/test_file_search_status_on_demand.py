"""
FileSearchWorker 도구 상태 캐시 재시드 TC

검증 대상:
    - 워커 초기화 시 도구 상태 1회 시드 (TC1)
    - 메인 루프에서 STATUS_CHECK_INTERVAL 경과 시 재시드 (TC-R)
    - interval 이내 재시드 미호출 (TC-B)
    - 재시드 예외가 _safe_execute로 흡수되어 루프 계속 (TC-E)

GET /status는 API에서 직접 체크하며, 즉석 실패 시 워커가 주기적으로 갱신하는
DB 캐시를 폴백으로 사용한다. 따라서 캐시를 24h 이내로 신선하게 유지하는 것이 핵심.
"""
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.worker.file_search_worker import FileSearchWorker, STATUS_CHECK_INTERVAL


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_worker() -> FileSearchWorker:
    worker = FileSearchWorker.__new__(FileSearchWorker)
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
# TC-R: interval 경과 시 재시드
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_main_loop_iteration_R_reseeds_when_interval_elapsed():
    """_last_status_check가 STATUS_CHECK_INTERVAL 이상 지난 경우 재시드가 호출된다."""
    worker = _make_worker()
    worker._last_status_check = time.time() - STATUS_CHECK_INTERVAL - 1

    check_calls = []

    async def _fake_check():
        check_calls.append(1)

    async def _fake_process_db():
        pass

    worker._check_tool_status = _fake_check
    worker._process_db_pending = _fake_process_db

    safe_calls = []

    async def _tracking_safe_execute(name, coro_fn):
        safe_calls.append(name)
        await coro_fn()

    worker._safe_execute = _tracking_safe_execute
    worker._last_db_poll = 0.0
    old_ts = worker._last_status_check

    await worker._main_loop_iteration()

    assert "check_tool_status" in safe_calls, \
        "interval 경과 시 _main_loop_iteration()에서 check_tool_status가 호출되어야 한다"
    assert len(check_calls) == 1, "_check_tool_status가 1회 호출되어야 한다"
    assert worker._last_status_check > old_ts, "_last_status_check가 갱신되어야 한다"


# ---------------------------------------------------------------------------
# TC-B: interval 이내 재시드 미호출
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_main_loop_iteration_B_no_reseed_within_interval():
    """_last_status_check가 STATUS_CHECK_INTERVAL 이내이면 재시드를 하지 않는다."""
    worker = _make_worker()
    # interval 직전 (1초 여유) → 재시드 안 됨
    worker._last_status_check = time.time() - STATUS_CHECK_INTERVAL + 1

    check_calls = []

    async def _fake_check():
        check_calls.append(1)

    async def _fake_process_db():
        pass

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
        "interval 이내에는 check_tool_status가 호출되면 안 된다"
    assert len(check_calls) == 0


# ---------------------------------------------------------------------------
# TC-E: 재시드 예외가 루프를 중단하지 않음
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_main_loop_iteration_E_reseed_failure_does_not_break_loop():
    """_check_tool_status 예외가 _safe_execute로 흡수되어 루프가 계속된다."""
    worker = _make_worker()
    worker._last_status_check = time.time() - STATUS_CHECK_INTERVAL - 1

    async def _failing_check():
        raise RuntimeError("ripgrep 상태 체크 실패 시뮬레이션")

    post_check_calls = []

    async def _fake_process_db():
        post_check_calls.append(1)

    worker._check_tool_status = _failing_check
    worker._process_db_pending = _fake_process_db

    # _safe_execute는 예외를 흡수하고 계속하는 실제 구현을 모사
    async def _absorbing_safe_execute(name, coro_fn):
        try:
            await coro_fn()
        except Exception:
            pass  # 흡수

    worker._safe_execute = _absorbing_safe_execute
    worker._last_db_poll = 0.0

    # 예외 없이 완료되어야 함
    await worker._main_loop_iteration()

    # DB 폴링도 정상 실행됨
    assert len(post_check_calls) == 1, \
        "재시드 실패 후에도 DB 폴링이 실행되어야 한다"
