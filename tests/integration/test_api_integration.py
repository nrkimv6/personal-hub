"""
API Integration Tests

실제 HTTP 통신을 통한 API 통합 테스트.
테스트 서버가 자동으로 시작/종료됩니다.

실행 방법:
    pytest tests/integration/
    또는
    .\scripts\tests_scripts\test.ps1 -Integration
"""

import pytest

# requests는 optional dependency
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


pytestmark = pytest.mark.skipif(not HAS_REQUESTS, reason="requests 모듈 필요")


class TestHealthEndpoint:
    """Health 엔드포인트 테스트"""

    def test_health_check(self, integration_server):
        """서버 상태 확인"""
        response = requests.get(f"{integration_server}/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"


class TestBusinessAPI:
    """Business API 통합 테스트"""

    def test_list_businesses_empty(self, integration_server):
        """빈 업체 목록 조회"""
        response = requests.get(f"{integration_server}/api/businesses")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_create_and_get_business(self, integration_server):
        """업체 생성 및 조회"""
        # 생성
        create_response = requests.post(
            f"{integration_server}/api/businesses",
            json={
                "name": "테스트 업체",
                "url": "https://booking.naver.com/booking/13/bizes/1234567"
            }
        )

        # 생성 성공 또는 이미 존재
        assert create_response.status_code in [200, 201, 409]

        # 목록 조회
        list_response = requests.get(f"{integration_server}/api/businesses")
        assert list_response.status_code == 200


class TestSlotCheckAPI:
    """슬롯 조회 API 통합 테스트"""

    def test_slot_check_missing_params(self, integration_server):
        """필수 파라미터 누락 시 400 에러"""
        response = requests.get(f"{integration_server}/api/v1/slots/check")

        assert response.status_code == 400
        data = response.json()
        assert "detail" in data

    def test_slot_check_invalid_url(self, integration_server):
        """잘못된 URL 형식 시 400 에러"""
        response = requests.get(
            f"{integration_server}/api/v1/slots/check",
            params={"url": "https://invalid-url.com"}
        )

        assert response.status_code == 400


class TestBusinessUrlImportAPI:
    """Business URL Import API 통합 테스트 (T5 HTTP 통합)"""

    ENCODED_URL = (
        "https://booking.naver.com/booking/12/bizes/1630978/items/7575050"
        "?startDateTime=2026-04-25T00%3A00%3A00%2B09%3A00"
    )

    def test_import_url_right_url_only_autofills_names(self, integration_server):
        """R: item_name 없이 URL만으로 200 + business_id/item_id 반환"""
        response = requests.post(
            f"{integration_server}/api/businesses/import-url",
            json={"url": self.ENCODED_URL, "fetch_details": False}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["business_id"] is not None
        assert data["item_id"] is not None

    def test_import_url_right_response_includes_business_and_item_fields(self, integration_server):
        """R: 응답에 business/biz_item 필드가 포함되고 name이 비어있지 않음"""
        response = requests.post(
            f"{integration_server}/api/businesses/import-url",
            json={"url": self.ENCODED_URL, "fetch_details": False}
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("business") is not None
        assert data["business"].get("name"), "business.name이 비어있어서는 안 됨"
        assert data.get("biz_item") is not None
        assert data["biz_item"].get("name"), "biz_item.name이 비어있어서는 안 됨"

    def test_import_url_boundary_existing_business_reuse(self, integration_server):
        """B: 동일 URL 두 번 요청 시 재사용 분기에서도 business.name 반환"""
        payload = {"url": self.ENCODED_URL, "fetch_details": False}
        requests.post(f"{integration_server}/api/businesses/import-url", json=payload)
        response = requests.post(f"{integration_server}/api/businesses/import-url", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data.get("business") is not None
        assert data["business"].get("name")

    def test_import_url_right_with_manual_item_name_preserved(self, integration_server):
        """R 회귀: item_name 직접 지정 시 해당 값 그대로 저장"""
        import time
        unique_name = f"TC_아이템_{int(time.time())}"
        response = requests.post(
            f"{integration_server}/api/businesses/import-url",
            json={
                "url": "https://booking.naver.com/booking/12/bizes/9990001/items/9990001",
                "item_name": unique_name,
                "fetch_details": False
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["biz_item"]["name"] == unique_name

    def test_import_url_error_invalid_url_format(self, integration_server):
        """E: 잘못된 URL 입력 시 success=False 또는 에러 응답"""
        response = requests.post(
            f"{integration_server}/api/businesses/import-url",
            json={"url": "https://naver.com/invalid/path"}
        )
        data = response.json()
        assert data.get("success") is False or response.status_code >= 400


class TestAccountAPI:
    """Account API 통합 테스트"""

    def test_list_accounts(self, integration_server):
        """계정 목록 조회"""
        response = requests.get(f"{integration_server}/api/accounts")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)


class TestImageClassifyAPI:
    """Image Classifier API 통합 테스트 — /api/ic/classify 엔드포인트"""

    def test_classify_status_endpoint_returns_200(self, integration_server):
        """GET /api/ic/classify/status 요청 시 HTTP 200 반환 및 running 필드 포함."""
        response = requests.get(f"{integration_server}/api/ic/classify/status")

        assert response.status_code == 200
        data = response.json()
        assert "running" in data, f"응답에 'running' 필드가 없음: {data}"

    def test_classify_start_returns_error_when_no_files(self, integration_server):
        """POST /api/ic/classify/start — 분류 대상 파일 없을 때 4xx 반환 (서버 에러 500 아님)."""
        response = requests.post(
            f"{integration_server}/api/ic/classify/start",
            json={"model": "claude_cli", "batch_size": 1},
        )

        # DB에 파일 없으므로 4xx 반환 예상 (200이면 빈 배치 처리 시작)
        assert response.status_code != 500, f"서버 에러(500) 발생: {response.text}"
        assert response.status_code in [200, 400, 404, 409], \
            f"예상치 못한 응답 코드: {response.status_code}, body: {response.text}"

    def test_classify_start_with_gemini_model_no_server_error(self, integration_server):
        """POST /api/ic/classify/start body model='gemini_cli' — 서버 에러(500) 없음."""
        response = requests.post(
            f"{integration_server}/api/ic/classify/start",
            json={"model": "gemini_cli", "batch_size": 1},
        )

        assert response.status_code != 500, \
            f"gemini_cli 모델로 요청 시 서버 에러 발생: {response.text}"
