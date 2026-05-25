"""Tests for eventus_reservation HTTP routes.

Uses an in-memory SQLite DB and mocked EventusAnalyzer / _adapter
so no real HTTP calls are made.
"""

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
from app.models.recurring_rule import RecurringRule
from app.routes import monitoring_events
from app.modules.availability.types import AvailabilityCheckResult, AvailabilitySlot
from app.modules.eventus_reservation.services.analyzer import EventusAnalyzeResult
from app.modules.eventus_reservation.services.html_parser import EventusSlot
from app.modules.eventus_reservation.routes import monitor as monitor_routes

_SOURCE_URL = "https://event-us.kr/age20scoffee/event/126341"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def eventus_http_context(monkeypatch):
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
    test_app = FastAPI()
    test_app.dependency_overrides[get_db] = override_get_db
    test_app.include_router(monitor_routes.router)
    test_app.include_router(monitoring_events.router)

    with TestClient(test_app) as client:
        yield client, factory

    engine.dispose()


@pytest.fixture(autouse=True)
def clean(eventus_http_context):
    _, factory = eventus_http_context
    db = factory()
    try:
        db.execute(text("DELETE FROM monitoring_events"))
        db.execute(text("DELETE FROM monitor_schedules"))
        db.execute(text("DELETE FROM biz_items"))
        db.execute(text("DELETE FROM businesses"))
        db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_target(client: TestClient) -> dict:
    response = client.post(
        "/api/v1/eventus/targets",
        json={
            "source_url": _SOURCE_URL,
            "name": "20대 커피챗 이벤트",
            "event_id": "126341",
            "organizer_slug": "age20scoffee",
            "channel_name": "Age20s Coffee",
            "bundle_ids": ["bundle_morning_A", "bundle_afternoon_B"],
            "selected_bundle_id": "bundle_morning_A",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_schedule(client: TestClient, target_id: int, date: str = "2026-06-01") -> int:
    response = client.post(
        "/api/v1/eventus/schedules",
        json={"biz_item_id": target_id, "dates": [date]},
    )
    assert response.status_code == 201
    assert response.json()["created"] == 1
    schedules = client.get("/api/v1/eventus/schedules").json()
    return schedules[0]["id"]


# ---------------------------------------------------------------------------
# Target CRUD
# ---------------------------------------------------------------------------

def test_create_eventus_target_RIGHT_creates_business_and_biz_item(eventus_http_context):
    """R: target 생성 → Business(service_type='eventus') + BizItem(extra_desc_json) 생성."""
    client, factory = eventus_http_context
    target = _create_target(client)

    assert target["event_id"] == "126341"
    assert target["selected_bundle_id"] == "bundle_morning_A"
    assert target["source_url"] == _SOURCE_URL

    db = factory()
    try:
        business = db.query(Business).filter(Business.service_type == "eventus").one()
        item = db.query(BizItem).one()
        assert business.business_id == "eventus:126341"
        extra = json.loads(item.extra_desc_json)
        assert extra["event_id"] == "126341"
        assert extra["organizer_slug"] == "age20scoffee"
        assert extra["selected_bundle_id"] == "bundle_morning_A"
    finally:
        db.close()


def test_list_eventus_targets_RIGHT_returns_registered_target(eventus_http_context):
    """R: GET /targets → 등록된 target 반환."""
    client, _ = eventus_http_context
    target = _create_target(client)

    response = client.get("/api/v1/eventus/targets")

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["id"] == target["id"]
    assert response.json()[0]["source_url"] == _SOURCE_URL


def test_delete_eventus_target_RIGHT_removes_target_and_related_schedules(eventus_http_context):
    """R: target 삭제 → 연관 schedule도 제거."""
    client, _ = eventus_http_context
    target = _create_target(client)
    _create_schedule(client, target["id"])

    response = client.delete(f"/api/v1/eventus/targets/{target['id']}")

    assert response.status_code == 200
    assert client.get("/api/v1/eventus/targets").json() == []
    assert client.get("/api/v1/eventus/schedules").json() == []


def test_delete_eventus_target_BOUNDARY_not_found_returns_404(eventus_http_context):
    """B: 존재하지 않는 target 삭제 → 404."""
    client, _ = eventus_http_context
    response = client.delete("/api/v1/eventus/targets/9999")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Schedule CRUD
# ---------------------------------------------------------------------------

def test_create_eventus_schedule_RIGHT_sets_date_and_enabled_state(eventus_http_context):
    """R: 스케줄 생성 → date/is_enabled/event_id/selected_bundle_id 반환."""
    client, _ = eventus_http_context
    target = _create_target(client)
    schedule_id = _create_schedule(client, target["id"])

    schedule = client.get(f"/api/v1/eventus/schedules/{schedule_id}/status").json()

    assert schedule["date"] == "2026-06-01"
    assert schedule["is_enabled"] is True
    assert schedule["event_id"] == "126341"
    assert schedule["selected_bundle_id"] == "bundle_morning_A"


def test_list_schedules_RIGHT_returns_last_event_status(eventus_http_context):
    """R: GET /schedules → last_event_status/last_event_at 포함."""
    client, factory = eventus_http_context
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
                timestamp=datetime(2026, 5, 25, 10, 0),
            )
        )
        db.commit()
    finally:
        db.close()

    schedule = client.get("/api/v1/eventus/schedules").json()[0]

    assert schedule["last_event_status"] == "no_slots"
    assert "2026-05-25T10:00:00" in schedule["last_event_at"]


