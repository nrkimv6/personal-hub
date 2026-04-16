"""
Integrity HTTP 통합 테스트 (T5)

GET /api/v1/integrity/check, /api/v1/integrity/stats 응답 계약을 검증한다.
"""
import os

import pytest
from fastapi.testclient import TestClient

os.environ["TESTING"] = "1"

pytestmark = pytest.mark.http


@pytest.fixture(scope="module")
def client():
    from sqlalchemy.orm import sessionmaker

    from app.main import app
    from app.database import get_db
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


class TestIntegrityHTTP:
    """Integrity API HTTP 통합 테스트."""

    def test_http_get_integrity_check_200(self, client):
        """R: GET /api/v1/integrity/check → 200 + 응답 구조 유지."""
        resp = client.get("/api/v1/integrity/check")

        assert resp.status_code == 200, f"기대 200, 실제 {resp.status_code}: {resp.text}"
        body = resp.json()
        assert "total_issues" in body
        assert "by_severity" in body
        assert "issues" in body
        assert {"critical", "warning", "info"} <= set(body["by_severity"].keys())
        assert isinstance(body["issues"], list)

    def test_http_get_integrity_stats_200(self, client):
        """R: GET /api/v1/integrity/stats → 200 + DB 통계 구조 유지."""
        resp = client.get("/api/v1/integrity/stats")

        assert resp.status_code == 200, f"기대 200, 실제 {resp.status_code}: {resp.text}"
        body = resp.json()
        assert "tables" in body
        assert "db_size_bytes" in body
        assert "db_size_mb" in body
        assert "businesses" in body["tables"]
        assert body["tables"]["businesses"] is None or isinstance(body["tables"]["businesses"], int)
        assert body["db_size_bytes"] >= 0
