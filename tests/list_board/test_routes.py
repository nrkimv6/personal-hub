"""List Board routes response schema TC (FastAPI TestClient)."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, JSON
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import Base, get_db
from app.modules.list_board.models import ListBoardItem, ListBoardColumn


def _patch_jsonb():
    ListBoardItem.__table__.c.properties.type = JSON()
    ListBoardColumn.__table__.c.options.type = JSON()


@pytest.fixture
def client():
    _patch_jsonb()
    # StaticPool: 모든 연결이 동일한 in-memory DB 공유 (SQLite :memory: 격리 방지)
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # 필요한 테이블만 생성 (전체 create_all은 SQLite에서 복잡한 FK 순서로 일부 누락 가능)
    ListBoardItem.__table__.create(engine)
    ListBoardColumn.__table__.create(engine)
    TestSession = sessionmaker(bind=engine)

    def override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    from app.main import app
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    ListBoardItem.__table__.drop(engine)
    ListBoardColumn.__table__.drop(engine)


def test_import_returns_result_schema(client):
    res = client.post("/api/v1/list-board/import", json={
        "markdown_text": "| Title | Duration |\n|---|---|\n| [Course A](https://example.com/a) | 30 minutes |",
        "source": "test",
    })
    assert res.status_code == 200
    data = res.json()
    assert "created" in data
    assert "updated" in data
    assert "skipped" in data
    assert "errors" in data
    assert data["created"] == 1


def test_list_items_returns_schema(client):
    client.post("/api/v1/list-board/import", json={
        "markdown_text": "| Title | Duration |\n|---|---|\n| [Course A](https://example.com/a) | 45 minutes |",
        "source": "src1",
        "badge_type": "Skill Badge",
    })
    res = client.get("/api/v1/list-board/items")
    assert res.status_code == 200
    data = res.json()
    assert "items" in data
    assert "total" in data
    assert data["total"] == 1
    assert data["items"][0]["source"] == "src1"


def test_list_items_filter_by_source(client):
    for i, src in enumerate(["alpha", "beta"]):
        client.post("/api/v1/list-board/import", json={
            "markdown_text": f"| Title | Duration |\n|---|---|\n| [C{i}](https://example.com/{i}) | 30 minutes |",
            "source": src,
        })
    res = client.get("/api/v1/list-board/items?source=alpha")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert data["items"][0]["source"] == "alpha"
