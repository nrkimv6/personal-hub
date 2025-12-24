"""
Event API 통합 테스트
"""

import pytest
from datetime import date, timedelta
from fastapi.testclient import TestClient

from app.main import app
from app.database import get_db
from app.models.event import Event
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
def sample_event(test_db_session):
    """테스트용 이벤트 생성"""
    event = Event(
        title="테스트 이벤트",
        event_type="event",
        event_url="https://forms.gle/test123",
        url_type="google_form",
        event_start=date.today(),
        event_end=date.today() + timedelta(days=7),
        organizer="테스트 주최사",
        source_type="manual",
    )
    test_db_session.add(event)
    test_db_session.commit()
    test_db_session.refresh(event)
    return event


class TestEventListAPI:
    """GET /api/v1/events 테스트"""

    def test_get_events_empty(self, client):
        """빈 목록 조회"""
        response = client.get("/api/v1/events")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data

    def test_get_events_with_data(self, client, sample_event):
        """이벤트 목록 조회"""
        response = client.get("/api/v1/events")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1

    def test_get_events_filter_event_type(self, client, sample_event):
        """이벤트 유형 필터"""
        response = client.get("/api/v1/events?event_type=event")
        assert response.status_code == 200
        data = response.json()
        for item in data["items"]:
            assert item["event_type"] == "event"

    def test_get_events_filter_event_status(self, client, sample_event):
        """진행 상태 필터"""
        response = client.get("/api/v1/events?event_status=ongoing")
        assert response.status_code == 200

    def test_get_events_pagination(self, client, sample_event):
        """페이지네이션"""
        response = client.get("/api/v1/events?page=1&page_size=10")
        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 1
        assert data["page_size"] == 10

    def test_get_events_sorting(self, client, sample_event):
        """정렬"""
        response = client.get("/api/v1/events?sort_by=event_end&sort_order=desc")
        assert response.status_code == 200


