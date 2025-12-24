"""
Popup API 통합 테스트
"""

import pytest
from datetime import date, timedelta
from fastapi.testclient import TestClient

from app.main import app
from app.database import get_db
from app.models.popup import Popup
from app.models.instagram_post import InstagramPost
from app.core.auth import create_access_token


@pytest.fixture
def admin_headers():
    """관리자 인증 헤더"""
    token = create_access_token(email="admin@test.com", is_admin=True)
    return {"Authorization": f"Bearer {token}"}


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
def sample_popup(test_db_session):
    """테스트용 팝업 생성"""
    popup = Popup(
        title="테스트 팝업",
        venue_name="더현대 서울",
        address="서울시 영등포구",
        start_date=date.today(),
        end_date=date.today() + timedelta(days=14),
        organizer="테스트 브랜드",
        source_type="manual",
    )
    test_db_session.add(popup)
    test_db_session.commit()
    test_db_session.refresh(popup)
    return popup


class TestPopupListAPI:
    """GET /api/v1/popups 테스트"""

    def test_get_popups_empty(self, client):
        """빈 목록 조회"""
        response = client.get("/api/v1/popups")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data

    def test_get_popups_with_data(self, client, sample_popup):
        """팝업 목록 조회"""
        response = client.get("/api/v1/popups")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1

    def test_get_popups_filter_popup_status(self, client, sample_popup):
        """진행 상태 필터"""
        response = client.get("/api/v1/popups?popup_status=ongoing")
        assert response.status_code == 200

    def test_get_popups_pagination(self, client, sample_popup):
        """페이지네이션"""
        response = client.get("/api/v1/popups?page=1&page_size=10")
        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 1
        assert data["page_size"] == 10

    def test_get_popups_sorting(self, client, sample_popup):
        """정렬"""
        response = client.get("/api/v1/popups?sort_by=end_date&sort_order=desc")
        assert response.status_code == 200


