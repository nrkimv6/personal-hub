"""
Uncategorized API 통합 테스트
"""

import pytest
from datetime import date, timedelta
from fastapi.testclient import TestClient

from app.main import app
from app.database import get_db
from app.models.uncategorized_post import UncategorizedPost
from app.models.instagram_post import InstagramPost
from app.models.event import Event
from app.models.popup import Popup


@pytest.fixture
def client(test_db_session):
    """테스트용 FastAPI 클라이언트"""
    def override_get_db():
        try:
            yield test_db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def instagram_post(test_db_session):
    """테스트용 Instagram 게시물"""
    import uuid
    unique_id = f"uncategorized_test_{uuid.uuid4().hex[:8]}"
    post = InstagramPost(
        post_id=unique_id,
        account="uncategorized_test_account",
        url=f"https://instagram.com/p/{unique_id}",
        images=[{"src": "https://example.com/image.jpg"}],
    )
    test_db_session.add(post)
    test_db_session.commit()
    test_db_session.refresh(post)
    return post


@pytest.fixture
def sample_uncategorized(test_db_session, instagram_post):
    """테스트용 미분류 항목 생성"""
    item = UncategorizedPost(
        original_tag="홍보대사",
        title="테스트 홍보대사 모집",
        summary="테스트 요약",
        organizer="테스트 브랜드",
        source_instagram_post_id=instagram_post.id,
        source_instagram_url=instagram_post.url,
        source_instagram_account=instagram_post.account,
    )
    test_db_session.add(item)
    test_db_session.commit()
    test_db_session.refresh(item)
    return item


class TestUncategorizedListAPI:
    """GET /api/v1/uncategorized 테스트"""

    def test_get_uncategorized_empty(self, client):
        """빈 목록 조회"""
        response = client.get("/api/v1/uncategorized")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data

    def test_get_uncategorized_with_data(self, client, sample_uncategorized):
        """미분류 목록 조회"""
        response = client.get("/api/v1/uncategorized")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1

    def test_get_uncategorized_filter_original_tag(self, client, sample_uncategorized):
        """원본 태그 필터"""
        response = client.get("/api/v1/uncategorized?original_tag=홍보대사")
        assert response.status_code == 200
        data = response.json()
        for item in data["items"]:
            assert item["original_tag"] == "홍보대사"

    def test_get_uncategorized_exclude_reclassified(self, client, sample_uncategorized, test_db_session):
        """재분류된 항목 제외 (기본값)"""
        # 재분류된 항목 생성
        reclassified_item = UncategorizedPost(
            original_tag="기타",
            title="재분류된 항목",
            source_instagram_post_id=sample_uncategorized.source_instagram_post_id + 1000,  # 다른 ID
            reclassified_as="event",
            reclassified_id=1,
        )
        # 먼저 InstagramPost 생성
        import uuid
        unique_id = f"reclassified_test_{uuid.uuid4().hex[:8]}"
        post = InstagramPost(
            post_id=unique_id,
            account="test",
        )
        test_db_session.add(post)
        test_db_session.commit()

        reclassified_item.source_instagram_post_id = post.id
        test_db_session.add(reclassified_item)
        test_db_session.commit()

        # 기본 조회 - 재분류된 항목 제외
        response = client.get("/api/v1/uncategorized")
        assert response.status_code == 200
        data = response.json()
        for item in data["items"]:
            assert item["reclassified_as"] is None

    def test_get_uncategorized_include_reclassified(self, client, sample_uncategorized):
        """재분류된 항목 포함"""
        response = client.get("/api/v1/uncategorized?include_reclassified=true")
        assert response.status_code == 200


class TestUncategorizedDetailAPI:
    """GET /api/v1/uncategorized/{id} 테스트"""

    def test_get_uncategorized_detail(self, client, sample_uncategorized):
        """미분류 항목 상세 조회"""
        response = client.get(f"/api/v1/uncategorized/{sample_uncategorized.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == sample_uncategorized.id
        assert data["original_tag"] == sample_uncategorized.original_tag

    def test_get_uncategorized_not_found(self, client):
        """존재하지 않는 미분류 항목 조회"""
        response = client.get("/api/v1/uncategorized/99999")
        assert response.status_code == 404


class TestReclassifyAPI:
    """POST /api/v1/uncategorized/{id}/reclassify 테스트"""

    def test_reclassify_to_event(self, client, sample_uncategorized, test_db_session):
        """Event로 재분류"""
        response = client.post(f"/api/v1/uncategorized/{sample_uncategorized.id}/reclassify", json={
            "target": "event",
            "title": "재분류된 이벤트",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["target"] == "event"
        assert data["created_id"] is not None

        # Event 테이블에 생성 확인
        event = test_db_session.query(Event).filter(Event.id == data["created_id"]).first()
        assert event is not None
        assert event.title == "재분류된 이벤트"
        assert event.source_type == "instagram"

    def test_reclassify_to_popup(self, client, test_db_session, instagram_post):
        """Popup으로 재분류"""
        # 새 미분류 항목 생성 (재분류 안 된 것)
        item = UncategorizedPost(
            original_tag="기타",
            title="팝업으로 재분류될 항목",
            source_instagram_post_id=instagram_post.id,
            source_instagram_url=instagram_post.url,
            source_instagram_account=instagram_post.account,
        )
        test_db_session.add(item)
        test_db_session.commit()
        test_db_session.refresh(item)

        response = client.post(f"/api/v1/uncategorized/{item.id}/reclassify", json={
            "target": "popup",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["target"] == "popup"

        # Popup 테이블에 생성 확인
        popup = test_db_session.query(Popup).filter(Popup.id == data["created_id"]).first()
        assert popup is not None
        assert popup.source_type == "instagram"

    def test_reclassify_already_reclassified(self, client, sample_uncategorized, test_db_session):
        """이미 재분류된 항목"""
        # 먼저 재분류
        sample_uncategorized.reclassified_as = "event"
        sample_uncategorized.reclassified_id = 1
        test_db_session.commit()

        # 다시 재분류 시도
        response = client.post(f"/api/v1/uncategorized/{sample_uncategorized.id}/reclassify", json={
            "target": "popup",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "Already reclassified" in data["message"]

    def test_reclassify_not_found(self, client):
        """존재하지 않는 미분류 항목 재분류"""
        response = client.post("/api/v1/uncategorized/99999/reclassify", json={
            "target": "event",
        })
        assert response.status_code == 404


class TestUncategorizedDeleteAPI:
    """DELETE /api/v1/uncategorized/{id} 테스트"""

    def test_delete_uncategorized(self, client, sample_uncategorized):
        """미분류 항목 삭제"""
        response = client.delete(f"/api/v1/uncategorized/{sample_uncategorized.id}")
        assert response.status_code == 204

        # 삭제 확인
        response = client.get(f"/api/v1/uncategorized/{sample_uncategorized.id}")
        assert response.status_code == 404

    def test_delete_uncategorized_not_found(self, client):
        """존재하지 않는 미분류 항목 삭제"""
        response = client.delete("/api/v1/uncategorized/99999")
        assert response.status_code == 404
