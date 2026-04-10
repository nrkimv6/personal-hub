"""
PG 아카이브 검색 API HTTP 통합 테스트 (Phase T5)

T5 TC:
  test_http_get_instagram_archive_posts_200: GET /api/v1/instagram/posts/archive → 200
  test_http_get_instagram_archive_posts_empty: 데이터 없을 때 200 + empty list
  test_http_get_monitoring_events_archive_200: GET /api/v1/monitoring/events/archive → 200
  test_http_get_monitoring_events_archive_filter: schedule_id 필터 동작
"""
import os
import pytest
from fastapi.testclient import TestClient

os.environ["TESTING"] = "1"

pytestmark = pytest.mark.http


@pytest.fixture(scope="module")
def client():
    from app.main import app
    from app.database import get_db
    from sqlalchemy.orm import sessionmaker
    from app.core.database import engine as pg_engine, is_pg

    if not is_pg:
        pytest.skip("PostgreSQL 전용 테스트")

    PgSession = sessionmaker(autocommit=False, autoflush=False, bind=pg_engine)

    def override_get_db():
        db = PgSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


class TestInstagramArchiveHTTP:
    """GET /api/v1/instagram/posts/archive HTTP 통합 테스트."""

    def test_http_get_instagram_archive_posts_200(self, client):
        """R: GET /api/v1/instagram/posts/archive → 200 + PostListResponse 구조."""
        resp = client.get("/api/v1/instagram/posts/archive")
        assert resp.status_code == 200, f"기대 200, 실제 {resp.status_code}: {resp.text}"
        body = resp.json()
        assert "posts" in body
        assert "total" in body
        assert "page" in body
        assert "limit" in body

    def test_http_get_instagram_archive_posts_empty(self, client):
        """B: 존재하지 않는 account 필터 → 200 + empty list."""
        resp = client.get("/api/v1/instagram/posts/archive?account=__nonexistent_test_account__")
        assert resp.status_code == 200, f"기대 200, 실제 {resp.status_code}: {resp.text}"
        body = resp.json()
        assert "posts" in body
        assert body["total"] == 0
        assert body["posts"] == []


class TestMonitoringEventsArchiveHTTP:
    """GET /api/v1/monitoring/events/archive HTTP 통합 테스트."""

    def test_http_get_monitoring_events_archive_200(self, client):
        """R: GET /api/v1/monitoring/events/archive → 200 + MonitoringEventList 구조."""
        resp = client.get("/api/v1/monitoring/events/archive")
        assert resp.status_code == 200, f"기대 200, 실제 {resp.status_code}: {resp.text}"
        body = resp.json()
        assert "items" in body
        assert "total" in body
        assert "page" in body
        assert "page_size" in body
        assert "total_pages" in body

    def test_http_get_monitoring_events_archive_filter(self, client):
        """B: schedule_id=99999 필터 → 200 + 결과 0건."""
        resp = client.get("/api/v1/monitoring/events/archive?schedule_id=99999")
        assert resp.status_code == 200, f"기대 200, 실제 {resp.status_code}: {resp.text}"
        body = resp.json()
        assert body["total"] == 0
        assert body["items"] == []
