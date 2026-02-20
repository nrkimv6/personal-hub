"""Notes API Right-BICEP 테스트.

패턴 참조: tests/modules/naver_booking/test_business_api.py
"""

import pytest
from fastapi.testclient import TestClient


# ══════════════════════════════════════════════════════════════
# TestNotesAPIRight — 올바른 결과 확인 (RIGHT)
# ══════════════════════════════════════════════════════════════

class TestNotesAPIRight:
    def test_create_note(self, client: TestClient, sample_note_data: dict):
        res = client.post("/api/notes", json=sample_note_data)
        assert res.status_code == 201
        data = res.json()
        assert data["title"] == sample_note_data["title"]
        assert data["content"] == sample_note_data["content"]
        assert data["remark"] == sample_note_data["remark"]
        assert data["tags"] == []
        assert "created_at" in data
        assert "id" in data

    def test_get_notes_list(self, client: TestClient, sample_note: dict):
        res = client.get("/api/notes")
        assert res.status_code == 200
        data = res.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "pages" in data
        assert data["total"] >= 1

    def test_get_note_by_id(self, client: TestClient, sample_note: dict):
        res = client.get(f"/api/notes/{sample_note['id']}")
        assert res.status_code == 200
        data = res.json()
        assert data["id"] == sample_note["id"]
        assert "tags" in data

    def test_update_note(self, client: TestClient, sample_note: dict):
        updated_title = "수정된 제목"
        res = client.put(f"/api/notes/{sample_note['id']}", json={"title": updated_title})
        assert res.status_code == 200
        data = res.json()
        assert data["title"] == updated_title
        assert data["updated_at"] >= sample_note["updated_at"]

    def test_update_note_creates_history(self, client: TestClient, sample_note: dict):
        client.put(f"/api/notes/{sample_note['id']}", json={"title": "수정 후 제목"})
        res = client.get(f"/api/notes/{sample_note['id']}/history")
        assert res.status_code == 200
        history = res.json()
        assert len(history) >= 1
        # 이전 본문이 이력에 저장되어야 함
        assert history[0]["title"] == sample_note["title"]

    def test_delete_note_soft(self, client: TestClient, sample_note: dict):
        res = client.delete(f"/api/notes/{sample_note['id']}")
        assert res.status_code == 200
        # 목록에서 제외되어야 함
        list_res = client.get("/api/notes")
        ids = [n["id"] for n in list_res.json()["items"]]
        assert sample_note["id"] not in ids

    def test_toggle_pin(self, client: TestClient, sample_note: dict):
        # 처음엔 비고정
        assert sample_note["is_pinned"] is False
        # 고정
        res = client.post(f"/api/notes/{sample_note['id']}/pin")
        assert res.status_code == 200
        assert res.json()["is_pinned"] is True
        # 다시 해제
        res = client.post(f"/api/notes/{sample_note['id']}/pin")
        assert res.json()["is_pinned"] is False

    def test_create_tag(self, client: TestClient, sample_tag_data: dict):
        res = client.post("/api/notes/tags", json=sample_tag_data)
        assert res.status_code == 201
        data = res.json()
        assert data["name"] == sample_tag_data["name"]
        assert data["color"] == sample_tag_data["color"]

    def test_create_note_with_tags(self, client: TestClient, sample_note_data: dict, sample_tag: dict):
        data = {**sample_note_data, "tag_ids": [sample_tag["id"]]}
        res = client.post("/api/notes", json=data)
        assert res.status_code == 201
        note = res.json()
        # 상세 조회로 태그 포함 확인
        detail = client.get(f"/api/notes/{note['id']}").json()
        tag_ids = [t["id"] for t in detail["tags"]]
        assert sample_tag["id"] in tag_ids


# ══════════════════════════════════════════════════════════════
# TestNotesAPIBoundary — 경계값 테스트 (BOUNDARY)
# ══════════════════════════════════════════════════════════════

