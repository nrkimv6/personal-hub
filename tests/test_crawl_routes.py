"""
크롤링 API 라우트 테스트

RIGHT-BICEP, CORRECT 원칙 적용
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient
from datetime import datetime

from app.main import app
from app.database import get_db
from app.models import CrawlRequest, TaskSchedule


@pytest.fixture
def client(test_db_session):
    """테스트 DB 세션을 사용하는 테스트 클라이언트."""
    def override_get_db():
        try:
            yield test_db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


class TestCrawlRequestRoutes:
    """CrawlRequest API 라우트 테스트."""

    def test_create_request_right(self, client):
        """[Right] 요청 생성 API가 올바르게 동작해야 함."""
        response = client.post("/api/v2/crawl/requests", json={
            "url": "https://example.com/test",
            "url_type": "other",
            "requested_by": "api_test"
        })

        assert response.status_code == 200
        data = response.json()
        assert data["url"] == "https://example.com/test"
        assert data["url_type"] == "other"
        assert data["status"] == "pending"

    def test_get_requests_paginated_right(self, client):
        """[Right] 요청 목록 조회 API가 올바르게 동작해야 함."""
        # 먼저 몇 개 생성
        for i in range(5):
            client.post("/api/v2/crawl/requests", json={
                "url": f"https://example.com/test{i}",
                "url_type": "instagram"
            })

        response = client.get("/api/v2/crawl/requests", params={
            "page": 1,
            "limit": 10,
            "url_type": "instagram"
        })

        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert "pages" in data

    def test_get_request_by_id_right(self, client):
        """[Right] 요청 상세 조회 API가 올바르게 동작해야 함."""
        # 먼저 생성
        create_response = client.post("/api/v2/crawl/requests", json={
            "url": "https://example.com/detail",
            "url_type": "naver_blog"
        })
        request_id = create_response.json()["id"]

        # 조회
        response = client.get(f"/api/v2/crawl/requests/{request_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == request_id
        assert data["url"] == "https://example.com/detail"

    def test_get_request_not_found_error(self, client):
        """[Error] 존재하지 않는 요청 조회 시 404를 반환해야 함."""
        response = client.get("/api/v2/crawl/requests/99999")
        assert response.status_code == 404


class TestTaskScheduleRoutes:
    """TaskSchedule API 라우트 테스트."""

    def test_create_schedule_right(self, client):
        """[Right] 스케줄 생성 API가 올바르게 동작해야 함."""
        ts = datetime.now().timestamp()
        response = client.post("/api/tasks/schedules", json={
            "name": f"test_schedule_{ts}",
            "target_type": "instagram_feed",
            "schedule_type": "manual",
            "display_name": "테스트 스케줄",
            "enabled": True
        })

        assert response.status_code == 200
        data = response.json()
        assert data["target_type"] == "instagram_feed"
        assert data["enabled"] == True

    def test_create_schedule_duplicate_name_error(self, client):
        """[Error] 중복된 이름으로 스케줄 생성 시 400을 반환해야 함."""
        ts = datetime.now().timestamp()
        name = f"duplicate_test_{ts}"

        # 첫 번째 생성
        client.post("/api/tasks/schedules", json={
            "name": name,
            "target_type": "instagram_feed",
            "schedule_type": "manual"
        })

        # 두 번째 생성 시도 (동일 이름)
        response = client.post("/api/tasks/schedules", json={
            "name": name,
            "target_type": "naver_blog",
            "schedule_type": "manual"
        })

        assert response.status_code == 400

    def test_get_schedules_right(self, client):
        """[Right] 스케줄 목록 조회 API가 올바르게 동작해야 함."""
        ts = datetime.now().timestamp()

        # 스케줄 생성
        client.post("/api/tasks/schedules", json={
            "name": f"list_test_{ts}",
            "target_type": "instagram_feed",
            "schedule_type": "manual",
            "enabled": True
        })

        response = client.get("/api/tasks/schedules", params={
            "enabled_only": True
        })

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_get_schedule_by_id_right(self, client):
        """[Right] 스케줄 상세 조회 API가 올바르게 동작해야 함."""
        ts = datetime.now().timestamp()

        # 생성
        create_response = client.post("/api/tasks/schedules", json={
            "name": f"detail_test_{ts}",
            "target_type": "naver_blog",
            "schedule_type": "time_window"
        })
        schedule_id = create_response.json()["id"]

        # 조회
        response = client.get(f"/api/tasks/schedules/{schedule_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == schedule_id

    def test_update_schedule_right(self, client):
        """[Right] 스케줄 업데이트 API가 올바르게 동작해야 함."""
        ts = datetime.now().timestamp()

        # 생성
        create_response = client.post("/api/tasks/schedules", json={
            "name": f"update_test_{ts}",
            "target_type": "instagram_feed",
            "schedule_type": "manual",
            "enabled": True
        })
        schedule_id = create_response.json()["id"]

        # 업데이트
        response = client.put(f"/api/tasks/schedules/{schedule_id}", json={
            "display_name": "업데이트된 이름",
            "enabled": False
        })

        assert response.status_code == 200
        data = response.json()
        assert data["display_name"] == "업데이트된 이름"
        assert data["enabled"] == False

    def test_toggle_schedule_right(self, client):
        """[Right] 스케줄 토글 API가 올바르게 동작해야 함."""
        ts = datetime.now().timestamp()

        # 생성 (enabled=True)
        create_response = client.post("/api/tasks/schedules", json={
            "name": f"toggle_test_{ts}",
            "target_type": "instagram_feed",
            "schedule_type": "manual",
            "enabled": True
        })
        schedule_id = create_response.json()["id"]

        # 비활성화
        response = client.post(
            f"/api/tasks/schedules/{schedule_id}/toggle",
            params={"enabled": False}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        assert data["enabled"] == False


class TestCrawlRunRoutes:
    """TaskScheduleRun API 라우트 테스트."""

    def test_get_schedule_runs_right(self, client):
        """[Right] 스케줄 실행 이력 조회 API가 올바르게 동작해야 함."""
        ts = datetime.now().timestamp()

        # 스케줄 생성
        create_response = client.post("/api/tasks/schedules", json={
            "name": f"runs_test_{ts}",
            "target_type": "instagram_feed",
            "schedule_type": "manual"
        })
        schedule_id = create_response.json()["id"]

        # 실행 이력 조회
        response = client.get(f"/api/tasks/schedules/{schedule_id}/runs")

        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data

    def test_get_schedule_stats_right(self, client):
        """[Right] 스케줄 통계 조회 API가 올바르게 동작해야 함."""
        ts = datetime.now().timestamp()

        # 스케줄 생성
        create_response = client.post("/api/tasks/schedules", json={
            "name": f"stats_test_{ts}",
            "target_type": "instagram_feed",
            "schedule_type": "manual"
        })
        schedule_id = create_response.json()["id"]

        # 통계 조회
        response = client.get(
            f"/api/tasks/schedules/{schedule_id}/stats",
            params={"days": 7}
        )

        assert response.status_code == 200
        data = response.json()
        assert "period_days" in data
        assert "total_runs" in data
        assert "success_rate" in data

    def test_get_all_runs_right(self, client):
        """[Right] 전체 실행 이력 조회 API가 올바르게 동작해야 함."""
        response = client.get("/api/tasks/runs")

        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert "pages" in data


class TestUrlCrawlRoutes:
    """URL 크롤링 API 라우트 테스트 (await 버그 수정 검증)."""

    def _make_mock_request(self, url: str = "https://example.com/test", url_type: str = "generic") -> MagicMock:
        """테스트용 CrawlRequest mock 객체 생성."""
        mock_req = MagicMock()
        mock_req.id = 1
        mock_req.url = url
        mock_req.url_type = url_type
        mock_req.status = "pending"
        return mock_req

    def test_create_url_crawl_right(self, client):
        """[Right] 정상 URL POST → 200 + CrawlUrlResponse 반환."""
        mock_req = self._make_mock_request()
        with patch(
            "app.routes.crawl.universal_crawl_service.create_request",
            new=AsyncMock(return_value=(mock_req, "크롤링 요청이 등록되었습니다. (ID: 1)"))
        ):
            response = client.post("/api/v2/crawl/url", json={
                "url": "https://example.com/test",
                "auto_analyze": True,
                "priority": 0,
            })

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["request_id"] == 1
        assert data["url"] == "https://example.com/test"
        assert data["url_type"] == "generic"
        assert data["status"] == "pending"
        assert "message" in data

    def test_create_url_crawl_error_valueerror(self, client):
        """[Error] service가 ValueError raise → 400 반환."""
        with patch(
            "app.routes.crawl.universal_crawl_service.create_request",
            new=AsyncMock(side_effect=ValueError("Instagram URL은 지원하지 않습니다."))
        ):
            response = client.post("/api/v2/crawl/url", json={
                "url": "https://www.instagram.com/p/test/",
                "auto_analyze": True,
                "priority": 0,
            })

        assert response.status_code == 400

    def test_create_url_crawl_error_generic(self, client):
        """[Error] service가 Exception raise → 500 + '크롤링 요청 생성에 실패했습니다.' 메시지."""
        with patch(
            "app.routes.crawl.universal_crawl_service.create_request",
            new=AsyncMock(side_effect=Exception("DB 연결 실패"))
        ):
            response = client.post("/api/v2/crawl/url", json={
                "url": "https://example.com/test",
                "auto_analyze": True,
                "priority": 0,
            })

        assert response.status_code == 500
        assert response.json()["detail"] == "크롤링 요청 생성에 실패했습니다."

    def test_create_batch_url_crawl_right(self, client):
        """[Right] 2개 URL POST → 200 + created=2."""
        call_count = 0

        async def mock_create(db, url, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_req = MagicMock()
            mock_req.id = call_count
            return mock_req, f"등록됨 (ID: {call_count})"

        with patch("app.routes.crawl.universal_crawl_service.create_request", side_effect=mock_create):
            response = client.post("/api/v2/crawl/urls", json={
                "urls": ["https://example.com/1", "https://example.com/2"],
                "auto_analyze": True,
                "priority": 0,
            })

        assert response.status_code == 200
        data = response.json()
        assert data["created"] == 2
        assert data["skipped"] == 0
        assert data["errors"] == []

    def test_create_batch_url_crawl_boundary_max(self, client):
        """[Boundary] 21개 URL → 400/422 에러 (Pydantic max_length 또는 route 검증)."""
        response = client.post("/api/v2/crawl/urls", json={
            "urls": [f"https://example.com/{i}" for i in range(21)],
            "auto_analyze": True,
            "priority": 0,
        })

        # Pydantic 스키마 max_length=20 제약으로 422, 또는 route에서 400
        assert response.status_code in (400, 422)

    def test_create_batch_url_crawl_error_partial(self, client):
        """[Error] 3개 URL 중 1개에서 Exception → 200 + created=2, errors 배열에 에러 URL."""
        call_count = 0

        async def mock_create(db, url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise Exception("2번째 URL 처리 실패")
            mock_req = MagicMock()
            mock_req.id = call_count
            return mock_req, f"등록됨 (ID: {call_count})"

        with patch("app.routes.crawl.universal_crawl_service.create_request", side_effect=mock_create):
            response = client.post("/api/v2/crawl/urls", json={
                "urls": [
                    "https://example.com/1",
                    "https://example.com/2",
                    "https://example.com/3",
                ],
                "auto_analyze": True,
                "priority": 0,
            })

        assert response.status_code == 200
        data = response.json()
        assert data["created"] == 2
        assert len(data["errors"]) == 1
        assert "example.com/2" in data["errors"][0]
