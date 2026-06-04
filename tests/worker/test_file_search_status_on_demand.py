"""
FileSearchWorker on-demand 상태 체크 TC

검증 대상:
    - 워커 초기화 시 도구 상태 1회 시드 (TC1)
    - status_check_queue에 요청 있으면 _check_tool_status 호출 (TC-OD-present)
    - status_check_queue 비어있으면 _check_tool_status 미호출 (TC-OD-empty)
    - _check_tool_status 실행 후 Redis 키 file_search:status_cache 갱신 (TC-RK)

이전 STATUS_CHECK_INTERVAL 주기 재시드 방식을 대체:
GET /status가 호출될 때 on-demand 큐를 통해 워커(Session 1)에 위임.
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.worker.file_search_worker import FileSearchWorker


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_worker() -> FileSearchWorker:
    worker = FileSearchWorker.__new__(FileSearchWorker)
    worker.name = "file_search_worker"
    worker.use_redis = False
    worker.redis_queue = None
    worker.open_queue = None
    worker.status_check_queue = None
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
# TC-OD-present: status_check_queue에 요청 있으면 _check_tool_status 호출
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_main_loop_iteration_ondemand_processes_status_check_queue():
    """status_check_queue에 요청이 있으면 _check_tool_status가 호출된다."""
    worker = _make_worker()

    mock_queue = AsyncMock()
    mock_queue.pop_nowait = AsyncMock(return_value={"request": "status_check"})
    worker.status_check_queue = mock_queue

    check_calls = []

    async def _fake_check():
        check_calls.append(1)

    worker._check_tool_status = _fake_check

    safe_calls = []

    async def _tracking_safe_execute(name, coro_fn):
        safe_calls.append(name)
        await coro_fn()

    worker._safe_execute = _tracking_safe_execute

    await worker._main_loop_iteration()

    assert "check_tool_status" in safe_calls, \
        "status_check_queue에 요청 있으면 check_tool_status가 호출되어야 한다"
    assert len(check_calls) == 1, "_check_tool_status가 정확히 1회 호출되어야 한다"


# ---------------------------------------------------------------------------
# TC-OD-empty: status_check_queue 비어있으면 _check_tool_status 미호출
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_main_loop_iteration_no_status_check_without_queue_item():
    """status_check_queue가 비어 있으면 _check_tool_status가 호출되지 않는다."""
    worker = _make_worker()

    mock_queue = AsyncMock()
    mock_queue.pop_nowait = AsyncMock(return_value=None)  # 빈 큐
    worker.status_check_queue = mock_queue

    check_calls = []

    async def _fake_check():
        check_calls.append(1)

    worker._check_tool_status = _fake_check

    safe_calls = []

    async def _tracking_safe_execute(name, coro_fn):
        safe_calls.append(name)
        await coro_fn()

    worker._safe_execute = _tracking_safe_execute

    await worker._main_loop_iteration()

    assert "check_tool_status" not in safe_calls, \
        "큐가 비어있으면 check_tool_status가 호출되면 안 된다"
    assert len(check_calls) == 0


# ---------------------------------------------------------------------------
# TC-RK: _check_tool_status 실행 후 Redis 키 file_search:status_cache 갱신
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_check_tool_status_writes_redis_key():
    """_check_tool_status() 실행 후 Redis 키 file_search:status_cache가 TTL 60으로 갱신된다."""
    worker = _make_worker()

    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock()

    mock_db = MagicMock()
    mock_db.query.return_value.filter_by.return_value.first.return_value = None

    with patch("app.shared.redis.RedisClient.get_client",
               new_callable=AsyncMock, return_value=mock_redis), \
         patch("app.worker.file_search_worker.SessionLocal", return_value=mock_db), \
         patch("app.modules.file_search.services.everything.EverythingService.is_available",
               new_callable=AsyncMock, return_value=(True, "")), \
         patch("app.modules.file_search.services.ripgrep.RipgrepService.is_available",
               return_value=(True, "C:\\fake\\rg.exe")), \
         patch("os.path.exists", return_value=True), \
         patch("app.services.failure_alert_delivery.report_failure_alert",
               new_callable=AsyncMock):
        await worker._check_tool_status()

    mock_redis.set.assert_called_once()
    args, kwargs = mock_redis.set.call_args
    assert args[0] == "file_search:status_cache", \
        "Redis 키 이름이 'file_search:status_cache'여야 한다"
    assert kwargs.get("ex") == 60, "Redis 키 TTL이 60초여야 한다"

    cache = json.loads(args[1])
    assert cache["ripgrep_ok"] is True
    assert "C:\\fake\\rg.exe" in cache["ripgrep_path"]
    assert cache["everything_ok"] is True
