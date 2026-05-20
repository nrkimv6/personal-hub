"""Popup monitor service lifecycle tests.

Run status transitions:
- success: fetch succeeds and Apollo parse is clean.
- partial: fetch succeeds but parser reports an Apollo parse problem.
- error: fetch fails before parsing and the error run remains displayable.

Latest snapshot ordering uses run start order so an older scheduled run that
finishes late cannot overwrite a newer run's snapshot.
"""

import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.browser_profile import BrowserProfile
from app.models.popup_url_monitor import PopupUrlMonitor
from app.models.popup_url_monitor_run import PopupUrlMonitorRun
from app.models.service_account import ServiceAccount
from app.modules.naver_popup_monitor.services.fetcher import PopupFetchResult
from app.modules.naver_popup_monitor.services import monitor_service as monitor_service_module
from app.modules.naver_popup_monitor.services.monitor_service import PopupMonitorService


def _build_apollo_html(items: list[dict]) -> str:
    apollo = {
        "ROOT_QUERY": {
            "popupStoreList": [f"PopupStore:{item['popupId']}" for item in items],
        }
    }
    for item in items:
        apollo[f"PopupStore:{item['popupId']}"] = {
            "__typename": "PopupStore",
            "popupId": item["popupId"],
            "title": item["title"],
            "placeName": item.get("placeName", "unknown"),
            "startDate": item.get("startDate"),
            "endDate": item.get("endDate"),
            "bookingUrl": item.get("bookingUrl"),
        }
    return (
        "<html><body><script>"
        f"window.__APOLLO_STATE__ = {json.dumps(apollo, ensure_ascii=False)}"
        "</script></body></html>"
    )


def _build_place_reservation_html(
    *,
    booking_business_id: str | None = None,
    booking_url: str | None = None,
    ticket_total: int = 0,
) -> str:
    apollo = {
        "ROOT_QUERY": {
            'placeDetail({"input":{"deviceType":"pc","id":"2015421037","isNx":false}})': {
                "__typename": "PlaceDetail",
                "naverBooking": {
                    "__typename": "PlaceDetailNaverBooking",
                    "bookingBusinessId": booking_business_id,
                    "naverBookingUrl": booking_url,
                    "naverBookingHubUrl": None,
                    "bookingButtonName": "예약",
                },
                "tickets": {
                    "__typename": "TicketItemsResult",
                    "total": ticket_total,
                    "items": [],
                    "moreBookingUrl": "",
                },
            }
        }
    }
    return (
        "<html><body><script>"
        f"window.__APOLLO_STATE__ = {json.dumps(apollo, ensure_ascii=False)}"
        "</script></body></html>"
    )


class FakeFetcher:
    def __init__(self, results: list[PopupFetchResult]):
        self._results = results
        self.calls = 0

    async def fetch_popup_html(self, **kwargs):
        idx = min(self.calls, len(self._results) - 1)
        self.calls += 1
        return self._results[idx]

    async def close(self):
        return None


@pytest.fixture
def integration_session_factory():
    from app.models.base import Base

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[
            BrowserProfile.__table__,
            ServiceAccount.__table__,
            PopupUrlMonitor.__table__,
            PopupUrlMonitorRun.__table__,
        ],
    )
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=True)
    yield factory
    engine.dispose()


