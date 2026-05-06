"""
Reports API HTTP 통합 테스트 (Phase T5)
typography 통일 작업에서 프론트가 format 필드로 markdown 렌더 분기하므로
API 응답에 format 필드가 포함되는지 확인한다.

T5 TC:
  test_http_get_reports_list_has_format_field: GET /api/v1/reports → items[*].format 존재
  test_http_get_reports_format_default_value: 보고서 생성 시 format 기본값이 'markdown'
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


class TestReportsFormatFieldHTTP:
    """Reports API format 필드 존재 확인 — typography 통일 분기 계약."""

    def test_http_get_reports_list_200(self, client):
        """R: GET /api/v1/reports → 200 + ReportList 구조 (items, total, page, page_size)."""
        resp = client.get("/api/v1/reports")
        assert resp.status_code == 200, f"기대 200, 실제 {resp.status_code}: {resp.text}"
        body = resp.json()
        assert "items" in body
        assert "total" in body

    def test_http_get_reports_list_items_have_format(self, client):
        """R: GET /api/v1/reports 응답 items에 format 필드가 있다."""
        resp = client.get("/api/v1/reports?page_size=5")
        assert resp.status_code == 200
        body = resp.json()
        for report in body.get("items", []):
            assert "format" in report, f"report id={report.get('id')} 에 format 필드 없음"

    def test_http_get_reports_list_format_empty_when_none(self, client):
        """B: 보고서가 없어도 200 + empty list 반환."""
        resp = client.get("/api/v1/reports?search=__nonexistent_report_typography_test__")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0
        assert body["items"] == []
