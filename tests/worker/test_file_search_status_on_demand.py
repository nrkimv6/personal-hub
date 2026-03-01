"""
FileSearchWorker 온디맨드 상태 체크 TC

검증 대상:
    - 워커 초기화 시 도구 상태 1회 호출
    - 메인 루프에서 검색 요청 없이 상태 체크 미호출
    - 검색 실행 시 30초 경과했으면 상태 체크 호출
    - 검색 실행 시 30초 미경과면 상태 체크 미호출
"""
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.worker.file_search_worker import FileSearchWorker, STATUS_CHECK_INTERVAL


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
# TC2: 메인 루프에서 검색 요청 없을 때 상태 체크 미호출
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_main_loop_no_periodic_status_check():
    """_main_loop_iteration()은 상태 체크를 수행하지 않는다 (온디맨드 전환 확인)."""
    worker = _make_worker()
    worker._last_status_check = time.time() - STATUS_CHECK_INTERVAL - 1  # 만료 상태

    check_calls = []

    async def _fake_check():
        check_calls.append(1)

    async def _fake_process_db():
        pass  # DB 폴링 noop

    worker._check_tool_status = _fake_check
    worker._process_db_pending = _fake_process_db

    # DB 폴링 모드에서 실행 (use_redis=False)
    # _safe_execute 대역 — check_tool_status 이름이 들어오면 기록
    safe_calls = []

    async def _tracking_safe_execute(name, coro_fn):
        safe_calls.append(name)
        await coro_fn()

    worker._safe_execute = _tracking_safe_execute
    # DB_POLL_INTERVAL 만료로 process_db_pending 호출되도록
    worker._last_db_poll = 0.0

    await worker._main_loop_iteration()

    assert "check_tool_status" not in safe_calls, \
        "_main_loop_iteration()에서 check_tool_status가 호출되면 안 된다"


# ---------------------------------------------------------------------------
# TC3: 검색 실행 시 30초 경과 → 상태 체크 호출
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_execute_search_triggers_status_check_when_stale():
    """마지막 상태 체크로부터 STATUS_CHECK_INTERVAL 이상 경과했으면 체크를 수행한다."""
    worker = _make_worker()
    worker._last_status_check = time.time() - STATUS_CHECK_INTERVAL - 1  # 만료

    check_calls = []

    async def _fake_check():
        check_calls.append(1)

    worker._check_tool_status = _fake_check
    worker._safe_execute = _mock_safe_execute

    # _execute_search 내부 로직만 테스트 — 실제 검색 서비스는 mock
    req = MagicMock()
    req.search_id = "test-id"
    req.request_json = '{"query": "hello", "mode": "ripgrep", "case_sensitive": false, "root_path": null, "max_results": 50}'

    mock_result = MagicMock()
    mock_result.model_dump_json.return_value = '{"results": []}'
    mock_result.total_count = 0

    db = MagicMock()

    with patch(
        "app.modules.file_search.services.search_service.SearchService.search",
        new=AsyncMock(return_value=mock_result),
    ):
        await worker._execute_search(req, db)

    assert len(check_calls) == 1, \
        "30초 경과 시 _execute_search()에서 _check_tool_status()가 1회 호출되어야 한다"


# ---------------------------------------------------------------------------
# TC4: 검색 실행 시 30초 미경과 → 상태 체크 미호출
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_execute_search_skips_status_check_when_fresh():
    """마지막 상태 체크로부터 STATUS_CHECK_INTERVAL 미만이면 체크를 건너뛴다."""
    worker = _make_worker()
    worker._last_status_check = time.time()  # 방금 체크함

    check_calls = []

    async def _fake_check():
        check_calls.append(1)

    worker._check_tool_status = _fake_check
    worker._safe_execute = _mock_safe_execute

    req = MagicMock()
    req.search_id = "test-id"
    req.request_json = '{"query": "hello", "mode": "ripgrep", "case_sensitive": false, "root_path": null, "max_results": 50}'

    mock_result = MagicMock()
    mock_result.model_dump_json.return_value = '{"results": []}'
    mock_result.total_count = 0

    db = MagicMock()

    with patch(
        "app.modules.file_search.services.search_service.SearchService.search",
        new=AsyncMock(return_value=mock_result),
    ):
        await worker._execute_search(req, db)

    assert len(check_calls) == 0, \
        "30초 미경과 시 _execute_search()에서 _check_tool_status()가 호출되면 안 된다"