@pytest.mark.asyncio
async def test_monitor_service_updates_latest_runs_and_notification_condition(
    integration_session_factory,
):
    db = integration_session_factory()
    monitor = PopupUrlMonitor(
        name="팝업 테스트",
        url="https://pcmap.place.naver.com/popupstore/list",
        request_profile="A",
        fallback_strategy="reinforce",
        proxy_enabled=True,
        notify_on_new=True,
        min_new_count=2,
        monitoring_mode="anonymous",
        is_enabled=True,
    )
    db.add(monitor)
    db.commit()
    db.refresh(monitor)

    html_first = _build_apollo_html(
        [
            {
                "popupId": "p1",
                "title": "팝업1",
                "placeName": "성수",
                "startDate": "2026-04-10",
                "endDate": "2026-04-20",
            }
        ]
    )
    html_second = _build_apollo_html(
        [
            {
                "popupId": "p1",
                "title": "팝업1",
                "placeName": "성수",
                "startDate": "2026-04-10",
                "endDate": "2026-04-20",
            },
            {
                "popupId": "p2",
                "title": "팝업2",
                "placeName": "홍대",
                "startDate": "2026-04-11",
                "endDate": "2026-04-21",
            },
        ]
    )

    fake_fetcher = FakeFetcher(
        [
            PopupFetchResult(
                success=True,
                html=html_first,
                status=200,
                final_url="https://pcmap.place.naver.com/popupstore/list",
                request_profile="A",
                proxy_url=None,
                fallback_applied=False,
            ),
            PopupFetchResult(
                success=True,
                html=html_second,
                status=200,
                final_url="https://pcmap.place.naver.com/popupstore/list",
                request_profile="B",
                proxy_url="http://proxy.local:8080",
                fallback_applied=True,
            ),
        ]
    )
    notification = MagicMock()
    notification.should_notify.return_value = True
    notification.send_notification_message = AsyncMock()
    service = PopupMonitorService(
        fetcher=fake_fetcher,
        notification_service=notification,
    )

    outcome1 = await service.run_monitor_once(db, monitor, trigger="manual")
    assert outcome1.new_count == 1
    notification.send_notification_message.assert_not_called()

    monitor.min_new_count = 1
    db.commit()

    outcome2 = await service.run_monitor_once(db, monitor, trigger="manual")
    assert outcome2.new_count == 1
    assert outcome2.proxy_url == "http://proxy.local:8080"
    assert outcome2.fallback_applied is True

    runs_payload = service.list_runs_payload(db, monitor.id, limit=10)
    assert len(runs_payload) == 2
    assert runs_payload[0]["request_profile"] == "B"

    latest_payload = service.get_latest_payload(db, monitor.id)
    assert latest_payload["item_count"] == 2
    assert latest_payload["last_run"]["new_count"] == 1
    notification.send_notification_message.assert_called_once()
    db.close()


@pytest.mark.asyncio
async def test_latest_snapshot_uses_newer_finished_run_when_runs_complete_out_of_order(
    integration_session_factory,
    monkeypatch,
):
    db = integration_session_factory()
    newer_snapshot = {
        "items": [
            {
                "item_key": "id:newer",
                "popup_id": "newer",
                "title": "최신 팝업",
                "place_name": "성수",
                "start_date": None,
                "end_date": None,
                "status": None,
                "reservation_url": None,
                "raw": {},
            }
        ],
        "meta": {"trigger": "manual"},
        "diff": {"new_count": 1, "has_new": True},
    }
    monitor = PopupUrlMonitor(
        name="late-writer",
        url="https://pcmap.place.naver.com/popupstore/list",
        request_profile="A",
        fallback_strategy="reinforce",
        proxy_enabled=False,
        notify_on_new=False,
        min_new_count=1,
        monitoring_mode="anonymous",
        is_enabled=True,
        latest_snapshot_json=json.dumps(newer_snapshot, ensure_ascii=False),
        latest_snapshot_hash="newer-hash",
        latest_checked_at=datetime(2026, 5, 6, 10, 0, 0),
    )
    db.add(monitor)
    db.commit()
    db.refresh(monitor)
    newer_run = PopupUrlMonitorRun(
        monitor_id=monitor.id,
        status="success",
        new_count=1,
        has_new=True,
        snapshot_json=json.dumps(newer_snapshot, ensure_ascii=False),
        request_profile="A",
        fallback_applied=False,
        started_at=datetime(2026, 5, 6, 10, 0, 0),
        finished_at=datetime(2026, 5, 6, 10, 0, 5),
    )
    db.add(newer_run)
    db.commit()
    db.refresh(newer_run)
    newer_run_id = newer_run.id

    old_html = _build_apollo_html(
        [
            {
                "popupId": "older",
                "title": "오래된 팝업",
                "placeName": "홍대",
            }
        ]
    )
    service = PopupMonitorService(
        fetcher=FakeFetcher(
            [
                PopupFetchResult(
                    success=True,
                    html=old_html,
                    status=200,
                    final_url="https://pcmap.place.naver.com/popupstore/list",
                    request_profile="A",
                    proxy_url=None,
                    fallback_applied=False,
                )
            ]
        ),
        notification_service=MagicMock(should_notify=MagicMock(return_value=False)),
    )

    class OrderedDatetime(datetime):
        calls = [
            datetime(2026, 5, 6, 9, 59, 0),
            datetime(2026, 5, 6, 10, 1, 0),
        ]

        @classmethod
        def now(cls, tz=None):
            value = cls.calls.pop(0)
            if tz is not None:
                return value.replace(tzinfo=tz)
            return value

    monkeypatch.setattr(monitor_service_module, "datetime", OrderedDatetime)

    outcome = await service.run_monitor_once(db, monitor, trigger="worker")
    assert outcome.status == "success"

    db.refresh(monitor)
    latest_payload = service.get_latest_payload(db, monitor.id)
    assert monitor.latest_snapshot_hash == "newer-hash"
    assert latest_payload["snapshot"]["items"][0]["popup_id"] == "newer"
    assert latest_payload["last_run"]["id"] == newer_run_id
    assert latest_payload["last_run"]["id"] != outcome.run_id
    db.close()


