"""메모 벌크 API 테스트."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# 메타데이터에 notes 모델 등록을 보장하기 위해 명시적 임포트 (app 변수 오염 방지)
from app.modules.notes import models as _notes_models  # noqa: F401
from app.main import app
from app.database import get_db, Base


# ──────────────── 테스트 DB 픽스처 ────────────────


@pytest.fixture(scope="function")
def db_bundle(tmp_path):
    db_path = tmp_path / "test_notes_temp.db"
    engine_test = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    testing_session_local = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine_test,
    )

    Base.metadata.create_all(bind=engine_test)
    session = testing_session_local()
    try:
        yield {
            "session": session,
            "SessionLocal": testing_session_local,
            "engine": engine_test,
        }
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine_test)
        engine_test.dispose()


@pytest.fixture(scope="function")
def db(db_bundle):
    yield db_bundle["session"]


@pytest.fixture(scope="function")
def client(db_bundle):
    TestingSessionLocal = db_bundle["SessionLocal"]

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


class TestSearchTitles:
    """제목 검색 API 테스트."""

    def test_search_titles(self, client):
        """제목 검색 — 부분 일치 결과 반환."""
        create_note(client, "파이썬 기초")
        create_note(client, "파이썬 고급")
        create_note(client, "자바스크립트")

        res = client.get("/api/notes/search/titles?q=파이썬")
        assert res.status_code == 200
        data = res.json()
        assert len(data) == 2
        titles = [d["title"] for d in data]
        assert "파이썬 기초" in titles
        assert "파이썬 고급" in titles
        for item in data:
            assert "id" in item
            assert "title" in item

    def test_search_titles_empty(self, client):
        """검색 결과 없을 때 빈 배열 반환."""
        res = client.get("/api/notes/search/titles?q=존재하지않는제목xyz")
        assert res.status_code == 200
        assert res.json() == []

    def test_search_titles_missing_q_returns_422(self, client):
        """q 파라미터 없으면 422."""
        res = client.get("/api/notes/search/titles")
        assert res.status_code == 422


class TestToggleStar:
    """별표 토글 테스트."""

    def test_toggle_star(self, client):
        """별표 토글: 기본값 False → True → False."""
        note_id = create_note(client, "별표 테스트 메모")

        # 기본값 확인
        res = client.get(f"/api/notes/{note_id}")
        assert res.status_code == 200
        assert res.json()["is_starred"] is False

        # 별표 ON
        res = client.post(f"/api/notes/{note_id}/star")
        assert res.status_code == 200
        data = res.json()
        assert data["is_starred"] is True

        # 별표 OFF
        res = client.post(f"/api/notes/{note_id}/star")
        assert res.status_code == 200
        assert res.json()["is_starred"] is False

    def test_filter_starred(self, client):
        """?starred=true 필터: 별표 메모만 반환."""
        id1 = create_note(client, "별표 A")
        create_note(client, "일반 B")

        # id1만 별표
        client.post(f"/api/notes/{id1}/star")

        res = client.get("/api/notes?starred=true")
        assert res.status_code == 200
        items = res.json()["items"]
        assert len(items) == 1
        assert items[0]["id"] == id1
        assert items[0]["is_starred"] is True

    def test_filter_not_starred(self, client):
        """?starred=false 필터: 별표 없는 메모만 반환."""
        id1 = create_note(client, "별표 A")
        id2 = create_note(client, "일반 B")

        client.post(f"/api/notes/{id1}/star")

        res = client.get("/api/notes?starred=false")
        assert res.status_code == 200
        items = res.json()["items"]
        ids = [i["id"] for i in items]
        assert id1 not in ids
        assert id2 in ids

    def test_starred_not_in_archive(self, client):
        """아카이브 응답에는 is_starred 필드 미포함 (NoteArchiveResponse)."""
        note_id = create_note(client, "아카이브용 메모")
        client.post(f"/api/notes/{note_id}/star")

        # 아카이브 이동
        res = client.post(f"/api/notes/{note_id}/archive")
        assert res.status_code == 200
        archive_data = res.json()
        assert "is_starred" not in archive_data