class TestPopupDetailAPI:
    """GET /api/v1/popups/{id} 테스트"""

    def test_get_popup_detail(self, client, sample_popup):
        """팝업 상세 조회"""
        response = client.get(f"/api/v1/popups/{sample_popup.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == sample_popup.id
        assert data["title"] == sample_popup.title

    def test_get_popup_not_found(self, client):
        """존재하지 않는 팝업 조회"""
        response = client.get("/api/v1/popups/99999")
        assert response.status_code == 404


class TestPopupCreateAPI:
    """POST /api/v1/popups 테스트"""

    def test_create_popup(self, client, admin_headers):
        """팝업 생성"""
        response = client.post("/api/v1/popups", json={
            "title": "새 팝업",
            "venue_name": "코엑스",
            "address": "서울시 강남구",
        }, headers=admin_headers)
        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "새 팝업"
        assert data["venue_name"] == "코엑스"

    def test_create_popup_minimal(self, client, admin_headers):
        """최소 필드로 팝업 생성"""
        response = client.post("/api/v1/popups", json={
            "title": "간단한 팝업",
        }, headers=admin_headers)
        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "간단한 팝업"
        assert data["source_type"] == "manual"  # 기본값

    def test_create_popup_validation_error(self, client, admin_headers):
        """필수 필드 누락"""
        response = client.post("/api/v1/popups", json={}, headers=admin_headers)
        assert response.status_code == 422  # Validation Error

    def test_create_popup_unauthorized(self, client, mock_external_request):
        """인증 없이 팝업 생성 시도 (외부 요청)"""
        response = client.post("/api/v1/popups", json={
            "title": "새 팝업",
        })
        assert response.status_code == 401


class TestPopupUpdateAPI:
    """PUT /api/v1/popups/{id} 테스트"""

    def test_update_popup(self, client, sample_popup, admin_headers):
        """팝업 수정"""
        response = client.put(f"/api/v1/popups/{sample_popup.id}", json={
            "title": "수정된 제목",
            "status": "cancelled",
        }, headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "수정된 제목"
        assert data["status"] == "cancelled"

    def test_update_popup_partial(self, client, sample_popup, admin_headers):
        """부분 수정 (다른 필드 유지)"""
        original_venue = sample_popup.venue_name
        response = client.put(f"/api/v1/popups/{sample_popup.id}", json={
            "title": "제목만 수정",
        }, headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "제목만 수정"
        assert data["venue_name"] == original_venue

    def test_update_popup_not_found(self, client, admin_headers):
        """존재하지 않는 팝업 수정"""
        response = client.put("/api/v1/popups/99999", json={
            "title": "수정",
        }, headers=admin_headers)
        assert response.status_code == 404

    def test_update_popup_unauthorized(self, client, sample_popup, mock_external_request):
        """인증 없이 팝업 수정 시도 (외부 요청)"""
        response = client.put(f"/api/v1/popups/{sample_popup.id}", json={
            "title": "수정",
        })
        assert response.status_code == 401


class TestPopupDeleteAPI:
    """DELETE /api/v1/popups/{id} 테스트"""

    def test_delete_popup(self, client, sample_popup, admin_headers):
        """팝업 삭제"""
        response = client.delete(f"/api/v1/popups/{sample_popup.id}", headers=admin_headers)
        assert response.status_code == 204

        # 삭제 확인
        response = client.get(f"/api/v1/popups/{sample_popup.id}")
        assert response.status_code == 404

    def test_delete_popup_not_found(self, client, admin_headers):
        """존재하지 않는 팝업 삭제"""
        response = client.delete("/api/v1/popups/99999", headers=admin_headers)
        assert response.status_code == 404

    def test_delete_popup_unauthorized(self, client, sample_popup, mock_external_request):
        """인증 없이 팝업 삭제 시도 (외부 요청)"""
        response = client.delete(f"/api/v1/popups/{sample_popup.id}")
        assert response.status_code == 401


class TestPopupBookmarkAPI:
    """POST /api/v1/popups/{id}/bookmark 테스트"""

    def test_toggle_bookmark(self, client, sample_popup, admin_headers):
        """북마크 토글"""
        # OFF -> ON
        response = client.post(f"/api/v1/popups/{sample_popup.id}/bookmark", headers=admin_headers)
        assert response.status_code == 200
        assert response.json()["is_bookmarked"] is True

        # ON -> OFF
        response = client.post(f"/api/v1/popups/{sample_popup.id}/bookmark", headers=admin_headers)
        assert response.status_code == 200
        assert response.json()["is_bookmarked"] is False

    def test_toggle_bookmark_unauthorized(self, client, sample_popup, mock_external_request):
        """인증 없이 북마크 시도 (외부 요청)"""
        response = client.post(f"/api/v1/popups/{sample_popup.id}/bookmark")
        assert response.status_code == 401


class TestPopupVisitedAPI:
    """POST /api/v1/popups/{id}/visited 테스트"""

    def test_toggle_visited(self, client, sample_popup, admin_headers):
        """방문 완료 토글"""
        # OFF -> ON
        response = client.post(f"/api/v1/popups/{sample_popup.id}/visited", headers=admin_headers)
        assert response.status_code == 200
        assert response.json()["is_visited"] is True

        # ON -> OFF
        response = client.post(f"/api/v1/popups/{sample_popup.id}/visited", headers=admin_headers)
        assert response.status_code == 200
        assert response.json()["is_visited"] is False

    def test_toggle_visited_unauthorized(self, client, sample_popup, mock_external_request):
        """인증 없이 방문 완료 시도 (외부 요청)"""
        response = client.post(f"/api/v1/popups/{sample_popup.id}/visited")
        assert response.status_code == 401


class TestPopupImportFromInstagramAPI:
    """POST /api/v1/popups/import-from-instagram 테스트"""

    @pytest.fixture
    def instagram_post(self, test_db_session):
        """테스트용 Instagram 게시물"""
        import uuid
        unique_id = f"popup_test_{uuid.uuid4().hex[:8]}"
        post = InstagramPost(
            post_id=unique_id,
            account="popup_test_account",
            url=f"https://instagram.com/p/{unique_id}",
            images=[{"src": "https://example.com/image.jpg"}],
        )
        test_db_session.add(post)
        test_db_session.commit()
        test_db_session.refresh(post)
        return post

    def test_import_from_instagram(self, client, instagram_post, admin_headers):
        """Instagram에서 팝업 가져오기"""
        response = client.post("/api/v1/popups/import-from-instagram", json={
            "instagram_post_id": instagram_post.id,
        }, headers=admin_headers)
        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "popup_test_account의 팝업"  # llm_* 필드 제거로 기본 제목 사용
        assert data["source_type"] == "instagram"
        assert data["source_instagram_post_id"] == instagram_post.id

    def test_import_from_instagram_not_found(self, client, admin_headers):
        """존재하지 않는 게시물"""
        response = client.post("/api/v1/popups/import-from-instagram", json={
            "instagram_post_id": 99999,
        }, headers=admin_headers)
        assert response.status_code == 404

    def test_import_from_instagram_unauthorized(self, client, mock_external_request):
        """인증 없이 가져오기 시도 (외부 요청)"""
        response = client.post("/api/v1/popups/import-from-instagram", json={
            "instagram_post_id": 1,
        })
        assert response.status_code == 401


class TestPopupComputedFields:
    """계산 필드 테스트"""

    def test_popup_status_in_response(self, client, sample_popup):
        """응답에 popup_status 포함"""
        response = client.get(f"/api/v1/popups/{sample_popup.id}")
        assert response.status_code == 200
        data = response.json()
        assert "popup_status" in data
        assert data["popup_status"] in ["ongoing", "upcoming", "ended", "cancelled"]

    def test_days_remaining_in_response(self, client, sample_popup):
        """응답에 days_remaining 포함"""
        response = client.get(f"/api/v1/popups/{sample_popup.id}")
        assert response.status_code == 200
        data = response.json()
        assert "days_remaining" in data
        # sample_popup은 14일 후 종료
        assert data["days_remaining"] == 14
