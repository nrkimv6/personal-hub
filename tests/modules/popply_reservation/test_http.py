import json
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import get_db
from app.models.base import Base
from app.models.business import Business
from app.models.biz_item import BizItem
from app.models.monitor_schedule import MonitorSchedule
from app.models.monitoring_event import MonitoringEvent
from app.models.proxy_usage import ProxyUsageLog
from app.routes import monitoring_events
from app.models.recurring_rule import RecurringRule
from app.modules.availability.types import AvailabilityCheckResult, AvailabilitySlot
from app.modules.popply_reservation.routes import monitor as monitor_routes


@pytest.fixture
def popply_http_context(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[
            Business.__table__,
            BizItem.__table__,
            RecurringRule.__table__,
            MonitorSchedule.__table__,
            MonitoringEvent.__table__,
            ProxyUsageLog.__table__,
        ],
    )
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=True)

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr("app.services.event_logger.SessionLocal", factory)
    app = FastAPI()
    app.dependency_overrides[get_db] = override_get_db
    app.include_router(monitor_routes.router)
    app.include_router(monitoring_events.router)

    with TestClient(app) as client:
        yield client, factory

    engine.dispose()


@pytest.fixture(autouse=True)
def clean(popply_http_context):
    _, factory = popply_http_context
    db = factory()
    try:
        db.execute(text("DELETE FROM monitoring_events"))
        db.execute(text("DELETE FROM monitor_schedules"))
        db.execute(text("DELETE FROM biz_items"))
        db.execute(text("DELETE FROM businesses"))
        db.commit()
    finally:
        db.close()


def _create_target(client: TestClient) -> dict:
    response = client.post(
        "/api/v1/popply/targets",
        json={
            "source_url": "https://popply.co.kr/popup/4727/reservation/pre/q%252Fabc%253D%253D",
            "name": "테스트 팝업",
        },
    )
    assert response.status_code == 201
    return response.json()


def _create_schedule(client: TestClient, target_id: int, date: str = "2026-06-01") -> int:
    response = client.post(
        "/api/v1/popply/schedules",
        json={"biz_item_id": target_id, "dates": [date]},
    )
    assert response.status_code == 201
    assert response.json()["created"] == 1
    schedules = client.get("/api/v1/popply/schedules").json()
    return schedules[0]["id"]


def test_create_popply_target_RIGHT_creates_business_and_biz_item(popply_http_context):
    client, factory = popply_http_context

    target = _create_target(client)

    assert target["store_id"] == "4727"
    assert target["schedule_group"] == "q%2Fabc%3D%3D"
    db = factory()
    try:
        business = db.query(Business).one()
        item = db.query(BizItem).one()
        assert business.service_type == "popply"
        assert item.base_url.startswith("https://popply.co.kr/popup/4727")
    finally:
        db.close()


def test_list_popply_targets_RIGHT_returns_registered_targets(popply_http_context):
    client, _ = popply_http_context
    target = _create_target(client)

    response = client.get("/api/v1/popply/targets")

    assert response.status_code == 200
    assert response.json()[0]["id"] == target["id"]
    assert response.json()[0]["source_url"].startswith("https://popply.co.kr")


def test_delete_popply_target_RIGHT_removes_target_and_related_schedules(popply_http_context):
    client, _ = popply_http_context
    target = _create_target(client)
    _create_schedule(client, target["id"])

    response = client.delete(f"/api/v1/popply/targets/{target['id']}")

    assert response.status_code == 200
    assert client.get("/api/v1/popply/targets").json() == []
    assert client.get("/api/v1/popply/schedules").json() == []


def test_create_popply_schedule_RIGHT_sets_date_group_and_enabled_state(popply_http_context):
    client, _ = popply_http_context
    target = _create_target(client)
    schedule_id = _create_schedule(client, target["id"])

    schedule = client.get(f"/api/v1/popply/schedules/{schedule_id}/status").json()

    assert schedule["date"] == "2026-06-01"
    assert schedule["schedule_group"] == "q%2Fabc%3D%3D"
    assert schedule["is_enabled"] is True


def test_list_popply_schedules_RIGHT_returns_status_and_latest_event(popply_http_context):
    client, factory = popply_http_context
    target = _create_target(client)
    schedule_id = _create_schedule(client, target["id"])
    db = factory()
    try:
        db.add(
            MonitoringEvent(
                schedule_id=schedule_id,
                event_type="check",
                status="no_slots",
                available_count=0,
                timestamp=datetime(2026, 5, 15, 9, 0),
            )
        )
        db.commit()
    finally:
        db.close()

    schedule = client.get("/api/v1/popply/schedules").json()[0]

    assert schedule["last_event_status"] == "no_slots"
    assert schedule["last_event_at"].startswith("2026-05-15T09:00:00")


def test_toggle_popply_schedule_RIGHT_enable_disable_roundtrip(popply_http_context):
    client, _ = popply_http_context
    target = _create_target(client)
    schedule_id = _create_schedule(client, target["id"])

    disabled = client.post(f"/api/v1/popply/schedules/{schedule_id}/disable").json()
    enabled = client.post(f"/api/v1/popply/schedules/{schedule_id}/enable").json()

    assert disabled["is_enabled"] is False
    assert enabled["is_enabled"] is True


