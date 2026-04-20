"""Expo API 계약 테스트."""

from __future__ import annotations

from datetime import date, datetime
from uuid import uuid4
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.auth import create_access_token
from app.core.config import settings
from app.database import get_db
from app.main import app
from app.models import CrawledPage, CrawlRequest, Event, InstagramWorkerStatus, Popup


@pytest.fixture
def admin_headers():
    token = create_access_token(email="admin@test.com", is_admin=True)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client(test_db_session):
    def override_get_db():
        try:
            yield test_db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def expo_test_env(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "ADMIN_TOOLS_BASE_URL", "")
    return tmp_path


def _make_payload():
    return {
        "version": "2026-04-20",
        "slug": "coffee-expo-2026",
        "title": "커피엑스포 2026",
        "exported_at": "2026-04-20T15:00:00+09:00",
        "booths": [
            {
                "id": "A-09",
                "name": "A-09",
                "pin": {
                    "xNorm": 0.12,
                    "yNorm": 0.34,
                },
            }
        ],
    }


def _seed_pipeline_rows(test_db_session):
    test_db_session.query(CrawledPage).delete()
    test_db_session.query(CrawlRequest).delete()
    test_db_session.query(InstagramWorkerStatus).delete()
    test_db_session.query(Event).delete()
    test_db_session.query(Popup).delete()
    test_db_session.commit()

    suffix = uuid4().hex[:8]
    event = Event(
        title=f"Expo Event {suffix}",
        event_type="event",
        event_start=date(2026, 4, 15),
        event_end=date(2026, 4, 18),
        source_type="manual",
    )
    popup = Popup(
        title=f"Expo Popup {suffix}",
        start_date=date(2026, 4, 15),
        end_date=date(2026, 4, 18),
        source_type="manual",
    )
    test_db_session.add_all([event, popup])
    test_db_session.flush()

    crawled_page = CrawledPage(
        url=f"https://example.com/expo-event-{suffix}",
        url_type="naver_blog",
        title="Expo Source",
        crawled_at=datetime(2026, 4, 20, 10, 0, 0),
        is_event=True,
        event_id=event.id,
        url_hash=f"expo-source-hash-{suffix}",
    )
    crawl_request = CrawlRequest(
        url=f"https://example.com/expo-event-{suffix}",
        url_type="naver_blog",
        status=CrawlRequest.STATUS_COMPLETED,
        requested_by="manual",
        requested_at=datetime(2026, 4, 20, 9, 0, 0),
        processed_at=datetime(2026, 4, 20, 9, 5, 0),
        result_type="crawled_page",
        result_id=1,
        result_status="created",
    )
    worker = InstagramWorkerStatus(
        worker_id=f"expo-worker-{suffix}",
        pid=3210,
        started_at=datetime(2026, 4, 20, 8, 0, 0),
        last_heartbeat=datetime(2026, 4, 20, 10, 0, 0),
        current_state="processing",
        is_alive=True,
    )
    test_db_session.add_all([crawled_page, crawl_request, worker])
    test_db_session.commit()