class TestNotesAPIBoundary:
    def test_create_note_empty_content(self, client: TestClient, unique_id: str):
        res = client.post("/api/notes", json={"title": f"빈본문_{unique_id}", "content": ""})
        assert res.status_code == 201
        assert res.json()["content"] == ""

    def test_create_note_long_content(self, client: TestClient, unique_id: str):
        long_content = "A" * 100_000  # 100KB
        res = client.post("/api/notes", json={"title": f"장문_{unique_id}", "content": long_content})
        assert res.status_code == 201
        # 다시 조회해도 동일
        note_id = res.json()["id"]
        detail = client.get(f"/api/notes/{note_id}").json()
        assert len(detail["content"]) == 100_000

    def test_create_note_unicode_emoji(self, client: TestClient, unique_id: str):
        content = "안녕하세요 🎉 Hello 中文 🐍\nSpecial: <script>alert(1)</script>"
        res = client.post("/api/notes", json={"title": f"유니코드_{unique_id}", "content": content})
        assert res.status_code == 201
        note_id = res.json()["id"]
        detail = client.get(f"/api/notes/{note_id}").json()
        assert "🎉" in detail["content"]
        assert "안녕하세요" in detail["content"]

    def test_list_notes_page_zero(self, client: TestClient):
        # page=0은 FastAPI 유효성 검사(ge=1)로 422
        res = client.get("/api/notes?page=0")
        assert res.status_code == 422

    def test_list_notes_empty_search(self, client: TestClient, sample_note: dict):
        # search="" → 전체 목록 반환 (필터 무시)
        res = client.get("/api/notes?search=")
        assert res.status_code == 200
        assert res.json()["total"] >= 1

    def test_create_tag_max_length(self, client: TestClient, unique_id: str):
        # 50자 이름 생성 성공
        name = ("T" * 46 + unique_id[:4])[:50]
        res = client.post("/api/notes/tags", json={"name": name})
        assert res.status_code == 201
        assert res.json()["name"] == name


# ══════════════════════════════════════════════════════════════
# TestNotesAPIInverse — 역관계 검증 (INVERSE)
# ══════════════════════════════════════════════════════════════

class TestNotesAPIInverse:
    def test_archive_and_restore_roundtrip(
        self, client: TestClient, sample_note_data: dict, sample_tag: dict
    ):
        # 태그 포함 메모 생성
        data = {**sample_note_data, "tag_ids": [sample_tag["id"]]}
        note = client.post("/api/notes", json=data).json()
        note_id = note["id"]

        # 아카이브
        arc = client.post(f"/api/notes/{note_id}/archive").json()
        arc_id = arc["id"]

        # 활성 목록에서 사라짐
        ids = [n["id"] for n in client.get("/api/notes").json()["items"]]
        assert note_id not in ids

        # 복원
        restored = client.post(f"/api/notes/archive/{arc_id}/restore").json()
        assert restored["title"] == sample_note_data["title"]
        assert restored["content"] == sample_note_data["content"]
        assert restored["remark"] == sample_note_data["remark"]
        # 태그도 복원됨
        tag_ids = [t["id"] for t in restored["tags"]]
        assert sample_tag["id"] in tag_ids

    def test_archive_preserves_history(self, client: TestClient, sample_note: dict):
        note_id = sample_note["id"]
        # 2회 수정
        client.put(f"/api/notes/{note_id}", json={"title": "1차 수정"})
        client.put(f"/api/notes/{note_id}", json={"title": "2차 수정"})

        # 아카이브
        arc = client.post(f"/api/notes/{note_id}/archive").json()
        arc_id = arc["id"]

        # 복원
        restored = client.post(f"/api/notes/archive/{arc_id}/restore").json()
        restored_id = restored["id"]

        # 이력 2건 보존
        history = client.get(f"/api/notes/{restored_id}/history").json()
        assert len(history) >= 2

    def test_delete_tag_does_not_delete_notes(
        self, client: TestClient, sample_note_data: dict, unique_id: str
    ):
        # 태그 생성
        tag = client.post("/api/notes/tags", json={"name": f"삭제태그_{unique_id}"}).json()
        # 태그 포함 메모 생성
        note = client.post("/api/notes", json={**sample_note_data, "tag_ids": [tag["id"]]}).json()
        # 태그 삭제
        client.delete(f"/api/notes/tags/{tag['id']}")
        # 메모는 여전히 존재
        detail = client.get(f"/api/notes/{note['id']}")
        assert detail.status_code == 200


