"""T5 HTTP: LLM stats 엔드포인트 통합 테스트."""

from datetime import datetime

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


class TestStatsEndpoint:
    def test_stats_R_200_schema(self, client, db):
        """GET /api/v1/llm/stats 200 + 필수 키 존재 + 값 int."""
        app.dependency_overrides[get_db] = override_get_db
        for status in ["completed", "failed", "pending"]:
            req = LLMRequest(
                caller_type="t", caller_id="i", prompt="p",
                status=status, requested_at=datetime.now()
            )
            db.add(req)
        db.commit()

        resp = client.get("/api/v1/llm/stats")

        assert resp.status_code == 200
        body = resp.json()
        for key in ("total", "pending", "processing", "completed", "failed"):
            assert key in body, f"'{key}' missing in response"
            assert isinstance(body[key], int), f"'{key}' is not int"

        assert body["completed"] == 1
        assert body["failed"] == 1
        assert body["pending"] == 1
        assert body["total"] == 3

    def test_stats_B_empty(self, client, db):
        """빈 DB → 모든 값 0."""
        app.dependency_overrides[get_db] = override_get_db

        resp = client.get("/api/v1/llm/stats")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0
        assert body["pending"] == 0
        assert body["completed"] == 0
        assert body["failed"] == 0
