"""T5 HTTP: LLM grouped-by-caller 엔드포인트 통합 테스트."""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import get_db
from app.models.base import Base
from app.modules.claude_worker.models.llm_request import LLMRequest

pytestmark = pytest.mark.http

SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def client():
    Base.metadata.create_all(bind=engine)
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db():
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


def _seed(db, caller_type, caller_id, status, minutes_ago=5):
    req = LLMRequest(
        caller_type=caller_type,
        caller_id=caller_id,
        prompt="test",
        status=status,
        requested_at=datetime.now() - timedelta(minutes=minutes_ago),
    )
    db.add(req)
    db.commit()
    return req


class TestGroupedByCallerEndpoint:
    def test_grouped_R_200_schema(self, client, db):
        """GET /api/v1/llm/requests/grouped-by-caller 200 + 스키마 필드 존재."""
        app.dependency_overrides[get_db] = override_get_db
        _seed(db, "typeA", "id1", "failed")
        _seed(db, "typeB", "id2", "completed")

        resp = client.get("/api/v1/llm/requests/grouped-by-caller")

        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body
        assert "total" in body
        assert "page" in body
        assert "pages" in body
        assert "summary" in body
        summary = body["summary"]
        assert "total_callers" in summary
        assert "callers_with_success" in summary
        assert "callers_without_success" in summary

    def test_grouped_R_filter_params(self, client, db):
        """only_without_success=true, caller_type, page, page_size 조합 200."""
        app.dependency_overrides[get_db] = override_get_db
        _seed(db, "typeA", "id1", "failed")
        _seed(db, "typeA", "id2", "failed")
        _seed(db, "typeB", "id3", "completed")

        resp = client.get(
            "/api/v1/llm/requests/grouped-by-caller",
            params={"only_without_success": "true", "caller_type": "typeA", "page": 1, "page_size": 2},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        for item in body["items"]:
            assert item["caller_type"] == "typeA"
            assert item["has_success"] is False