def test_toggle_eventus_schedule_RIGHT_enable_disable_roundtrip(eventus_http_context):
    """R: disable → enable 라운드트립 정상 동작."""
    client, _ = eventus_http_context
    target = _create_target(client)
    schedule_id = _create_schedule(client, target["id"])

    disabled = client.post(f"/api/v1/eventus/schedules/{schedule_id}/disable").json()
    enabled = client.post(f"/api/v1/eventus/schedules/{schedule_id}/enable").json()

    assert disabled["is_enabled"] is False
    assert enabled["is_enabled"] is True


def test_delete_eventus_schedule_RIGHT_removes_schedule_without_deleting_target(eventus_http_context):
    """R: 스케줄 삭제 → target은 유지."""
    client, _ = eventus_http_context
    target = _create_target(client)
    schedule_id = _create_schedule(client, target["id"])

    response = client.delete(f"/api/v1/eventus/schedules/{schedule_id}")

    assert response.status_code == 200
    assert client.get("/api/v1/eventus/schedules").json() == []
    assert client.get("/api/v1/eventus/targets").json()[0]["id"] == target["id"]


# ---------------------------------------------------------------------------
# Analyze endpoint
# ---------------------------------------------------------------------------

def test_analyze_RIGHT_returns_meta_from_mocked_analyzer(eventus_http_context, monkeypatch):
    """R: POST /analyze → mocked analyzer 결과 반환."""
    client, _ = eventus_http_context

    fake_result = EventusAnalyzeResult(
        event_id="126341",
        source_url=_SOURCE_URL,
        organizer_slug="age20scoffee",
        channel_name="Age20s Coffee",
        title="20대 커피챗",
        bundles=["bundle_morning_A", "bundle_afternoon_B"],
        slots=[
            EventusSlot(
                bundle_id="bundle_morning_A",
                time_label="6/1 09:00~11:00",
                is_closed=True,
                closed_text="모집마감",
            )
        ],
        closed_token_counts=5,
        fetch_method="anonymous_html",
    )

    class FakeAnalyzer:
        async def analyze(self, inp):
            return fake_result

    monkeypatch.setattr(monitor_routes, "_analyzer", FakeAnalyzer())

    response = client.post("/api/v1/eventus/analyze", json={"input": _SOURCE_URL})

    assert response.status_code == 200
    data = response.json()
    assert data["event_id"] == "126341"
    assert data["title"] == "20대 커피챗"
    assert "bundle_morning_A" in data["bundles"]
    assert data["closed_token_counts"] == 5
    assert data["error_code"] is None
    assert len(data["slots"]) == 1
    assert data["slots"][0]["bundle_id"] == "bundle_morning_A"
    assert data["slots"][0]["is_closed"] is True


def test_analyze_invalid_input_returns_400(eventus_http_context):
    """E: 잘못된 URL 입력 → 400."""
    client, _ = eventus_http_context

    response = client.post(
        "/api/v1/eventus/analyze",
        json={"input": "https://example.com/not/eventus"},
    )

    assert response.status_code == 400


def test_analyze_event_id_only_returns_200_with_error_code(eventus_http_context, monkeypatch):
    """R: event_id 단독 입력 → analyzer가 error_code='event_id_resolver_error' 반환."""
    client, _ = eventus_http_context

    fake_result = EventusAnalyzeResult(
        event_id="126341",
        source_url=None,
        organizer_slug=None,
        channel_name=None,
        title=None,
        error_code="event_id_resolver_error",
        error_message="Cannot construct canonical URL from event_id=126341 alone",
        fetch_method="anonymous_html",
    )

    class FakeAnalyzer:
        async def analyze(self, inp):
            return fake_result

    monkeypatch.setattr(monitor_routes, "_analyzer", FakeAnalyzer())

    response = client.post("/api/v1/eventus/analyze", json={"input": "126341"})

    assert response.status_code == 200
    assert response.json()["error_code"] == "event_id_resolver_error"


# ---------------------------------------------------------------------------
# Check-now
# ---------------------------------------------------------------------------

