"""
Event API 통합 테스트
"""

import pytest
from datetime import date, timedelta
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch

from app.main import app
from app.database import get_db
from app.models.event import Event
from app.models.instagram_post import InstagramPost
from app.core.auth import create_access_token
from app.modules.claude_worker.models.llm_request import LLMRequest
from app.services.page_extractor.base import ExtractedContent


pytestmark = pytest.mark.http


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

    def test_get_events_filter_ongoing_or_upcoming(self, client, admin_headers):
        """진행 중 + 예정 상태 필터"""
        response_a = client.post("/api/v1/events", json={
            "title": "진행 중 이벤트",
            "event_start": str(date.today() - timedelta(days=1)),
            "event_end": str(date.today() + timedelta(days=2)),
        }, headers=admin_headers)
        response_b = client.post("/api/v1/events", json={
            "title": "예정 이벤트",
            "event_start": str(date.today() + timedelta(days=3)),
            "event_end": str(date.today() + timedelta(days=5)),
        }, headers=admin_headers)
        response_c = client.post("/api/v1/events", json={
            "title": "종료 이벤트",
            "event_start": str(date.today() - timedelta(days=5)),
            "event_end": str(date.today() - timedelta(days=1)),
        }, headers=admin_headers)
        response_d = client.post("/api/v1/events", json={
            "title": "취소 이벤트",
            "event_start": str(date.today()),
            "event_end": str(date.today() + timedelta(days=1)),
        }, headers=admin_headers)
        assert response_a.status_code == 201
        assert response_b.status_code == 201
        assert response_c.status_code == 201
        assert response_d.status_code == 201
        cancelled_id = response_d.json()["id"]
        cancel_response = client.put(
            f"/api/v1/events/{cancelled_id}",
            json={"status": "cancelled"},
            headers=admin_headers,
        )
        assert cancel_response.status_code == 200

        response = client.get("/api/v1/events?event_status=ongoing_or_upcoming")
        assert response.status_code == 200
        data = response.json()
        titles = {item["title"] for item in data["items"]}
        assert "진행 중 이벤트" in titles
        assert "예정 이벤트" in titles
        assert "종료 이벤트" not in titles
        assert "취소 이벤트" not in titles

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

    def test_get_events_search_by_title(self, client, admin_headers):
        """제목 검색"""
        # 검색할 이벤트 생성
        client.post("/api/v1/events", json={
            "title": "크리스마스 이벤트",
            "event_type": "event",
            "summary": "특별 경품 제공",
        }, headers=admin_headers)

        response = client.get("/api/v1/events?search=크리스마스")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1
        assert any("크리스마스" in item["title"] for item in data["items"])

    def test_get_events_search_by_summary(self, client, admin_headers):
        """요약 검색"""
        client.post("/api/v1/events", json={
            "title": "신년 이벤트",
            "event_type": "event",
            "summary": "스타벅스 기프티콘 증정",
        }, headers=admin_headers)

        response = client.get("/api/v1/events?search=스타벅스")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1

    def test_get_events_search_by_organizer(self, client, admin_headers):
        """주최자 검색"""
        client.post("/api/v1/events", json={
            "title": "브랜드 이벤트",
            "event_type": "event",
            "organizer": "삼성전자",
        }, headers=admin_headers)

        response = client.get("/api/v1/events?search=삼성전자")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1

    def test_get_events_search_no_result(self, client, sample_event):
        """검색 결과 없음"""
        response = client.get("/api/v1/events?search=존재하지않는검색어xyz")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0


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

    def test_create_event_unauthorized(self, client, mock_external_request):
        """인증 없이 이벤트 생성 시도 (외부 요청)"""
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

    def test_update_event_unauthorized(self, client, sample_event, mock_external_request):
        """인증 없이 이벤트 수정 시도 (외부 요청)"""
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

    def test_delete_event_unauthorized(self, client, sample_event, mock_external_request):
        """인증 없이 이벤트 삭제 시도 (외부 요청)"""
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

    def test_toggle_bookmark_unauthorized(self, client, sample_event, mock_external_request):
        """인증 없이 북마크 시도 (외부 요청)"""
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

    def test_toggle_participate_unauthorized(self, client, sample_event, mock_external_request):
        """인증 없이 참여 완료 시도 (외부 요청)"""
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
        assert data["title"] == "api_test_account의 이벤트"  # llm_* 필드 제거로 기본 제목 사용
        assert data["event_type"] == "event"  # 기본값
        assert data["source_type"] == "instagram"
        assert data["source_instagram_post_id"] == instagram_post.id

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

    def test_import_from_instagram_unauthorized(self, client, mock_external_request):
        """인증 없이 가져오기 시도 (외부 요청)"""
        response = client.post("/api/v1/events/import-from-instagram", json={
            "instagram_post_id": 1,
        })
        assert response.status_code == 401