class TestExpoApi:
    def test_get_expo_pipeline_status_right_returns_seed_and_worker_summary(
        self, client, expo_test_env, test_db_session
    ):
        _seed_pipeline_rows(test_db_session)

        with patch(
            "app.modules.instagram.services.worker_status_service.WorkerHealthRedis.check",
            return_value={
                "source": "redis",
                "ttl_remaining": 20,
                "updated_at": datetime(2026, 4, 20, 10, 0, 0),
            },
        ):
            response = client.get("/api/v1/expo/coffee-expo-2026/pipeline-status")

        assert response.status_code == 200
        payload = response.json()
        assert payload["slug"] == "coffee-expo-2026"
        assert payload["booth_seed_count"] == 8
        assert payload["time_slot_count"] == 3
        assert payload["event_count"] == 1
        assert payload["popup_count"] == 1
        assert payload["worker"]["status"] == "healthy"
        assert payload["worker"]["current_state"] == "processing"

    def test_get_expo_pipeline_status_boundary_returns_unknown_publish_status_without_record(
        self, client, expo_test_env
    ):
        response = client.get("/api/v1/expo/coffee-expo-2026/pipeline-status")

        assert response.status_code == 200
        payload = response.json()
        assert payload["published_status"]["status"] == "unknown"
        assert payload["published_status"]["source"] == "fallback"
        assert payload["last_exported_at"] is None

    def test_post_expo_export_record_error_rejects_unknown_slug(self, client, expo_test_env, admin_headers):
        response = client.post(
            "/api/v1/expo/unknown/exports/record",
            json={**_make_payload(), "slug": "unknown"},
            headers=admin_headers,
        )

        assert response.status_code == 404

    def test_get_expo_collection_status_right_includes_recent_requests(
        self, client, expo_test_env, test_db_session
    ):
        _seed_pipeline_rows(test_db_session)

        with patch(
            "app.modules.instagram.services.worker_status_service.WorkerHealthRedis.check",
            return_value={
                "source": "redis",
                "ttl_remaining": 25,
                "updated_at": datetime(2026, 4, 20, 10, 0, 0),
            },
        ):
            response = client.get("/api/v1/expo/coffee-expo-2026/collection-status")

        assert response.status_code == 200
        payload = response.json()
        assert payload["recent_completed_requests"] == 1
        assert payload["failed_request_count"] == 0
        assert payload["pending_request_count"] == 0
        assert payload["recent_sources"][0]["match_status"] == "event"

    def test_get_expo_collection_status_boundary_handles_empty_history(
        self, client, expo_test_env, test_db_session
    ):
        test_db_session.query(CrawledPage).delete()
        test_db_session.query(CrawlRequest).delete()
        test_db_session.query(InstagramWorkerStatus).delete()
        test_db_session.commit()

        response = client.get("/api/v1/expo/coffee-expo-2026/collection-status")

        assert response.status_code == 200
        payload = response.json()
        assert payload["recent_completed_requests"] == 0
        assert payload["failed_request_count"] == 0
        assert payload["pending_request_count"] == 0
        assert payload["matching_pending_count"] == 0
        assert payload["recent_sources"] == []

    def test_post_expo_export_record_error_requires_admin(
        self, client, expo_test_env, mock_external_request
    ):
        response = client.post(
            "/api/v1/expo/coffee-expo-2026/exports/record",
            json=_make_payload(),
        )

        assert response.status_code == 401

    def test_post_expo_export_record_right_creates_record(self, client, expo_test_env, admin_headers):
        response = client.post(
            "/api/v1/expo/coffee-expo-2026/exports/record",
            json=_make_payload(),
            headers=admin_headers,
        )

        assert response.status_code == 201
        payload = response.json()
        assert payload["slug"] == "coffee-expo-2026"
        assert payload["booth_count"] == 1
        assert payload["exported_at"] == "2026-04-20T15:00:00+09:00"

    def test_get_expo_pipeline_status_error_returns_404_for_unknown_slug(self, client, expo_test_env):
        response = client.get("/api/v1/expo/unknown/pipeline-status")

        assert response.status_code == 404

    def test_get_expo_published_status_right_returns_shape(self, client, expo_test_env):
        response = client.get("/api/v1/expo/coffee-expo-2026/published-status")

        assert response.status_code == 200
        payload = response.json()
        assert payload["slug"] == "coffee-expo-2026"
        assert set(payload.keys()) >= {
            "slug",
            "status",
            "checked_at",
            "last_published_at",
            "admin_url",
            "source",
            "detail",
        }

    def test_post_expo_export_record_error_returns_422_for_invalid_payload(
        self, client, expo_test_env, admin_headers
    ):
        payload = _make_payload()
        payload["booths"] = []
        payload.pop("exported_at")

        response = client.post(
            "/api/v1/expo/coffee-expo-2026/exports/record",
            json=payload,
            headers=admin_headers,
        )

        assert response.status_code == 422