# ══════════════════════════════════════════════════════════════
# TestNotesAPICrossCheck — 교차 검증 (CROSS-CHECK)
# ══════════════════════════════════════════════════════════════

class TestNotesAPICrossCheck:
    def test_filter_by_tag(self, client: TestClient, unique_id: str, sample_note_data: dict):
        # 태그A 메모 2개 + 태그B 메모 1개
        tag_a = client.post("/api/notes/tags", json={"name": f"tagA_{unique_id}"}).json()
        tag_b = client.post("/api/notes/tags", json={"name": f"tagB_{unique_id}"}).json()

        client.post("/api/notes", json={**sample_note_data, "title": f"A1_{unique_id}", "tag_ids": [tag_a["id"]]})
        client.post("/api/notes", json={**sample_note_data, "title": f"A2_{unique_id}", "tag_ids": [tag_a["id"]]})
        client.post("/api/notes", json={**sample_note_data, "title": f"B1_{unique_id}", "tag_ids": [tag_b["id"]]})

        res = client.get(f"/api/notes?tag={tag_a['name']}")
        items = res.json()["items"]
        titles = [n["title"] for n in items]
        assert f"A1_{unique_id}" in titles
        assert f"A2_{unique_id}" in titles
        assert f"B1_{unique_id}" not in titles

    def test_search_title_and_content(self, client: TestClient, unique_id: str):
        kw = f"UNIQUE_KW_{unique_id}"
        client.post("/api/notes", json={"title": kw, "content": "no match"})
        client.post("/api/notes", json={"title": "no match", "content": kw})

        res = client.get(f"/api/notes?search={kw}")
        assert res.json()["total"] >= 2

    def test_pinned_notes_first(self, client: TestClient, unique_id: str):
        n1 = client.post("/api/notes", json={"title": f"일반_{unique_id}", "content": ""}).json()
        n2 = client.post("/api/notes", json={"title": f"고정_{unique_id}", "content": ""}).json()
        client.post(f"/api/notes/{n2['id']}/pin")  # 고정

        items = client.get("/api/notes").json()["items"]
        ids = [n["id"] for n in items]
        assert ids.index(n2["id"]) < ids.index(n1["id"])

    def test_soft_deleted_excluded_from_list(self, client: TestClient, sample_note: dict):
        client.delete(f"/api/notes/{sample_note['id']}")
        ids = [n["id"] for n in client.get("/api/notes").json()["items"]]
        assert sample_note["id"] not in ids

    def test_archive_excluded_from_notes_list(
        self, client: TestClient, sample_note_data: dict, unique_id: str
    ):
        note = client.post("/api/notes", json={**sample_note_data, "title": f"arc_{unique_id}"}).json()
        client.post(f"/api/notes/{note['id']}/archive")

        # 활성 목록에서 제외
        note_ids = [n["id"] for n in client.get("/api/notes").json()["items"]]
        assert note["id"] not in note_ids

        # 아카이브 목록에 있음
        arc_items = client.get("/api/notes/archive").json()["items"]
        orig_ids = [a["original_id"] for a in arc_items]
        assert note["id"] in orig_ids

    def test_tag_note_count(self, client: TestClient, unique_id: str, sample_note_data: dict):
        tag = client.post("/api/notes/tags", json={"name": f"cnt_{unique_id}"}).json()
        # 메모 2개에 태그 할당
        client.post("/api/notes", json={**sample_note_data, "title": f"cnt1_{unique_id}", "tag_ids": [tag["id"]]})
        client.post("/api/notes", json={**sample_note_data, "title": f"cnt2_{unique_id}", "tag_ids": [tag["id"]]})

        tags = client.get("/api/notes/tags").json()
        found = next((t for t in tags if t["id"] == tag["id"]), None)
        assert found is not None
        assert found["note_count"] >= 2


# ══════════════════════════════════════════════════════════════
# TestNotesAPIError — 에러 케이스 (ERROR)
# ══════════════════════════════════════════════════════════════