def test_check_now_RIGHT_records_no_slots_event(eventus_http_context, monkeypatch):
    """R: check-now → no_slots 이벤트 기록 + last_event_status 갱신."""
    client, _ = eventus_http_context
    target = _create_target(client)
    schedule_id = _create_schedule(client, target["id"])

    class FakeAdapter:
        async def check(self, **kwargs):
            return AvailabilityCheckResult(
                source_type="eventus",
                slots=[
                    AvailabilitySlot(
                        source_type="eventus",
                        available_count=0,
                        raw={"sourceType": "eventus", "bundleId": "bundle_morning_A"},
                    )
                ],
                fetch_method="anonymous_html",
            )

    monkeypatch.setattr(monitor_routes, "_adapter", FakeAdapter())

    response = client.post(f"/api/v1/eventus/schedules/{schedule_id}/check-now")

    assert response.status_code == 200
    assert response.json()["status"] == "no_slots"
    assert response.json()["available_count"] == 0

    schedule = client.get(f"/api/v1/eventus/schedules/{schedule_id}/status").json()
    assert schedule["last_event_status"] == "no_slots"


def test_check_now_RIGHT_records_available_event(eventus_http_context, monkeypatch):
    """R: check-now → available 이벤트 기록."""
    client, _ = eventus_http_context
    target = _create_target(client)
    schedule_id = _create_schedule(client, target["id"])

    class FakeAdapter:
        async def check(self, **kwargs):
            return AvailabilityCheckResult(
                source_type="eventus",
                slots=[
                    AvailabilitySlot(
                        source_type="eventus",
                        available_count=1,
                        raw={
                            "sourceType": "eventus",
                            "bundleId": "bundle_morning_A",
                            "availableCountKnown": False,
                            "urgencyHint": None,
                        },
                    )
                ],
                fetch_method="anonymous_html",
            )

    monkeypatch.setattr(monitor_routes, "_adapter", FakeAdapter())

    response = client.post(f"/api/v1/eventus/schedules/{schedule_id}/check-now")

    assert response.status_code == 200
    assert response.json()["status"] == "available"
    assert response.json()["available_count"] >= 1


def test_check_now_BOUNDARY_missing_source_url_returns_400(eventus_http_context, monkeypatch):
    """B: extra_desc_json에 source_url 없는 schedule → check-now 400."""
    client, factory = eventus_http_context

    # create a Business/BizItem/MonitorSchedule with empty extra_desc_json directly
    db = factory()
    try:
        biz = Business(
            business_id="eventus:no-url",
            name="no-url",
            service_type="eventus",
        )
        db.add(biz)
        db.flush()
        item = BizItem(
            business_id=biz.id,
            biz_item_id="eventus:no-url",
            name="no url item",
            base_url=None,
            extra_desc_json="{}",
        )
        db.add(item)
        db.flush()
        schedule = MonitorSchedule(biz_item_id=item.id, date="2026-06-01", is_enabled=True)
        db.add(schedule)
        db.commit()
        schedule_id = schedule.id
    finally:
        db.close()

    response = client.post(f"/api/v1/eventus/schedules/{schedule_id}/check-now")
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# monitoring events service_type filter
# ---------------------------------------------------------------------------

def test_eventus_monitoring_events_RIGHT_service_type_filter_returns_only_eventus(eventus_http_context):
    """R: GET /monitoring/events?service_type=eventus → eventus 이벤트만 반환."""
    client, factory = eventus_http_context
    target = _create_target(client)
    eventus_schedule_id = _create_schedule(client, target["id"], "2026-05-25")

    db = factory()
    try:
        naver_biz = Business(
            business_id="naver:999",
            name="네이버 대상",
            service_type="naver",
        )
        db.add(naver_biz)
        db.flush()
        naver_item = BizItem(
            business_id=naver_biz.id,
            biz_item_id="naver-item-999",
            name="네이버 아이템",
        )
        db.add(naver_item)
        db.flush()
        naver_schedule = MonitorSchedule(
            biz_item_id=naver_item.id,
            date="2026-05-25",
            is_enabled=True,
        )
        db.add(naver_schedule)
        db.flush()
        db.add_all([
            MonitoringEvent(
                schedule_id=eventus_schedule_id,
                event_type="check",
                status="no_slots",
                available_count=0,
                timestamp=datetime(2026, 5, 25, 10, 0),
            ),
            MonitoringEvent(
                schedule_id=naver_schedule.id,
                event_type="check",
                status="available",
                available_count=1,
                timestamp=datetime(2026, 5, 25, 10, 1),
            ),
        ])
        db.commit()
    finally:
        db.close()

    response = client.get("/api/v1/monitoring/events?service_type=eventus")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["schedule_id"] == eventus_schedule_id