@pytest.mark.asyncio
async def test_monitor_service_records_error_run_and_updates_checked_at(
    integration_session_factory,
):
    db = integration_session_factory()
    monitor = PopupUrlMonitor(
        name="error-run",
        url="https://pcmap.place.naver.com/popupstore/list",
        request_profile="A",
        fallback_strategy="reinforce",
        proxy_enabled=False,
        notify_on_new=False,
        min_new_count=1,
        monitoring_mode="anonymous",
        is_enabled=True,
    )
    db.add(monitor)
    db.commit()
    db.refresh(monitor)

    service = PopupMonitorService(
        fetcher=FakeFetcher(
            [
                PopupFetchResult(
                    success=False,
                    status=503,
                    final_url="https://pcmap.place.naver.com/popupstore/list",
                    request_profile="A",
                    proxy_url="http://proxy.local:8080",
                    fallback_applied=True,
                    error="HTTP 503",
                )
            ]
        ),
        notification_service=MagicMock(should_notify=MagicMock(return_value=False)),
    )

    outcome = await service.run_monitor_once(db, monitor, trigger="worker")
    assert outcome.status == "error"
    assert outcome.error_message == "HTTP 503"

    db.refresh(monitor)
    runs_payload = service.list_runs_payload(db, monitor.id, limit=10)
    assert monitor.latest_checked_at is not None
    assert runs_payload[0]["status"] == "error"
    assert runs_payload[0]["error_message"] == "HTTP 503"
    assert runs_payload[0]["snapshot"] is None
    db.close()


@pytest.mark.asyncio
async def test_monitor_service_preserves_partial_run_after_success(
    integration_session_factory,
):
    db = integration_session_factory()
    monitor = PopupUrlMonitor(
        name="partial-run",
        url="https://pcmap.place.naver.com/popupstore/list",
        request_profile="A",
        fallback_strategy="reinforce",
        proxy_enabled=False,
        notify_on_new=False,
        min_new_count=1,
        monitoring_mode="anonymous",
        is_enabled=True,
    )
    db.add(monitor)
    db.commit()
    db.refresh(monitor)

    service = PopupMonitorService(
        fetcher=FakeFetcher(
            [
                PopupFetchResult(
                    success=True,
                    html=_build_apollo_html(
                        [
                            {
                                "popupId": "success-before-partial",
                                "title": "정상 팝업",
                            }
                        ]
                    ),
                    status=200,
                    final_url="https://pcmap.place.naver.com/popupstore/list",
                    request_profile="A",
                    proxy_url=None,
                    fallback_applied=False,
                ),
                PopupFetchResult(
                    success=True,
                    html=(
                        "<html><body><script>"
                        'window.__APOLLO_STATE__ = {"ROOT_QUERY": ]}'
                        "</script></body></html>"
                    ),
                    status=200,
                    final_url="https://pcmap.place.naver.com/popupstore/list",
                    request_profile="A",
                    proxy_url=None,
                    fallback_applied=False,
                ),
            ]
        ),
        notification_service=MagicMock(should_notify=MagicMock(return_value=False)),
    )

    first = await service.run_monitor_once(db, monitor, trigger="worker")
    second = await service.run_monitor_once(db, monitor, trigger="worker")

    assert first.status == "success"
    assert second.status == "partial"
    assert second.error_message.startswith("apollo_json_decode_error:")

    runs_payload = service.list_runs_payload(db, monitor.id, limit=10)
    assert [run["status"] for run in runs_payload] == ["partial", "success"]
    assert runs_payload[0]["snapshot"]["items"] == []
    assert runs_payload[0]["snapshot"]["diff"]["new_count"] == 0
    db.close()