class TestNotesAPIError:
    def test_get_note_not_found(self, client: TestClient):
        res = client.get("/api/notes/99999")
        assert res.status_code == 404

    def test_update_note_not_found(self, client: TestClient):
        res = client.put("/api/notes/99999", json={"title": "x"})
        assert res.status_code == 404

    def test_create_note_missing_title(self, client: TestClient):
        res = client.post("/api/notes", json={"content": "본문만"})
        assert res.status_code == 422

    def test_create_note_invalid_tag_id(self, client: TestClient, unique_id: str):
        res = client.post("/api/notes", json={"title": f"잘못태그_{unique_id}", "tag_ids": [999999]})
        assert res.status_code == 400

    def test_create_tag_duplicate_name(self, client: TestClient, sample_tag: dict):
        res = client.post("/api/notes/tags", json={"name": sample_tag["name"]})
        assert res.status_code == 400

    def test_archive_not_found(self, client: TestClient):
        res = client.post("/api/notes/99999/archive")
        assert res.status_code == 404

    def test_restore_not_found(self, client: TestClient):
        res = client.post("/api/notes/archive/99999/restore")
        assert res.status_code == 404

    def test_route_ordering_archive_not_caught_by_id(self, client: TestClient):
        """GET /api/notes/archive가 /{id}로 매칭되지 않고 올바른 라우트로 처리됨."""
        res = client.get("/api/notes/archive")
        # /{id} 라우트에서 id='archive'를 정수로 변환하려 하면 422 발생
        # 올바른 /archive 라우트이면 200
        assert res.status_code == 200


# ══════════════════════════════════════════════════════════════
# TestNotesAPICORRECT — Conformance/Ordering/Range/Time
# ══════════════════════════════════════════════════════════════

class TestNotesAPICORRECT:
    def test_conformance_datetime_format(self, client: TestClient, sample_note: dict):
        """created_at, updated_at이 ISO 포맷 문자열인지 확인."""
        from datetime import datetime
        # ISO 파싱 성공 여부로 포맷 확인
        datetime.fromisoformat(sample_note["created_at"].replace("Z", "+00:00"))
        datetime.fromisoformat(sample_note["updated_at"].replace("Z", "+00:00"))

    def test_ordering_created_at_desc(self, client: TestClient, unique_id: str):
        """메모 3개 생성 → 목록이 최신순 정렬."""
        ids = []
        for i in range(3):
            note = client.post("/api/notes", json={"title": f"순서테스트{i}_{unique_id}"}).json()
            ids.append(note["id"])

        items = client.get("/api/notes").json()["items"]
        item_ids = [n["id"] for n in items]
        # 가장 나중에 만든 것이 앞에 있어야 함 (pinned 없는 경우)
        last_three_pos = [item_ids.index(i) for i in ids if i in item_ids]
        assert last_three_pos == sorted(last_three_pos, reverse=True)

    def test_range_pagination(self, client: TestClient, unique_id: str):
        """page_size=2로 3개 메모 → pages=2 이상, 각 페이지 아이템 수."""
        for i in range(3):
            client.post("/api/notes", json={"title": f"pg_{unique_id}_{i}"})

        res = client.get("/api/notes?page_size=2")
        data = res.json()
        assert data["page_size"] == 2
        assert data["pages"] >= 2
        assert len(data["items"]) <= 2

    def test_cardinality_total_count(self, client: TestClient, unique_id: str):
        """메모 3개 생성 후 total 증가 확인."""
        before = client.get("/api/notes").json()["total"]
        for i in range(3):
            client.post("/api/notes", json={"title": f"cnt_{unique_id}_{i}"})
        after = client.get("/api/notes").json()["total"]
        assert after == before + 3

    def test_time_updated_at_changes(self, client: TestClient, sample_note: dict):
        """수정 후 updated_at이 변경됨."""
        import time
        time.sleep(0.01)  # 타임스탬프 차이 보장
        updated = client.put(
            f"/api/notes/{sample_note['id']}", json={"content": "수정된 내용"}
        ).json()
        assert updated["updated_at"] >= sample_note["updated_at"]