def test_delete_popply_schedule_RIGHT_removes_schedule_without_deleting_target(popply_http_context):
    client, _ = popply_http_context
    target = _create_target(client)
    schedule_id = _create_schedule(client, target["id"])

    response = client.delete(f"/api/v1/popply/schedules/{schedule_id}")

    assert response.status_code == 200
    assert client.get("/api/v1/popply/schedules").json() == []
    assert client.get("/api/v1/popply/targets").json()[0]["id"] == target["id"]


def test_popply_item_4727_seed_target_and_schedule_RIGHT(popply_http_context):
    client, _ = popply_http_context
    target = client.post(
        "/api/v1/popply/targets",
        json={
            "source_url": "https://popply.co.kr/popup/4727/reservation/pre/q%252Fvz6hSqSFn1IMrEDVkTtDUvIPrnxtkqkn08sdn8T9EA7XyWkp5tej4hrzR0jbrmHagBNt3As8YgLwKGsTL89A%253D%253D",
            "name": "POPPLY 4727",
        },
    ).json()

    schedule_id = _create_schedule(client, target["id"])
    schedule = client.get(f"/api/v1/popply/schedules/{schedule_id}/status").json()

    assert target["store_id"] == "4727"
    assert target["reservation_type"] == "PRE"
    assert schedule["schedule_group"].startswith("q%2Fvz6h")


def test_popply_item_4727_check_now_records_no_slots_RIGHT(popply_http_context, monkeypatch):
    client, _ = popply_http_context
    target = _create_target(client)
    schedule_id = _create_schedule(client, target["id"])

    class FakeAdapter:
        async def check(self, **kwargs):
            return AvailabilityCheckResult(
                source_type="popply",
                slots=[
                    AvailabilitySlot(
                        source_type="popply",
                        available_count=0,
                        raw={"storeId": "4727", "scheduleGroup": "q%2Fabc%3D%3D"},
                    )
                ],
                fetch_method="anonymous_api",
            )

    monkeypatch.setattr(monitor_routes, "adapter", FakeAdapter())

    response = client.post(f"/api/v1/popply/schedules/{schedule_id}/check-now")
    schedule = client.get(f"/api/v1/popply/schedules/{schedule_id}/status").json()

    assert response.status_code == 200
    assert response.json()["status"] == "no_slots"
    assert response.json()["available_count"] == 0
    assert schedule["last_event_status"] == "no_slots"


def test_popply_monitoring_events_RIGHT_service_type_filter_returns_popply_events(popply_http_context):
    client, factory = popply_http_context
    target = _create_target(client)
    popply_schedule_id = _create_schedule(client, target["id"], "2026-05-16")

    db = factory()
    try:
        naver_business = Business(
            business_id="naver:1",
            name="네이버 대상",
            service_type="naver",
        )
        db.add(naver_business)
        db.flush()
        naver_item = BizItem(
            business_id=naver_business.id,
            biz_item_id="naver-item-1",
            name="네이버 아이템",
        )
        db.add(naver_item)
        db.flush()
        naver_schedule = MonitorSchedule(
            biz_item_id=naver_item.id,
            date="2026-05-16",
            is_enabled=True,
        )
        db.add(naver_schedule)
        db.flush()
        db.add_all(
            [
                MonitoringEvent(
                    schedule_id=popply_schedule_id,
                    event_type="check",
                    status="no_slots",
                    available_count=0,
                    timestamp=datetime(2026, 5, 15, 10, 0),
                ),
                MonitoringEvent(
                    schedule_id=naver_schedule.id,
                    event_type="check",
                    status="available",
                    available_count=1,
                    timestamp=datetime(2026, 5, 15, 10, 1),
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    response = client.get("/api/v1/monitoring/events?service_type=popply")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["schedule_id"] == popply_schedule_id
    assert payload["items"][0]["business_name"] == "테스트 팝업"


def test_popply_monitoring_events_RIGHT_preserves_slots_info_for_detail_modal(popply_http_context):
    client, factory = popply_http_context
    target = _create_target(client)
    schedule_id = _create_schedule(client, target["id"], "2026-05-17")

    slots_info = [
        {
            "sourceType": "popply",
            "storeId": "4727",
            "reservationDate": "2026-05-17",
            "reservationTime": "11:00",
            "reservationStartTime": "2026-05-17T11:00:00",
            "currentAvailableGuests": 0,
            "reservationScheduleId": 1001,
            "scheduleGroup": "q%2Fabc%3D%3D",
        }
    ]
    db = factory()
    try:
        db.add(
            MonitoringEvent(
                schedule_id=schedule_id,
                event_type="check",
                status="no_slots",
                available_count=0,
                slots_info=json.dumps(slots_info),
                response_time_ms=123.4,
                fetch_method="anonymous_api",
                timestamp=datetime(2026, 5, 15, 10, 30),
            )
        )
        db.commit()
    finally:
        db.close()

    response = client.get("/api/v1/monitoring/events?service_type=popply&page_size=5")

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["fetch_method"] == "anonymous_api"
    assert item["response_time_ms"] == 123.4
    assert isinstance(item["slots_info"], list)
    assert item["slots_info"][0]["sourceType"] == "popply"
    assert item["slots_info"][0]["reservationDate"] == "2026-05-17"
    assert item["slots_info"][0]["reservationTime"] == "11:00"
    assert item["slots_info"][0]["currentAvailableGuests"] == 0