class TestEventImportFromUrlAPI:
    """POST /api/v1/events/import-from-url 테스트"""

    @patch("app.modules.claude_worker.services.llm_service.LLMService.resolve_provider_model")
    @patch("app.services.event_service.asyncio.get_event_loop")
    def test_import_from_url_right_returns_acceptance_response(
        self, mock_get_event_loop, mock_resolve_provider_model, client, admin_headers, test_db_session
    ):
        mock_extracted = ExtractedContent(
            url="https://example.com/api-success",
            page_type="generic",
            extraction_method="fallback",
            title="API 이벤트",
            content="API 이벤트 본문",
            success=True,
        )
        mock_resolve_provider_model.return_value = ("claude", "sonnet-test")
        mock_get_event_loop.return_value.run_until_complete.return_value = mock_extracted

        with patch(
            "app.services.event_service.EventService._extract_page_content",
            new=MagicMock(return_value=mock_extracted),
        ):
            response = client.post(
                "/api/v1/events/import-from-url",
                json={"url": "https://example.com/api-success", "auto_save": False},
                headers=admin_headers,
            )

        assert response.status_code == 200
        data = response.json()
        saved_request = (
            test_db_session.query(LLMRequest)
            .filter(LLMRequest.caller_type == "event_import")
            .filter(LLMRequest.caller_id == "https://example.com/api-success")
            .one()
        )

        assert data["success"] is True
        assert data["is_event"] is True
        assert data["page_type"] == "generic"
        assert data["extraction_method"] == "fallback"
        assert data["request_id"] == saved_request.id
        assert data["message"] == f"이벤트 등록 요청을 받았습니다 (요청 ID: {saved_request.id})"
        assert data["extracted_event"] is None
        assert data["created_event"] is None
        assert data["error"] is None

    def test_import_from_url_error_duplicate_url_returns_contract_error(
        self, client, admin_headers, sample_event, test_db_session
    ):
        response = client.post(
            "/api/v1/events/import-from-url",
            json={"url": sample_event.event_url, "auto_save": False},
            headers=admin_headers,
        )

        assert response.status_code == 200
        data = response.json()

        assert data["success"] is False
        assert data["is_event"] is True
        assert data["page_type"] == "unknown"
        assert data["extraction_method"] == "skipped"
        assert "동일 URL" in data["error"]
        assert test_db_session.query(LLMRequest).count() == 0

    @patch("app.modules.claude_worker.services.llm_service.LLMService.resolve_provider_model")
    @patch("app.services.event_service.asyncio.get_event_loop")
    def test_import_from_url_error_request_persist_failure_returns_contract_error(
        self, mock_get_event_loop, mock_resolve_provider_model, client, admin_headers, test_db_session
    ):
        mock_extracted = ExtractedContent(
            url="https://example.com/api-failure",
            page_type="generic",
            extraction_method="fallback",
            title="API 실패 이벤트",
            content="API 실패 이벤트 본문",
            success=True,
        )
        mock_get_event_loop.return_value.run_until_complete.return_value = mock_extracted
        mock_resolve_provider_model.side_effect = RuntimeError("provider unavailable")

        with patch(
            "app.services.event_service.EventService._extract_page_content",
            new=MagicMock(return_value=mock_extracted),
        ):
            response = client.post(
                "/api/v1/events/import-from-url",
                json={"url": "https://example.com/api-failure", "auto_save": False},
                headers=admin_headers,
            )

        assert response.status_code == 200
        data = response.json()

        assert data["success"] is False
        assert data["is_event"] is True
        assert data["page_type"] == "generic"
        assert data["extraction_method"] == "fallback"
        assert "LLM 요청 생성 실패" in data["error"]
        assert test_db_session.query(LLMRequest).count() == 0


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