@pytest.mark.asyncio
async def test_place_reservation_monitor_first_unavailable_run_saves_latest_baseline(
    integration_session_factory,
):
    db = integration_session_factory()
    monitor = PopupUrlMonitor(
        name="place-baseline",
        url="https://m.place.naver.com/popupstore/2015421037/home",
        monitor_kind="place_reservation",
        request_profile="A",
        fallback_strategy="reinforce",
        proxy_enabled=False,
        notify_on_new=False,
        min_new_count=1,
        stop_on_detected=True,
        monitoring_mode="anonymous",
        is_enabled=True,
    )
    db.add(monitor)
    db.commit()
    db.refresh(monitor)

    service = PopupMonitorService(
        fetcher=FakeFetcher(
            [
                PopupFetchResult(
                    success=True,
                    html=_build_place_reservation_html(),
                    status=200,
                    final_url=monitor.url,
                    request_profile="A",
                    proxy_url=None,
                    fallback_applied=False,
                )
            ]
        ),
        notification_service=MagicMock(should_notify=MagicMock(return_value=False)),
    )

    outcome = await service.run_monitor_once(db, monitor, trigger="manual")
    db.refresh(monitor)
    latest_payload = service.get_latest_payload(db, monitor.id)

    assert outcome.status == "success"
    assert outcome.has_new is False
    assert monitor.is_enabled is True
    assert monitor.detected_at is None
    assert latest_payload["item_count"] == 0
    assert latest_payload["snapshot"]["reservation_state"]["available"] is False
    assert latest_payload["snapshot"]["meta"]["monitor_kind"] == "place_reservation"
    db.close()


@pytest.mark.asyncio
async def test_place_reservation_monitor_false_to_true_disables_and_notifies(
    integration_session_factory,
):
    db = integration_session_factory()
    monitor = PopupUrlMonitor(
        name="place-transition",
        url="https://m.place.naver.com/popupstore/2015421037/home",
        monitor_kind="place_reservation",
        request_profile="A",
        fallback_strategy="reinforce",
        proxy_enabled=False,
        notify_on_new=True,
        min_new_count=1,
        stop_on_detected=True,
        monitoring_mode="anonymous",
        is_enabled=True,
    )
    db.add(monitor)
    db.commit()
    db.refresh(monitor)

    notification = MagicMock()
    notification.should_notify.return_value = True
    notification.send_notification_message = AsyncMock()
    service = PopupMonitorService(
        fetcher=FakeFetcher(
            [
                PopupFetchResult(
                    success=True,
                    html=_build_place_reservation_html(),
                    status=200,
                    final_url=monitor.url,
                    request_profile="A",
                    proxy_url=None,
                    fallback_applied=False,
                ),
                PopupFetchResult(
                    success=True,
                    html=_build_place_reservation_html(
                        booking_business_id="1643675",
                        booking_url="https://booking.naver.com/booking/6/bizes/1643675/search",
                    ),
                    status=200,
                    final_url=monitor.url,
                    request_profile="A",
                    proxy_url=None,
                    fallback_applied=False,
                ),
            ]
        ),
        notification_service=notification,
    )

    first = await service.run_monitor_once(db, monitor, trigger="manual")
    second = await service.run_monitor_once(db, monitor, trigger="worker")
    db.refresh(monitor)

    assert first.has_new is False
    assert second.has_new is True
    assert second.new_count >= 1
    assert monitor.is_enabled is False
    assert monitor.detected_at is not None
    latest_payload = service.get_latest_payload(db, monitor.id)
    assert latest_payload["snapshot"]["reservation_state"]["available"] is True
    notification.send_notification_message.assert_called_once()
    db.close()


@pytest.mark.asyncio
async def test_place_reservation_monitor_stop_on_detected_false_keeps_enabled(
    integration_session_factory,
):
    db = integration_session_factory()
    monitor = PopupUrlMonitor(
        name="place-no-stop",
        url="https://m.place.naver.com/popupstore/2015421037/home",
        monitor_kind="place_reservation",
        request_profile="A",
        fallback_strategy="reinforce",
        proxy_enabled=False,
        notify_on_new=False,
        min_new_count=1,
        stop_on_detected=False,
        monitoring_mode="anonymous",
        is_enabled=True,
    )
    db.add(monitor)
    db.commit()
    db.refresh(monitor)

    service = PopupMonitorService(
        fetcher=FakeFetcher(
            [
                PopupFetchResult(
                    success=True,
                    html=_build_place_reservation_html(),
                    status=200,
                    final_url=monitor.url,
                    request_profile="A",
                    proxy_url=None,
                    fallback_applied=False,
                ),
                PopupFetchResult(
                    success=True,
                    html=_build_place_reservation_html(booking_business_id="1643675"),
                    status=200,
                    final_url=monitor.url,
                    request_profile="A",
                    proxy_url=None,
                    fallback_applied=False,
                ),
            ]
        ),
        notification_service=MagicMock(should_notify=MagicMock(return_value=False)),
    )

    await service.run_monitor_once(db, monitor, trigger="manual")
    outcome = await service.run_monitor_once(db, monitor, trigger="manual")
    db.refresh(monitor)

    assert outcome.has_new is True
    assert monitor.is_enabled is True
    assert monitor.detected_at is None
    db.close()


