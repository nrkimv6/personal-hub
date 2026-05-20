import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import get_db
from app.models.base import Base
from app.models.browser_profile import BrowserProfile
from app.models.popup_url_monitor import PopupUrlMonitor
from app.models.popup_url_monitor_run import PopupUrlMonitorRun
from app.models.service_account import ServiceAccount
from app.modules.naver_popup_monitor.routes import monitor as monitor_routes
from app.modules.naver_popup_monitor.services.fetcher import PopupFetchResult
from app.modules.naver_popup_monitor.services.monitor_service import PopupMonitorService


def _place_html(*, booking_business_id: str | None = None) -> str:
    apollo = {
        "ROOT_QUERY": {
            'placeDetail({"input":{"deviceType":"pc","id":"2015421037","isNx":false}})': {
                "__typename": "PlaceDetail",
                "naverBooking": {
                    "__typename": "PlaceDetailNaverBooking",
                    "bookingBusinessId": booking_business_id,
                    "naverBookingUrl": (
                        "https://booking.naver.com/booking/6/bizes/1643675/search"
                        if booking_business_id
                        else None
                    ),
                    "naverBookingHubUrl": None,
                    "bookingButtonName": "예약",
                },
                "tickets": {
                    "__typename": "TicketItemsResult",
                    "total": 0,
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


class SequenceFetcher:
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
def place_registration_context(monkeypatch):
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
    service = PopupMonitorService(
        fetcher=SequenceFetcher(
            [
                PopupFetchResult(
                    success=True,
                    html=_place_html(),
                    status=200,
                    final_url="https://m.place.naver.com/popupstore/2015421037/home",
                    request_profile="A",
                    proxy_url=None,
                    fallback_applied=False,
                ),
                PopupFetchResult(
                    success=True,
                    html=_place_html(booking_business_id="1643675"),
                    status=200,
                    final_url="https://m.place.naver.com/popupstore/2015421037/home",
                    request_profile="A",
                    proxy_url=None,
                    fallback_applied=False,
                ),
            ]
        ),
        notification_service=SimpleNamespace(should_notify=lambda state: False),
    )
    monkeypatch.setattr(monitor_routes, "monitor_service", service)

    app = FastAPI()

    def _override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(monitor_routes.router)

    with TestClient(app) as client:
        yield client, factory

    engine.dispose()


def test_place_reservation_registration_flow_T3_create_checknow_available_terminal(
    place_registration_context,
):
    client, _factory = place_registration_context
    create_res = client.post(
        "/api/v1/naver-popup/monitors",
        json={
            "name": "2015421037 reservation",
            "url": "https://map.naver.com/p/entry/place/2015421037",
            "monitor_kind": "place_reservation",
        },
    )
    assert create_res.status_code == 201
    monitor_id = create_res.json()["id"]
    assert create_res.json()["stop_on_detected"] is True

    first_res = client.post(f"/api/v1/naver-popup/monitors/{monitor_id}/check-now")
    assert first_res.status_code == 202
    assert first_res.json()["has_new"] is False

    second_res = client.post(f"/api/v1/naver-popup/monitors/{monitor_id}/check-now")
    assert second_res.status_code == 202
    assert second_res.json()["has_new"] is True

    monitor_res = client.get(f"/api/v1/naver-popup/monitors/{monitor_id}")
    assert monitor_res.status_code == 200
    monitor = monitor_res.json()
    assert monitor["is_enabled"] is False
    assert monitor["detected_at"] is not None

    latest = client.get(f"/api/v1/naver-popup/monitors/{monitor_id}/latest").json()
    assert latest["snapshot"]["reservation_state"]["available"] is True
    assert latest["last_run"]["id"] == second_res.json()["run_id"]


def test_place_reservation_registration_flow_T3_user_disable_excludes_worker_targets(
    place_registration_context,
):
    client, factory = place_registration_context
    create_res = client.post(
        "/api/v1/naver-popup/monitors",
        json={
            "name": "manual off",
            "url": "2015421037",
            "monitor_kind": "place_reservation",
        },
    )
    assert create_res.status_code == 201
    monitor_id = create_res.json()["id"]

    disable_res = client.post(f"/api/v1/naver-popup/monitors/{monitor_id}/disable")
    assert disable_res.status_code == 200
    assert disable_res.json()["is_enabled"] is False

    db = factory()
    try:
        enabled_ids = [
            row[0]
            for row in db.query(PopupUrlMonitor.id)
            .filter(PopupUrlMonitor.is_enabled.is_(True))
            .all()
        ]
    finally:
        db.close()

    assert monitor_id not in enabled_ids