class TestEventOfflineAPI:
    """오프라인 이벤트 관련 테스트"""

    def test_create_offline_event(self, client, admin_headers):
        """오프라인 이벤트 생성"""
        response = client.post("/api/v1/events", json={
            "title": "오프라인 이벤트",
            "event_type": "event",
            "is_offline": True,
            "location_venue": "강남역 1번 출구",
        }, headers=admin_headers)
        assert response.status_code == 201
        data = response.json()
        assert data["is_offline"] is True
        assert data["location_venue"] == "강남역 1번 출구"

    def test_create_online_event_default(self, client, admin_headers):
        """온라인 이벤트 생성 (기본값)"""
        response = client.post("/api/v1/events", json={
            "title": "온라인 이벤트",
            "event_type": "event",
        }, headers=admin_headers)
        assert response.status_code == 201
        data = response.json()
        assert data["is_offline"] is False

    def test_filter_online_events(self, client, admin_headers):
        """온라인 이벤트만 필터링"""
        # 온라인 이벤트 생성
        client.post("/api/v1/events", json={
            "title": "온라인 필터 테스트",
            "is_offline": False,
        }, headers=admin_headers)

        # 오프라인 이벤트 생성
        client.post("/api/v1/events", json={
            "title": "오프라인 필터 테스트",
            "is_offline": True,
        }, headers=admin_headers)

        # 온라인만 조회
        response = client.get("/api/v1/events?is_offline=false")
        assert response.status_code == 200
        data = response.json()
        for item in data["items"]:
            assert item["is_offline"] is False

    def test_filter_offline_events(self, client, admin_headers):
        """오프라인 이벤트만 필터링"""
        # 오프라인 이벤트 생성
        client.post("/api/v1/events", json={
            "title": "오프라인 필터 테스트2",
            "is_offline": True,
        }, headers=admin_headers)

        # 오프라인만 조회
        response = client.get("/api/v1/events?is_offline=true")
        assert response.status_code == 200
        data = response.json()
        for item in data["items"]:
            assert item["is_offline"] is True

    def test_toggle_offline(self, client, sample_event, admin_headers):
        """오프라인 상태 토글"""
        # sample_event는 기본적으로 is_offline=False

        # OFF -> ON
        response = client.post(f"/api/v1/events/{sample_event.id}/toggle-offline", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["is_offline"] is True
        assert data["message"] == "오프라인 이벤트로 변경되었습니다"

        # ON -> OFF
        response = client.post(f"/api/v1/events/{sample_event.id}/toggle-offline", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["is_offline"] is False
        assert data["message"] == "온라인 이벤트로 변경되었습니다"

    def test_toggle_offline_not_found(self, client, admin_headers):
        """존재하지 않는 이벤트 토글"""
        response = client.post("/api/v1/events/99999/toggle-offline", headers=admin_headers)
        assert response.status_code == 404

    def test_toggle_offline_unauthorized(self, client, sample_event, mock_external_request):
        """인증 없이 토글 시도 (외부 요청)"""
        response = client.post(f"/api/v1/events/{sample_event.id}/toggle-offline")
        assert response.status_code == 401

    def test_update_is_offline(self, client, sample_event, admin_headers):
        """PUT으로 is_offline 수정"""
        response = client.put(f"/api/v1/events/{sample_event.id}", json={
            "is_offline": True,
        }, headers=admin_headers)
        assert response.status_code == 200
        assert response.json()["is_offline"] is True
