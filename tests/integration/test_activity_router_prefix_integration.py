"""Activity router prefix integration tests.

These tests use the real FastAPI app to ensure activity routers remain
reachable under both /api/v1/activity and the legacy /api/activity alias.
"""

from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.activity import ActivityCenter, ActivityCourse, ActivityCrawlRun
from app.models.crawl_request import CrawlRequest


@pytest.fixture
def client(test_db_session):
    """App client with isolated DB."""

    def override_get_db():
        yield test_db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def seeded_activity(test_db_session):
    """Insert one activity center/course/run so both prefixes share data."""
    test_db_session.query(ActivityCourse).delete(synchronize_session=False)
    test_db_session.query(ActivityCrawlRun).delete(synchronize_session=False)
    test_db_session.query(CrawlRequest).delete(synchronize_session=False)
    test_db_session.query(ActivityCenter).delete(synchronize_session=False)
    test_db_session.commit()

    now = datetime.now()
    center = ActivityCenter(
        name="통합 테스트 센터",
        center_type="public_district",
        region_sido="부산",
        region_sigungu="해운대구",
        crawl_method="static",
        is_active=True,
        created_at=now - timedelta(days=1),
        updated_at=now - timedelta(hours=1),
        last_crawled_at=now - timedelta(hours=2),
    )
    test_db_session.add(center)
    test_db_session.flush()

    course = ActivityCourse(
        center_id=center.id,
        name="통합 테스트 강좌",
        category="hobby",
        course_start=date(2026, 4, 15),
        course_end=date(2026, 5, 15),
        collected_at=now - timedelta(minutes=30),
        status="active",
    )
    run = ActivityCrawlRun(
        center_id=center.id,
        started_at=now - timedelta(hours=3),
        completed_at=now - timedelta(hours=2, minutes=30),
        status=ActivityCrawlRun.STATUS_COMPLETED,
        courses_found=1,
        courses_new=1,
        courses_updated=0,
    )
    test_db_session.add_all([center, course, run])
    test_db_session.commit()
    return center


def test_activity_centers_prefixes_return_same_schema(client, seeded_activity):
    """Both prefixes should resolve to the same center list schema."""
    v1 = client.get("/api/v1/activity/centers?page_size=10")
    legacy = client.get("/api/activity/centers?page_size=10")

    assert v1.status_code == 200
    assert legacy.status_code == 200
    assert v1.json().keys() == legacy.json().keys()
    assert v1.json()["total"] == legacy.json()["total"] == 1
    assert v1.json()["items"][0]["name"] == "통합 테스트 센터"


def test_activity_prefix_smoke_endpoints(client, seeded_activity):
    """Smoke-test worker/courses endpoints on the versioned prefix."""
    worker_status = client.get("/api/v1/activity/worker/status")
    courses = client.get("/api/v1/activity/courses?page_size=1")

    assert worker_status.status_code == 200
    assert courses.status_code == 200
    assert worker_status.json()["is_running"] is False
    assert courses.json()["total"] == 1
    assert courses.json()["items"][0]["name"] == "통합 테스트 강좌"
