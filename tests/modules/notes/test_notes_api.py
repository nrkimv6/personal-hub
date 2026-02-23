"""메모 벌크 API 테스트."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# 메타데이터에 notes 모델 등록을 보장하기 위해 명시적 임포트 (app 변수 오염 방지)
from app.modules.notes import models as _notes_models  # noqa: F401
from app.main import app
from app.database import get_db, Base


# ──────────────── 인메모리 DB 픽스처 ────────────────

SQLALCHEMY_DATABASE_URL = "sqlite:///./test_notes_temp.db"

engine_test = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine_test)


@pytest.fixture(scope="function")
def db():
    Base.metadata.create_all(bind=engine_test)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine_test)


@pytest.fixture(scope="function")
def client(db):
    def override_get_db():
        s = TestingSessionLocal()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ──────────────── 헬퍼 ────────────────

def create_note(client: TestClient, title: str) -> int:
    res = client.post("/api/notes", json={"title": title, "content": f"{title} 내용"})
    assert res.status_code == 201, res.text
    return res.json()["id"]


def create_tag(client: TestClient, name: str) -> int:
    res = client.post("/api/notes/tags", json={"name": name, "color": "#3b82f6"})
    assert res.status_code == 201, res.text
    return res.json()["id"]


# ──────────────── 테스트 ────────────────

class TestBulkDelete:
    """벌크 삭제 테스트."""

    def test_bulk_delete(self, client):
        """3개 메모 생성 후 일괄 삭제, 목록에서 미노출 확인."""
        ids = [create_note(client, f"메모 {i}") for i in range(3)]

        res = client.post("/api/notes/bulk/delete", json={"note_ids": ids})
        assert res.status_code == 200
        data = res.json()
        assert data["ok"] is True
        assert data["count"] == 3

        # 목록에서 미노출
        list_res = client.get("/api/notes")
        assert list_res.status_code == 200
        remaining_ids = [n["id"] for n in list_res.json()["items"]]
        for nid in ids:
            assert nid not in remaining_ids

    def test_bulk_delete_partial(self, client):
        """일부만 존재하는 ids로 삭제 시 존재하는 것만 처리."""
        nid = create_note(client, "존재하는 메모")
        res = client.post("/api/notes/bulk/delete", json={"note_ids": [nid, 99999]})
        assert res.status_code == 200
        assert res.json()["count"] == 1

    def test_bulk_delete_empty_ids_returns_422(self, client):
        """빈 ids 전송 시 422."""
        res = client.post("/api/notes/bulk/delete", json={"note_ids": []})
        assert res.status_code == 422


class TestBulkArchive:
    """벌크 아카이브 테스트."""

    def test_bulk_archive(self, client):
        """일괄 아카이브 후 archive 목록 확인."""
        ids = [create_note(client, f"아카이브 메모 {i}") for i in range(2)]

        res = client.post("/api/notes/bulk/archive", json={"note_ids": ids})
        assert res.status_code == 200
        data = res.json()
        assert data["ok"] is True
        assert data["count"] == 2

        # 아카이브 목록 확인
        arch_res = client.get("/api/notes/archive")
        assert arch_res.status_code == 200
        arch_ids = [a["original_id"] for a in arch_res.json()["items"]]
        for nid in ids:
            assert nid in arch_ids

        # 메모 목록에서 미노출
        list_res = client.get("/api/notes")
        remaining_ids = [n["id"] for n in list_res.json()["items"]]
        for nid in ids:
            assert nid not in remaining_ids


class TestBulkTag:
    """벌크 태그 테스트."""

    def test_bulk_tag_add_and_remove(self, client):
        """add/remove 태그 동작 확인."""
        tag_a = create_tag(client, "태그A")
        tag_b = create_tag(client, "태그B")

        # 메모 생성 (태그A 포함)
        res = client.post("/api/notes", json={"title": "태그 테스트 메모", "tag_ids": [tag_a]})
        assert res.status_code == 201
        nid = res.json()["id"]

        # 태그B 추가, 태그A 제거
        bulk_res = client.post("/api/notes/bulk/tag", json={
            "note_ids": [nid],
            "add_tag_ids": [tag_b],
            "remove_tag_ids": [tag_a],
        })
        assert bulk_res.status_code == 200
        assert bulk_res.json()["ok"] is True

        # 결과 확인
        note_res = client.get(f"/api/notes/{nid}")
        assert note_res.status_code == 200
        tag_ids = [t["id"] for t in note_res.json()["tags"]]
        assert tag_b in tag_ids
        assert tag_a not in tag_ids

    def test_bulk_tag_no_duplicate(self, client):
        """이미 있는 태그 중복 추가 방지."""
        tag_a = create_tag(client, "중복태그")
        res = client.post("/api/notes", json={"title": "중복 테스트", "tag_ids": [tag_a]})
        nid = res.json()["id"]

        # 같은 태그 또 추가
        bulk_res = client.post("/api/notes/bulk/tag", json={
            "note_ids": [nid],
            "add_tag_ids": [tag_a],
            "remove_tag_ids": [],
        })
        assert bulk_res.status_code == 200

        note_res = client.get(f"/api/notes/{nid}")
        tags = [t["id"] for t in note_res.json()["tags"]]
        assert tags.count(tag_a) == 1  # 중복 없음
