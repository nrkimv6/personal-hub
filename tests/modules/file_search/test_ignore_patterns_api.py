"""
파일 검색 무시 패턴 API 테스트

Right-BICEP / CORRECT 패턴:
- TC-Right:    GET 목록, POST 추가, PATCH enabled 토글, DELETE 삭제
- TC-Error:    없는 id PATCH → 404, 없는 id DELETE → 404
- TC-Boundary: 빈 테이블 GET → 빈 배열, POST sort_order null → 자동 max+1
- TC-Cross:    POST 후 GET → 추가된 항목 포함, DELETE 후 GET → 제외됨
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import get_db
from app.models.file_search_ignore_pattern import FileSearchIgnorePattern
from app.modules.file_search.routes import router as file_search_router


# ── 인메모리 DB 픽스처 ──────────────────────────────────────────────────


@pytest.fixture
def db_engine():
    # StaticPool: 모든 커넥션이 동일한 인메모리 DB 공유 (SQLite :memory: 필수)
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # 해당 테이블만 생성 (FK 충돌 없이)
    with engine.connect() as conn:
        FileSearchIgnorePattern.__table__.create(conn, checkfirst=True)
        conn.commit()
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine):
    Session = sessionmaker(bind=db_engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def client(db_session):
    app = FastAPI()
    app.include_router(file_search_router)
    app.dependency_overrides[get_db] = lambda: db_session
    return TestClient(app)


@pytest.fixture
def seeded_client(db_session):
    """seed 패턴 2개가 삽입된 클라이언트."""
    db_session.add(FileSearchIgnorePattern(label="Node 모듈", pattern="node_modules", enabled=1, sort_order=1))
    db_session.add(FileSearchIgnorePattern(label="Git 저장소", pattern=".git", enabled=1, sort_order=2))
    db_session.commit()
    app = FastAPI()
    app.include_router(file_search_router)
    app.dependency_overrides[get_db] = lambda: db_session
    return TestClient(app)


# ── TC-Right ─────────────────────────────────────────────────────────────


class TestGetIgnorePatterns:
    def test_empty_table_returns_empty_list(self, client):
        """빈 테이블에서 GET → 빈 배열."""
        resp = client.get("/api/v1/file-search/ignore-patterns")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_patterns_sorted_by_sort_order(self, seeded_client):
        """GET → sort_order ASC 정렬 확인."""
        resp = seeded_client.get("/api/v1/file-search/ignore-patterns")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["pattern"] == "node_modules"
        assert data[1]["pattern"] == ".git"
        assert data[0]["sort_order"] < data[1]["sort_order"]

    def test_response_schema(self, seeded_client):
        """응답 필드 구조 확인."""
        resp = seeded_client.get("/api/v1/file-search/ignore-patterns")
        item = resp.json()[0]
        assert "id" in item
        assert "label" in item
        assert "pattern" in item
        assert "enabled" in item
        assert "sort_order" in item


class TestAddIgnorePattern:
    def test_add_pattern(self, client):
        """POST → 패턴 추가, 201 반환."""
        resp = client.post(
            "/api/v1/file-search/ignore-patterns",
            json={"label": "Python 캐시", "pattern": "__pycache__"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["label"] == "Python 캐시"
        assert data["pattern"] == "__pycache__"
        assert data["enabled"] is True
        assert data["id"] > 0

    def test_sort_order_auto_max_plus_one(self, seeded_client):
        """POST sort_order=null → 현재 max(2)+1=3 자동 설정."""
        resp = seeded_client.post(
            "/api/v1/file-search/ignore-patterns",
            json={"label": "빌드", "pattern": "dist"},
        )
        assert resp.status_code == 201
        assert resp.json()["sort_order"] == 3

    def test_sort_order_manual(self, client):
        """POST sort_order 직접 지정."""
        resp = client.post(
            "/api/v1/file-search/ignore-patterns",
            json={"label": "테스트", "pattern": "test_dir", "sort_order": 99},
        )
        assert resp.status_code == 201
        assert resp.json()["sort_order"] == 99

    def test_post_then_get_includes_new_item(self, client):
        """TC-Cross: POST 후 GET → 추가된 항목 포함."""
        client.post(
            "/api/v1/file-search/ignore-patterns",
            json={"label": "New", "pattern": "new_pattern"},
        )
        resp = client.get("/api/v1/file-search/ignore-patterns")
        patterns = [p["pattern"] for p in resp.json()]
        assert "new_pattern" in patterns


class TestPatchIgnorePattern:
    def test_toggle_enabled(self, seeded_client):
        """PATCH enabled=False → 비활성화."""
        # 먼저 id 확인
        patterns = seeded_client.get("/api/v1/file-search/ignore-patterns").json()
        pid = patterns[0]["id"]

        resp = seeded_client.patch(
            f"/api/v1/file-search/ignore-patterns/{pid}",
            json={"enabled": False},
        )
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False

    def test_toggle_enabled_back(self, seeded_client):
        """PATCH enabled=False → True 재활성화."""
        patterns = seeded_client.get("/api/v1/file-search/ignore-patterns").json()
        pid = patterns[0]["id"]

        seeded_client.patch(f"/api/v1/file-search/ignore-patterns/{pid}", json={"enabled": False})
        resp = seeded_client.patch(f"/api/v1/file-search/ignore-patterns/{pid}", json={"enabled": True})
        assert resp.json()["enabled"] is True

    def test_update_label(self, seeded_client):
        """PATCH label 수정."""
        patterns = seeded_client.get("/api/v1/file-search/ignore-patterns").json()
        pid = patterns[0]["id"]

        resp = seeded_client.patch(
            f"/api/v1/file-search/ignore-patterns/{pid}",
            json={"label": "수정된 라벨"},
        )
        assert resp.status_code == 200
        assert resp.json()["label"] == "수정된 라벨"

    def test_patch_not_found(self, client):
        """TC-Error: 없는 id PATCH → 404."""
        resp = client.patch(
            "/api/v1/file-search/ignore-patterns/99999",
            json={"enabled": False},
        )
        assert resp.status_code == 404


class TestDeleteIgnorePattern:
    def test_delete_pattern(self, seeded_client):
        """DELETE → 204, 이후 GET에서 미포함."""
        patterns = seeded_client.get("/api/v1/file-search/ignore-patterns").json()
        pid = patterns[0]["id"]
        deleted_pattern = patterns[0]["pattern"]

        resp = seeded_client.delete(f"/api/v1/file-search/ignore-patterns/{pid}")
        assert resp.status_code == 204

        remaining = seeded_client.get("/api/v1/file-search/ignore-patterns").json()
        remaining_patterns = [p["pattern"] for p in remaining]
        assert deleted_pattern not in remaining_patterns

    def test_delete_then_get_excludes_item(self, seeded_client):
        """TC-Cross: DELETE 후 GET → 삭제된 항목 미포함."""
        patterns = seeded_client.get("/api/v1/file-search/ignore-patterns").json()
        assert len(patterns) == 2
        pid = patterns[0]["id"]

        seeded_client.delete(f"/api/v1/file-search/ignore-patterns/{pid}")
        remaining = seeded_client.get("/api/v1/file-search/ignore-patterns").json()
        assert len(remaining) == 1

    def test_delete_not_found(self, client):
        """TC-Error: 없는 id DELETE → 404."""
        resp = client.delete("/api/v1/file-search/ignore-patterns/99999")
        assert resp.status_code == 404
