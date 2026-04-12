"""
CoupangHttpClient 프록시 로테이션 테스트 (T1/T2)

RIGHT-BICEP:
- R(Right): 정상 동작 검증
- B(Boundary): 프록시 소진 경계 조건
- E(Error): 403/타임아웃 에러 시 동작

워커 fallback 통합 검증:
- HTTP 실패 → Playwright 경로 fallback
- ProxyManager 없음 → 직접 연결 graceful degradation
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest


# ──────────────────────────────────────────────
# 헬퍼
# ──────────────────────────────────────────────

def _vendor_items_payload():
    """vendor-items API 정상 응답 예시."""
    return {
        "travelItems": [
            {
                "vendorItems": [
                    {
                        "vendorItemName": "한라산 1박2일 A",
                        "saleStatus": "AVAILABLE",
                        "stockCount": 3,
                    },
                    {
                        "vendorItemName": "한라산 1박2일 B",
                        "saleStatus": "SOLD_OUT",
                        "stockCount": 0,
                    },
                ]
            }
        ]
    }


def _make_mock_response(status: int = 200, json_data=None, text_data: str = ""):
    """aiohttp 응답 비동기 컨텍스트 매니저 mock."""
    resp = MagicMock()
    resp.status = status
    resp.json = AsyncMock(return_value=json_data or {})
    resp.text = AsyncMock(return_value=text_data)
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=None)
    return resp


def _make_mock_session(get_resp=None, post_resp=None):
    """aiohttp.ClientSession mock."""
    session = MagicMock()
    session.closed = False
    if get_resp is not None:
        session.get = MagicMock(return_value=get_resp)
    if post_resp is not None:
        session.post = MagicMock(return_value=post_resp)
    return session


# ──────────────────────────────────────────────
# T1 TC
# ──────────────────────────────────────────────

async def test_http_client_fetch_RIGHT():
    """R: 정상 응답 → VendorItem 2건 반환."""
    from app.modules.coupang_travel.services.http_client import CoupangHttpClient

    get_resp = _make_mock_response(200, {})
    post_resp = _make_mock_response(200, _vendor_items_payload())
    mock_session = _make_mock_session(get_resp=get_resp, post_resp=post_resp)

    client = CoupangHttpClient(proxy_manager=None, proxy_usage_logger=None)

    with patch(
        "app.modules.coupang_travel.services.http_client.aiohttp.ClientSession",
        return_value=mock_session,
    ):
        client._session = mock_session  # 직접 주입 (세션 생성 생략)
        items = await client.fetch_vendor_items(
            product_id="10000001",
            vendor_item_package_id="pkg_001",
            select_date="2026-05-01",
        )

    assert items is not None
    assert len(items) == 2
    assert items[0].vendor_item_name == "한라산 1박2일 A"
    assert items[0].sale_status == "AVAILABLE"
    assert items[1].sale_status == "SOLD_OUT"


async def test_http_client_ensure_cookies_RIGHT():
    """R: 동일 product_id 두 번 호출 시 GET(쿠키획득)은 1회만 실행."""
    from app.modules.coupang_travel.services.http_client import CoupangHttpClient

    get_resp = _make_mock_response(200, {})
    post_resp = _make_mock_response(200, _vendor_items_payload())
    mock_session = _make_mock_session(get_resp=get_resp, post_resp=post_resp)

    client = CoupangHttpClient()
    client._session = mock_session

    # 첫 번째 호출
    await client.fetch_vendor_items("prod_A", "pkg_A", "2026-05-01")
    # 두 번째 호출 (같은 product_id)
    await client.fetch_vendor_items("prod_A", "pkg_A", "2026-05-02")

    # GET은 최초 1회만 (쿠키 캐시됨)
    assert mock_session.get.call_count == 1
    # POST는 2회 (날짜별 요청)
    assert mock_session.post.call_count == 2


async def test_http_client_proxy_rotation_ERROR():
    """E: 프록시1에서 403 → mark_failed 호출 + 프록시2로 재시도 → 성공."""
    from app.modules.coupang_travel.services.http_client import CoupangHttpClient

    mock_pm = MagicMock()
    # 첫 번째 get_fresh_proxy → "http://proxy1:8080"
    # 두 번째 get_fresh_proxy → "http://proxy2:8080"
    mock_pm.get_fresh_proxy = MagicMock(
        side_effect=["http://proxy1:8080", "http://proxy2:8080"]
    )
    mock_pm.mark_failed = MagicMock()

    resp_403 = _make_mock_response(403)
    resp_200 = _make_mock_response(200, _vendor_items_payload())

    get_resp = _make_mock_response(200, {})
    mock_session = MagicMock()
    mock_session.closed = False
    mock_session.get = MagicMock(return_value=get_resp)
    # post: 첫 번째 → 403, 두 번째 → 200
    mock_session.post = MagicMock(side_effect=[resp_403, resp_200])

    client = CoupangHttpClient(proxy_manager=mock_pm)
    client._session = mock_session

    items = await client.fetch_vendor_items("prod_A", "pkg_A", "2026-05-01")

    assert items is not None
    assert len(items) == 2
    # proxy1에 대해 mark_failed 호출 검증
    mock_pm.mark_failed.assert_called_once_with("http://proxy1:8080", "HTTP 403")


async def test_http_client_proxy_exhausted_BOUNDARY():
    """B: 프록시 없음(get_fresh_proxy→None) → 직접 연결로 성공."""
    from app.modules.coupang_travel.services.http_client import CoupangHttpClient

    mock_pm = MagicMock()
    mock_pm.get_fresh_proxy = MagicMock(return_value=None)  # 항상 None
    mock_pm.mark_failed = MagicMock()

    get_resp = _make_mock_response(200, {})
    post_resp = _make_mock_response(200, _vendor_items_payload())
    mock_session = _make_mock_session(get_resp=get_resp, post_resp=post_resp)

    client = CoupangHttpClient(proxy_manager=mock_pm)
    client._session = mock_session

    items = await client.fetch_vendor_items("prod_B", "pkg_B", "2026-06-01")

    # 직접 연결로 성공 → 결과 반환
    assert items is not None
    assert len(items) == 2
    # 프록시 없으므로 mark_failed 호출 없음
    mock_pm.mark_failed.assert_not_called()


async def test_http_client_proxy_timeout_ERROR():
    """E: 프록시1 타임아웃 → mark_failed 호출 + 프록시2로 재시도 → 성공."""
    from app.modules.coupang_travel.services.http_client import CoupangHttpClient

    mock_pm = MagicMock()
    mock_pm.get_fresh_proxy = MagicMock(
        side_effect=["http://proxy1:8080", "http://proxy2:8080"]
    )
    mock_pm.mark_failed = MagicMock()

    get_resp = _make_mock_response(200, {})
    resp_timeout = MagicMock()
    resp_timeout.__aenter__ = AsyncMock(side_effect=asyncio.TimeoutError())
    resp_timeout.__aexit__ = AsyncMock(return_value=None)
    resp_200 = _make_mock_response(200, _vendor_items_payload())

    mock_session = MagicMock()
    mock_session.closed = False
    mock_session.get = MagicMock(return_value=get_resp)
    mock_session.post = MagicMock(side_effect=[resp_timeout, resp_200])

    client = CoupangHttpClient(proxy_manager=mock_pm)
    client._session = mock_session

    items = await client.fetch_vendor_items("prod_C", "pkg_C", "2026-05-01")

    assert items is not None
    assert len(items) == 2
    # proxy1 타임아웃 → mark_failed("timeout")
    mock_pm.mark_failed.assert_called_once_with("http://proxy1:8080", "timeout")


async def test_http_client_usage_log_RIGHT():
    """R: ProxyUsageLogger.log_attempt() 성공 시 1회 호출, 인자 검증."""
    from app.modules.coupang_travel.services.http_client import CoupangHttpClient

    mock_pm = MagicMock()
    mock_pm.get_fresh_proxy = MagicMock(return_value="http://proxy1:8080")
    mock_pm.mark_failed = MagicMock()

    mock_logger = MagicMock()
    mock_logger.start_request = MagicMock(return_value="req-uuid-001")
    mock_logger.log_attempt = MagicMock()

    get_resp = _make_mock_response(200, {})
    post_resp = _make_mock_response(200, _vendor_items_payload())
    mock_session = _make_mock_session(get_resp=get_resp, post_resp=post_resp)

    client = CoupangHttpClient(proxy_manager=mock_pm, proxy_usage_logger=mock_logger)
    client._session = mock_session

    await client.fetch_vendor_items("prod_D", "pkg_D", "2026-05-01", schedule_id=42)

    # start_request 1회
    mock_logger.start_request.assert_called_once_with(
        schedule_id=42,
        target_url="https://trip.coupang.com/api/products/prod_D/vendor-items",
        fetch_method="coupang_http_api",
    )
    # log_attempt 1회 (성공)
    mock_logger.log_attempt.assert_called_once()
    call_kwargs = mock_logger.log_attempt.call_args.kwargs
    assert call_kwargs["request_id"] == "req-uuid-001"
    assert call_kwargs["success"] is True
    assert call_kwargs["http_status"] == 200


async def test_worker_http_first_playwright_fallback():
    """R: HTTP 클라이언트 전체 실패 → Playwright 경로로 fallback."""
    from app.worker.coupang_monitor_worker import CoupangMonitorWorker

    ctx = {
        "id": 1,
        "item_biz_item_id": "10000001",
        "date": "2026-05-01",
        "service_account_id": 10,
        "biz_item_pk": 5,
    }

    mock_http_client = AsyncMock()
    mock_http_client.fetch_vendor_items = AsyncMock(return_value=None)  # HTTP 전체 실패

    mock_monitor_service = AsyncMock()
    mock_monitor_service.check_and_notify = AsyncMock(return_value=[])

    # BizItem extra_desc_json mock
    mock_biz_item = MagicMock()
    mock_biz_item.extra_desc_json = '{"vendor_item_package_id": "pkg_001"}'

    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = mock_biz_item
    mock_db.close = MagicMock()

    # Playwright browser mock
    mock_page = AsyncMock()
    mock_page.url = "https://trip.coupang.com/tp/products/10000001"
    mock_page.goto = AsyncMock()

    mock_context = AsyncMock()
    mock_context.pages = [mock_page]

    mock_browser = AsyncMock()
    mock_browser.get_context = AsyncMock(return_value=mock_context)

    worker = CoupangMonitorWorker(browser_manager=mock_browser)
    worker._monitor_service = mock_monitor_service
    worker._http_client = mock_http_client

    with (
        patch("app.worker.coupang_monitor_worker.SessionLocal", return_value=mock_db),
        patch.object(worker, "_set_schedule_active"),
    ):
        await worker._check_schedule(ctx)

    # HTTP 클라이언트 호출됨
    mock_http_client.fetch_vendor_items.assert_awaited_once()
    # Playwright fallback: check_and_notify는 page= 인자로 호출됨
    call_kwargs = mock_monitor_service.check_and_notify.call_args.kwargs
    assert "page" in call_kwargs
    assert call_kwargs["page"] is mock_page


async def test_worker_proxy_manager_not_available():
    """R: ProxyManager 없이도 워커 초기화 및 직접 연결 정상 동작."""
    from app.worker.coupang_monitor_worker import CoupangMonitorWorker

    worker = CoupangMonitorWorker(browser_manager=None)

    # ProxyManager factory에서 None 반환
    with patch(
        "app.worker.coupang_monitor_worker.CoupangMonitorWorker._get_proxy_manager",
        return_value=None,
    ), patch(
        "app.worker.coupang_monitor_worker.CoupangMonitorWorker._get_proxy_usage_logger",
        return_value=None,
    ), patch(
        "app.worker.coupang_monitor_worker.SessionLocal"
    ) as mock_sl, patch(
        "app.modules.coupang_travel.services.api_client.CoupangApiClient"
    ), patch(
        "app.modules.coupang_travel.services.monitor_service.CoupangMonitorService"
    ), patch(
        "app.shared.notification.NotificationService"
    ):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.count.return_value = 0
        mock_db.close = MagicMock()
        mock_sl.return_value = mock_db

        with patch(
            "app.services.schedule_service.ScheduleService.get_all_with_context",
            return_value=[],
        ):
            await worker._initialize()

    # 프록시 없이 초기화 완료 — http_client는 생성됨
    assert worker._http_client is not None
    # proxy_manager 없음 검증
    assert worker._http_client._proxy_manager is None