class TestEventDetailAPI:
    """GET /api/v1/events/{id} 테스트"""

    def test_get_event_detail(self, client, sample_event):
        """이벤트 상세 조회"""
        response = client.get(f"/api/v1/events/{sample_event.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == sample_event.id
        assert data["title"] == sample_event.title

    def test_get_event_not_found(self, client):
        """존재하지 않는 이벤트 조회"""
        response = client.get("/api/v1/events/99999")
        assert response.status_code == 404


class TestEventCreateAPI:
    """POST /api/v1/events 테스트"""

    def test_create_event(self, client, admin_headers):
        """이벤트 생성"""
        response = client.post("/api/v1/events", json={
            "title": "새 이벤트",
            "event_type": "popup",
            "event_url": "https://naver.me/test",
            "location_venue": "테스트 장소",
        }, headers=admin_headers)
        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "새 이벤트"
        assert data["event_type"] == "popup"
        assert data["url_type"] == "naver_form"
        assert data["location_venue"] == "테스트 장소"

    def test_create_event_minimal(self, client, admin_headers):
        """최소 필드로 이벤트 생성"""
        response = client.post("/api/v1/events", json={
            "title": "간단한 이벤트",
        }, headers=admin_headers)
        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "간단한 이벤트"
        assert data["event_type"] == "event"  # 기본값
        assert data["source_type"] == "manual"  # 기본값

    def test_create_event_validation_error(self, client, admin_headers):
        """필수 필드 누락"""
        response = client.post("/api/v1/events", json={}, headers=admin_headers)
        assert response.status_code == 422  # Validation Error

    def test_create_event_unauthorized(self, client):
        """인증 없이 이벤트 생성 시도"""
        response = client.post("/api/v1/events", json={
            "title": "새 이벤트",
        })
        assert response.status_code == 401


class TestEventUpdateAPI:
    """PUT /api/v1/events/{id} 테스트"""

    def test_update_event(self, client, sample_event, admin_headers):
        """이벤트 수정"""
        response = client.put(f"/api/v1/events/{sample_event.id}", json={
            "title": "수정된 제목",
            "status": "cancelled",
        }, headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "수정된 제목"
        assert data["status"] == "cancelled"

    def test_update_event_partial(self, client, sample_event, admin_headers):
        """부분 수정 (다른 필드 유지)"""
        original_organizer = sample_event.organizer
        response = client.put(f"/api/v1/events/{sample_event.id}", json={
            "title": "제목만 수정",
        }, headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "제목만 수정"
        assert data["organizer"] == original_organizer

    def test_update_event_not_found(self, client, admin_headers):
        """존재하지 않는 이벤트 수정"""
        response = client.put("/api/v1/events/99999", json={
            "title": "수정",
        }, headers=admin_headers)
        assert response.status_code == 404

    def test_update_event_unauthorized(self, client, sample_event):
        """인증 없이 이벤트 수정 시도"""
        response = client.put(f"/api/v1/events/{sample_event.id}", json={
            "title": "수정",
        })
        assert response.status_code == 401


class TestEventDeleteAPI:
    """DELETE /api/v1/events/{id} 테스트"""

    def test_delete_event(self, client, sample_event, admin_headers):
        """이벤트 삭제"""
        response = client.delete(f"/api/v1/events/{sample_event.id}", headers=admin_headers)
        assert response.status_code == 204

        # 삭제 확인
        response = client.get(f"/api/v1/events/{sample_event.id}")
        assert response.status_code == 404

    def test_delete_event_not_found(self, client, admin_headers):
        """존재하지 않는 이벤트 삭제"""
        response = client.delete("/api/v1/events/99999", headers=admin_headers)
        assert response.status_code == 404

    def test_delete_event_unauthorized(self, client, sample_event):
        """인증 없이 이벤트 삭제 시도"""
        response = client.delete(f"/api/v1/events/{sample_event.id}")
        assert response.status_code == 401


class TestEventBookmarkAPI:
    """POST /api/v1/events/{id}/bookmark 테스트"""

    def test_toggle_bookmark(self, client, sample_event, admin_headers):
        """북마크 토글"""
        # OFF -> ON
        response = client.post(f"/api/v1/events/{sample_event.id}/bookmark", headers=admin_headers)
        assert response.status_code == 200
        assert response.json()["is_bookmarked"] is True

        # ON -> OFF
        response = client.post(f"/api/v1/events/{sample_event.id}/bookmark", headers=admin_headers)
        assert response.status_code == 200
        assert response.json()["is_bookmarked"] is False

    def test_toggle_bookmark_not_found(self, client, admin_headers):
        """존재하지 않는 이벤트 북마크"""
        response = client.post("/api/v1/events/99999/bookmark", headers=admin_headers)
        assert response.status_code == 404

    def test_toggle_bookmark_unauthorized(self, client, sample_event):
        """인증 없이 북마크 시도"""
        response = client.post(f"/api/v1/events/{sample_event.id}/bookmark")
        assert response.status_code == 401


class TestEventParticipateAPI:
    """POST /api/v1/events/{id}/participate 테스트"""

    def test_toggle_participate(self, client, sample_event, admin_headers):
        """참여 완료 토글"""
        # OFF -> ON
        response = client.post(f"/api/v1/events/{sample_event.id}/participate", headers=admin_headers)
        assert response.status_code == 200
        assert response.json()["is_participated"] is True

        # ON -> OFF
        response = client.post(f"/api/v1/events/{sample_event.id}/participate", headers=admin_headers)
        assert response.status_code == 200
        assert response.json()["is_participated"] is False

    def test_toggle_participate_unauthorized(self, client, sample_event):
        """인증 없이 참여 완료 시도"""
        response = client.post(f"/api/v1/events/{sample_event.id}/participate")
        assert response.status_code == 401


class TestEventImportFromInstagramAPI:
    """POST /api/v1/events/import-from-instagram 테스트"""

    @pytest.fixture
    def instagram_post(self, test_db_session, request):
        """테스트용 Instagram 게시물 (테스트별 고유 ID)"""
        import uuid
        unique_id = f"api_test_{uuid.uuid4().hex[:8]}"
        post = InstagramPost(
            post_id=unique_id,
            account="api_test_account",
            url=f"https://instagram.com/p/{unique_id}",
            llm_status="completed",
            llm_tag="팝업",
            llm_summary="API 테스트 팝업",
            llm_event_start=date.today(),
            llm_event_end=date.today() + timedelta(days=14),
            llm_urls=["https://example.com/popup"],
            llm_location={"venue_name": "테스트 장소", "address": "서울시 강남구"},
        )
        test_db_session.add(post)
        test_db_session.commit()
        test_db_session.refresh(post)
        return post

    def test_import_from_instagram(self, client, instagram_post, admin_headers):
        """Instagram에서 이벤트 가져오기"""
        response = client.post("/api/v1/events/import-from-instagram", json={
            "instagram_post_id": instagram_post.id,
        }, headers=admin_headers)
        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "API 테스트 팝업"
        assert data["event_type"] == "popup"
        assert data["source_type"] == "instagram"
        assert data["source_instagram_post_id"] == instagram_post.id
        assert data["location_venue"] == "테스트 장소"
        assert data["location_address"] == "서울시 강남구"

    def test_import_from_instagram_with_title(self, client, instagram_post, admin_headers):
        """커스텀 제목으로 가져오기"""
        response = client.post("/api/v1/events/import-from-instagram", json={
            "instagram_post_id": instagram_post.id,
            "title": "내가 정한 제목",
        }, headers=admin_headers)
        assert response.status_code == 201
        assert response.json()["title"] == "내가 정한 제목"

    def test_import_from_instagram_not_found(self, client, admin_headers):
        """존재하지 않는 게시물"""
        response = client.post("/api/v1/events/import-from-instagram", json={
            "instagram_post_id": 99999,
        }, headers=admin_headers)
        assert response.status_code == 404

    def test_import_from_instagram_unauthorized(self, client):
        """인증 없이 가져오기 시도"""
        response = client.post("/api/v1/events/import-from-instagram", json={
            "instagram_post_id": 1,
        })
        assert response.status_code == 401


class TestEventComputedFields:
    """계산 필드 테스트"""

    def test_event_status_in_response(self, client, sample_event):
        """응답에 event_status 포함"""
        response = client.get(f"/api/v1/events/{sample_event.id}")
        assert response.status_code == 200
        data = response.json()
        assert "event_status" in data
        assert data["event_status"] in ["ongoing", "upcoming", "ended", "cancelled"]

    def test_days_remaining_in_response(self, client, sample_event):
        """응답에 days_remaining 포함"""
        response = client.get(f"/api/v1/events/{sample_event.id}")
        assert response.status_code == 200
        data = response.json()
        assert "days_remaining" in data
        # sample_event는 7일 후 종료
        assert data["days_remaining"] == 7
