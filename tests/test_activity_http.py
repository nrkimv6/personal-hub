"""Activity API HTTP contract tests.

This file locks the /api/v1/activity source-of-truth contract and the
legacy /api/activity alias so monitoring callers cannot drift again.
"""

from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.activity import ActivityCenter, ActivityCourse, ActivityCrawlRun
from app.models.crawl_request import CrawlRequest
from app.modules.activity.routes import crawl as activity_crawl_routes


@pytest.fixture
def client(test_db_session):
    """FastAPI TestClient wired to the isolated test DB."""

    def override_get_db():
        yield test_db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def activity_seed(test_db_session):
    """Seed a small but representative activity dataset."""
    now = datetime.now()

    test_db_session.query(ActivityCourse).delete(synchronize_session=False)
    test_db_session.query(ActivityCrawlRun).delete(synchronize_session=False)
    test_db_session.query(CrawlRequest).delete(synchronize_session=False)
    test_db_session.query(ActivityCenter).delete(synchronize_session=False)
    test_db_session.commit()

    center = ActivityCenter(
        name="테스트 문화센터",
        center_type="public_city",
        region_sido="서울",
        region_sigungu="강남구",
        address="서울특별시 강남구 테헤란로 1",
        crawl_url="https://example.com/activity/center/1",
        crawl_method="static",
        is_active=True,
        created_at=now - timedelta(days=2),
        updated_at=now - timedelta(hours=1),
        last_crawled_at=now - timedelta(hours=3),
    )
    test_db_session.add(center)
    test_db_session.flush()

    course = ActivityCourse(
        center_id=center.id,
        source_id="course-001",
        source_url="https://example.com/activity/course/1",
        name="성인 필라테스",
        category="exercise",
        target_age="adult",
        fee=50000,
        course_start=date(2026, 4, 20),
        course_end=date(2026, 6, 30),
        day_of_week="월/수",
        time_start="18:30",
        time_end="19:30",
        instructor_name="김강사",
        status="active",
        collected_at=now - timedelta(hours=2),
    )

    pending_request = CrawlRequest(
        url=f"activity://center/{center.id}",
        url_type=CrawlRequest.URL_TYPE_ACTIVITY,
        status=CrawlRequest.STATUS_PENDING,
        requested_by="manual",
        requested_at=now - timedelta(minutes=10),
    )
    processing_request = CrawlRequest(
        url=f"activity://center/{center.id}",
        url_type=CrawlRequest.URL_TYPE_ACTIVITY,
        status=CrawlRequest.STATUS_PROCESSING,
        requested_by="manual",
        requested_at=now - timedelta(minutes=5),
        picked_at=now - timedelta(minutes=4),
        worker_id="worker-1",
    )

    recent_run = ActivityCrawlRun(
        center_id=center.id,
        started_at=now - timedelta(hours=2),
        completed_at=now - timedelta(hours=1, minutes=30),
        status=ActivityCrawlRun.STATUS_COMPLETED,
        courses_found=4,
        courses_new=2,
        courses_updated=1,
    )
    old_run = ActivityCrawlRun(
        center_id=center.id,
        started_at=now - timedelta(days=2),
        completed_at=now - timedelta(days=2, minutes=30),
        status=ActivityCrawlRun.STATUS_FAILED,
        courses_found=0,
        courses_new=0,
        courses_updated=0,
        error_message="old run",
    )

    test_db_session.add_all(
        [center, course, pending_request, processing_request, recent_run, old_run]
    )
    test_db_session.commit()
    test_db_session.refresh(center)
    test_db_session.refresh(course)
    test_db_session.refresh(pending_request)
    test_db_session.refresh(processing_request)
    test_db_session.refresh(recent_run)
    test_db_session.refresh(old_run)
    return {
        "center": center,
        "course": course,
        "pending_request": pending_request,
        "processing_request": processing_request,
        "recent_run": recent_run,
        "old_run": old_run,
    }


class TestActivityCentersContract:
    """센터 목록 contract."""

    def test_v1_centers_returns_items_total(self, client, activity_seed):
        response = client.get("/api/v1/activity/centers?page_size=100")
        assert response.status_code == 200

        data = response.json()
        assert set(data.keys()) == {"items", "total"}
        assert data["total"] == 1
        assert len(data["items"]) == 1

        item = data["items"][0]
        assert item["name"] == "테스트 문화센터"
        assert item["center_type"] == "public_city"
        assert item["region_sido"] == "서울"
        assert item["region_sigungu"] == "강남구"
        assert item["course_count"] == 1

    def test_v1_centers_accepts_max_page_size(self, client, activity_seed):
        response = client.get("/api/v1/activity/centers?page_size=100")
        assert response.status_code == 200
        assert response.json()["total"] == 1

    def test_v1_centers_rejects_page_size_over_limit(self, client, activity_seed):
        response = client.get("/api/v1/activity/centers?page_size=101")
        assert response.status_code == 422

    def test_legacy_centers_alias_matches_v1(self, client, activity_seed):
        v1 = client.get("/api/v1/activity/centers?page_size=100")
        legacy = client.get("/api/activity/centers?page_size=100")

        assert v1.status_code == 200
        assert legacy.status_code == 200
        assert legacy.json() == v1.json()


class TestActivityCoursesContract:
    """강좌 목록 contract."""

    def test_v1_courses_returns_paged_list(self, client, activity_seed):
        response = client.get("/api/v1/activity/courses?page_size=1")
        assert response.status_code == 200

        data = response.json()
        assert data["total"] == 1
        assert data["page"] == 1
        assert data["page_size"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["name"] == "성인 필라테스"
        assert data["items"][0]["center_name"] == "테스트 문화센터"
        assert data["items"][0]["category"] == "exercise"


class TestActivityWorkerContract:
    """워커 상태와 요청 contract."""

    def test_worker_status_reports_counts(self, client, activity_seed):
        response = client.get("/api/v1/activity/worker/status")
        assert response.status_code == 200

        data = response.json()
        assert data["is_running"] is True
        assert data["pending_requests"] == 1
        assert data["processing_requests"] == 1
        assert data["recent_runs"] == 1
        assert data["last_activity"] is not None

    def test_worker_requests_list_uses_limit(self, client, activity_seed):
        response = client.get("/api/v1/activity/worker/requests?limit=1")
        assert response.status_code == 200

        data = response.json()
        assert len(data) == 1
        assert data[0]["status"] == CrawlRequest.STATUS_PROCESSING
        assert data[0]["url"].startswith("activity://center/")

    def test_worker_request_creates_pending_request(self, client, activity_seed):
        response = client.post(
            "/api/v1/activity/worker/request",
            json={"center_id": activity_seed["center"].id},
        )
        assert response.status_code == 201

        data = response.json()
        assert data["url"] == f"activity://center/{activity_seed['center'].id}"
        assert data["status"] == CrawlRequest.STATUS_PENDING
        assert data["id"] is not None


class TestActivityCrawlContract:
    """크롤링/동기화 contract."""

    def test_sync_hub_returns_pending_status(self, client, activity_seed, monkeypatch):
        async def fake_push_all_centers_to_activity_hub():
            return None

        monkeypatch.setattr(
            activity_crawl_routes,
            "_push_all_centers_to_activity_hub",
            fake_push_all_centers_to_activity_hub,
        )

        response = client.post("/api/v1/activity/crawl/sync-hub")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "pending"
        assert "activity-hub" in data["message"]