@pytest.mark.asyncio
async def test_place_reservation_monitor_older_run_cannot_overwrite_detected_latest(
    integration_session_factory,
    monkeypatch,
):
    db = integration_session_factory()
    detected_at = datetime(2026, 5, 6, 10, 0, 5)
    latest_snapshot = {
        "reservation_state": {
            "available": True,
            "signals": [{"kind": "booking_business_id", "path": "state", "value": "1643675"}],
            "booking_business_id": "1643675",
            "booking_url": None,
            "ticket_count": 0,
            "concrete_links": [],
        },
        "signals": [{"kind": "booking_business_id", "path": "state", "value": "1643675"}],
        "meta": {"monitor_kind": "place_reservation"},
        "diff": {"previous_available": False, "available": True, "new_count": 1, "has_new": True},
    }
    monitor = PopupUrlMonitor(
        name="place-late-writer",
        url="https://m.place.naver.com/popupstore/2015421037/home",
        monitor_kind="place_reservation",
        request_profile="A",
        fallback_strategy="reinforce",
        proxy_enabled=False,
        notify_on_new=False,
        min_new_count=1,
        stop_on_detected=True,
        monitoring_mode="anonymous",
        is_enabled=False,
        detected_at=detected_at,
        latest_snapshot_json=json.dumps(latest_snapshot, ensure_ascii=False),
        latest_snapshot_hash="detected-hash",
        latest_checked_at=datetime(2026, 5, 6, 10, 0, 0),
    )
    db.add(monitor)
    db.commit()
    db.refresh(monitor)

    service = PopupMonitorService(
        fetcher=FakeFetcher(
            [
                PopupFetchResult(
                    success=True,
                    html=_build_place_reservation_html(),
                    status=200,
                    final_url=monitor.url,
                    request_profile="A",
                    proxy_url=None,
                    fallback_applied=False,
                )
            ]
        ),
        notification_service=MagicMock(should_notify=MagicMock(return_value=False)),
    )

    class OrderedDatetime(datetime):
        calls = [
            datetime(2026, 5, 6, 9, 59, 0),
            datetime(2026, 5, 6, 10, 1, 0),
        ]

        @classmethod
        def now(cls, tz=None):
            value = cls.calls.pop(0)
            if tz is not None:
                return value.replace(tzinfo=tz)
            return value

    monkeypatch.setattr(monitor_service_module, "datetime", OrderedDatetime)

    outcome = await service.run_monitor_once(db, monitor, trigger="worker")
    db.refresh(monitor)
    latest_payload = service.get_latest_payload(db, monitor.id)

    assert outcome.status == "success"
    assert monitor.detected_at == detected_at
    assert monitor.latest_snapshot_hash == "detected-hash"
    assert latest_payload["snapshot"]["reservation_state"]["available"] is True
    db.close()


@pytest.mark.asyncio
async def test_place_reservation_monitor_notify_off_still_stops_on_detected(
    integration_session_factory,
):
    db = integration_session_factory()
    monitor = PopupUrlMonitor(
        name="place-notify-off",
        url="https://m.place.naver.com/popupstore/2015421037/home",
        monitor_kind="place_reservation",
        request_profile="A",
        fallback_strategy="reinforce",
        proxy_enabled=False,
        notify_on_new=False,
        min_new_count=1,
        stop_on_detected=True,
        monitoring_mode="anonymous",
        is_enabled=True,
    )
    db.add(monitor)
    db.commit()
    db.refresh(monitor)

    notification = MagicMock()
    notification.should_notify.return_value = True
    notification.send_notification_message = AsyncMock()
    service = PopupMonitorService(
        fetcher=FakeFetcher(
            [
                PopupFetchResult(
                    success=True,
                    html=_build_place_reservation_html(),
                    status=200,
                    final_url=monitor.url,
                    request_profile="A",
                    proxy_url=None,
                    fallback_applied=False,
                ),
                PopupFetchResult(
                    success=True,
                    html=_build_place_reservation_html(booking_business_id="1643675"),
                    status=200,
                    final_url=monitor.url,
                    request_profile="A",
                    proxy_url=None,
                    fallback_applied=False,
                ),
            ]
        ),
        notification_service=notification,
    )

    await service.run_monitor_once(db, monitor, trigger="manual")
    outcome = await service.run_monitor_once(db, monitor, trigger="manual")
    db.refresh(monitor)

    assert outcome.has_new is True
    assert monitor.is_enabled is False
    assert monitor.detected_at is not None
    notification.send_notification_message.assert_not_called()
    db.close()
