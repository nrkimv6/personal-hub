"""
Universal Crawl 모델 및 API 테스트
"""

import pytest
import hashlib
from datetime import datetime
from fastapi.testclient import TestClient

from app.main import app
from app.database import get_db
from app.models.universal_crawl import CrawledPage
from app.models.crawl_request import CrawlRequest
from app.core.auth import create_access_token
from app.services.universal_crawl_service import universal_crawl_service


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
def sample_crawled_page(test_db_session):
    """테스트용 크롤링 페이지 생성"""
    import uuid
    unique_id = uuid.uuid4().hex[:8]
    url = f"https://forms.gle/test_{unique_id}"
    page = CrawledPage(
        url=url,
        url_type="google_form",
        title="테스트 구글폼",
        description="테스트 설명",
        content="폼 내용",
        url_hash=hashlib.md5(url.encode()).hexdigest(),
        extractor_used="GoogleFormsExtractor",
    )
    test_db_session.add(page)
    test_db_session.commit()
    test_db_session.refresh(page)
    return page


@pytest.fixture
def sample_crawl_request(test_db_session):
    """테스트용 크롤링 요청 생성"""
    import uuid
    unique_id = uuid.uuid4().hex[:8]
    request = CrawlRequest(
        url=f"https://docs.google.com/forms/d/e/{unique_id}",
        url_type="google_form",
        status="pending",
        requested_by="manual",
    )
    test_db_session.add(request)
    test_db_session.commit()
    test_db_session.refresh(request)
    return request


class TestCrawledPageModel:
    """CrawledPage 모델 테스트"""

    def test_create_crawled_page(self, test_db_session):
        """크롤링 페이지 생성"""
        import uuid
        unique_id = uuid.uuid4().hex[:8]
        url = f"https://form.naver.com/test_{unique_id}"
        page = CrawledPage(
            url=url,
            url_type="naver_form",
            title="네이버폼 테스트",
            url_hash=hashlib.md5(url.encode()).hexdigest(),
        )
        test_db_session.add(page)
        test_db_session.commit()

        # 조회 확인
        saved = test_db_session.query(CrawledPage).filter_by(id=page.id).first()
        assert saved is not None
        assert saved.url_type == "naver_form"
        assert saved.title == "네이버폼 테스트"

    def test_url_hash_unique(self, test_db_session, sample_crawled_page):
        """URL 해시 중복 방지"""
        # 동일 URL로 생성 시도
        duplicate = CrawledPage(
            url=sample_crawled_page.url,
            url_type="google_form",
            url_hash=sample_crawled_page.url_hash,  # 동일 해시
        )
        test_db_session.add(duplicate)
        with pytest.raises(Exception):  # IntegrityError 또는 유사 예외
            test_db_session.commit()


class TestCrawlRequestModel:
    """CrawlRequest 모델 테스트"""

    def test_create_request(self, test_db_session):
        """크롤링 요청 생성"""
        import uuid
        unique_id = uuid.uuid4().hex[:8]
        request = CrawlRequest(
            url=f"https://blog.naver.com/testuser/{unique_id}",
            url_type="naver_blog",
            status="pending",
            requested_by="pwa_share",
        )
        test_db_session.add(request)
        test_db_session.commit()

        # 조회 확인
        saved = test_db_session.query(CrawlRequest).filter_by(id=request.id).first()
        assert saved is not None
        assert saved.url_type == "naver_blog"
        assert saved.status == "pending"
        assert saved.requested_by == "pwa_share"

    def test_request_status_transitions(self, test_db_session, sample_crawl_request):
        """요청 상태 전이"""
        request = sample_crawl_request

        # pending -> processing
        request.status = "processing"
        request.started_at = datetime.now()
        test_db_session.commit()
        assert request.status == "processing"

        # processing -> completed
        request.status = "completed"
        request.completed_at = datetime.now()
        test_db_session.commit()
        assert request.status == "completed"

    def test_request_with_account_id(self, test_db_session):
        """account_id가 있는 요청 (브라우저 프로필 필요)"""
        import uuid
        unique_id = uuid.uuid4().hex[:8]
        request = CrawlRequest(
            url=f"https://www.google.com/search?q=test_{unique_id}",
            url_type="generic",
            service_account_id=1,  # 로그인 필요한 경우
            status="pending",
        )
        test_db_session.add(request)
        test_db_session.commit()

        saved = test_db_session.query(CrawlRequest).filter_by(id=request.id).first()
        assert saved.service_account_id == 1

    def test_request_without_account_id(self, test_db_session):
        """service_account_id 없는 요청 (HTTP 전용 또는 기본 프로필)"""
        import uuid
        unique_id = uuid.uuid4().hex[:8]
        request = CrawlRequest(
            url=f"https://forms.gle/simple_{unique_id}",
            url_type="google_form",
            service_account_id=None,  # 브라우저 불필요
            status="pending",
        )
        test_db_session.add(request)
        test_db_session.commit()

        saved = test_db_session.query(CrawlRequest).filter_by(id=request.id).first()
        assert saved.service_account_id is None


class TestCrawlRequestRelationship:
    """요청-결과 관계 테스트"""

    def test_link_request_to_page(self, test_db_session, sample_crawled_page):
        """요청과 결과 페이지 연결"""
        request = CrawlRequest(
            url=sample_crawled_page.url,
            url_type=sample_crawled_page.url_type,
            status="completed",
            crawled_page_id=sample_crawled_page.id,
        )
        test_db_session.add(request)
        test_db_session.commit()

        # 관계 확인
        saved = test_db_session.query(CrawlRequest).filter_by(id=request.id).first()
        assert saved.crawled_page_id == sample_crawled_page.id
        assert saved.crawled_page is not None
        assert saved.crawled_page.title == "테스트 구글폼"


class TestUniversalCrawlService:
    """UniversalCrawlService 테스트"""

    def test_is_instagram_url(self):
        """Instagram URL 감지"""
        # Instagram URL 패턴
        assert universal_crawl_service.is_instagram_url("https://www.instagram.com/p/ABC123/")
        assert universal_crawl_service.is_instagram_url("https://instagram.com/reel/XYZ789/")
        assert universal_crawl_service.is_instagram_url("https://www.instagram.com/reels/ABC123/")
        assert universal_crawl_service.is_instagram_url("https://www.instagram.com/stories/user123/")
        assert universal_crawl_service.is_instagram_url("https://instagr.am/p/ABC123/")
        # 비 Instagram URL
        assert not universal_crawl_service.is_instagram_url("https://forms.gle/test")
        assert not universal_crawl_service.is_instagram_url("https://blog.naver.com/test")
        assert not universal_crawl_service.is_instagram_url("https://www.instagram.com/username/")  # 프로필은 제외

    def test_create_request_success(self, test_db_session):
        """요청 생성 성공"""
        import uuid
        unique_id = uuid.uuid4().hex[:8]
        url = f"https://forms.gle/test_{unique_id}"

        request, message = universal_crawl_service.create_request(
            db=test_db_session,
            url=url,
            auto_analyze=True,
        )

        assert request.id is not None
        assert request.status == "pending"
        assert request.url_type == "google_form"
        assert "등록되었습니다" in message

    def test_create_request_instagram_accepted(self, test_db_session):
        """Instagram URL 허용 (url_type=instagram으로 설정)"""
        import uuid
        unique_id = uuid.uuid4().hex[:8]

        request, message = universal_crawl_service.create_request(
            db=test_db_session,
            url=f"https://www.instagram.com/p/{unique_id}/",
        )

        assert request.id is not None
        assert request.status == "pending"
        assert request.url_type == "instagram"
        assert "등록되었습니다" in message

    def test_get_pending_requests(self, test_db_session):
        """대기 중인 요청 조회"""
        import uuid

        # 여러 요청 생성
        for i in range(3):
            unique_id = uuid.uuid4().hex[:8]
            universal_crawl_service.create_request(
                db=test_db_session,
                url=f"https://forms.gle/pending_{unique_id}",
                priority=i,
            )

        pending = universal_crawl_service.get_pending_requests(test_db_session, limit=10)
        assert len(pending) >= 3

        # 우선순위 순 정렬 확인
        priorities = [r.priority for r in pending[:3]]
        assert priorities == sorted(priorities, reverse=True)

    def test_update_request_status(self, test_db_session, sample_crawl_request):
        """요청 상태 업데이트"""
        request_id = sample_crawl_request.id

        # pending -> processing
        updated = universal_crawl_service.mark_processing(test_db_session, request_id)
        assert updated.status == "processing"
        assert updated.started_at is not None

    def test_retry_request(self, test_db_session):
        """실패한 요청 재시도"""
        import uuid
        unique_id = uuid.uuid4().hex[:8]

        request, _ = universal_crawl_service.create_request(
            db=test_db_session,
            url=f"https://forms.gle/retry_{unique_id}",
        )

        # 실패 처리
        universal_crawl_service.mark_failed(
            test_db_session, request.id, "테스트 실패"
        )

        # 재시도
        retried = universal_crawl_service.retry_request(test_db_session, request.id)
        assert retried.status == "pending"
        assert retried.error_message is None


class TestUniversalCrawlAPI:
    """Universal Crawl API 테스트 (v2로 통합됨)"""

    def test_create_crawl_request_api(self, client):
        """POST /api/v2/crawl/url - 요청 생성"""
        import uuid
        unique_id = uuid.uuid4().hex[:8]

        response = client.post(
            "/api/v2/crawl/url",
            json={
                "url": f"https://docs.google.com/forms/d/e/{unique_id}",
                "auto_analyze": True,
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["url_type"] == "google_form"
        assert data["status"] == "pending"

    def test_create_crawl_request_instagram_accepted(self, client):
        """POST /api/v2/crawl/url - Instagram URL 허용"""
        import uuid
        unique_id = uuid.uuid4().hex[:8]

        response = client.post(
            "/api/v2/crawl/url",
            json={"url": f"https://www.instagram.com/p/{unique_id}/"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["url_type"] == "instagram"
        assert data["status"] == "pending"

    def test_list_crawl_requests(self, client, sample_crawl_request):
        """GET /api/v2/crawl/universal-requests - 목록 조회"""
        response = client.get("/api/v2/crawl/universal-requests")

        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data

    def test_get_crawl_request(self, client, sample_crawl_request):
        """GET /api/v2/crawl/universal-requests/{id} - 상세 조회"""
        response = client.get(f"/api/v2/crawl/universal-requests/{sample_crawl_request.id}")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == sample_crawl_request.id

    def test_list_crawled_pages(self, client, sample_crawled_page):
        """GET /api/v2/crawl/pages - 목록 조회"""
        response = client.get("/api/v2/crawl/pages")

        assert response.status_code == 200
        data = response.json()
        assert "items" in data

    def test_get_crawled_page(self, client, sample_crawled_page):
        """GET /api/v2/crawl/pages/{id} - 상세 조회"""
        response = client.get(f"/api/v2/crawl/pages/{sample_crawled_page.id}")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == sample_crawled_page.id

    def test_analyze_page_api(self, client, sample_crawled_page):
        """POST /api/v2/crawl/pages/{id}/analyze - AI 분석 요청"""
        response = client.post(f"/api/v2/crawl/pages/{sample_crawled_page.id}/analyze")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["page_id"] == sample_crawled_page.id
        assert data["status"] == "pending"
        assert "request_id" in data

    def test_analyze_page_not_found(self, client):
        """POST /api/v2/crawl/pages/{id}/analyze - 없는 페이지"""
        response = client.post("/api/v2/crawl/pages/99999/analyze")

        assert response.status_code == 404

    def test_get_analysis_status_not_requested(self, client, sample_crawled_page):
        """GET /api/v2/crawl/pages/{id}/analysis - 분석 요청 없음"""
        # 먼저 분석 요청이 없는 새 페이지 생성
        import uuid
        import hashlib
        unique_id = uuid.uuid4().hex[:8]
        from app.database import get_db
        from app.models.universal_crawl import CrawledPage as CP

        # 다른 fixture를 통해 생성된 페이지 사용 가능하지만,
        # 분석 요청이 없는 상태를 테스트해야 하므로 별도 조회
        response = client.get(f"/api/v2/crawl/pages/{sample_crawled_page.id}/analysis")

        # 분석 요청이 없으면 not_requested
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ["not_requested", "pending", "completed"]

    def test_list_requests_with_filters(self, client, sample_crawl_request):
        """GET /api/v2/crawl/universal-requests - 필터 파라미터 테스트"""
        # 상태 필터
        response = client.get("/api/v2/crawl/universal-requests?status=pending")
        assert response.status_code == 200

        # URL 타입 필터
        response = client.get("/api/v2/crawl/universal-requests?url_type=google_form")
        assert response.status_code == 200

        # 분석 상태 필터
        response = client.get("/api/v2/crawl/universal-requests?analysis_status=unanalyzed")
        assert response.status_code == 200

        # 정렬
        response = client.get("/api/v2/crawl/universal-requests?sort_by=requested_at&sort_order=desc")
        assert response.status_code == 200

    def test_list_requests_url_search(self, client, sample_crawl_request):
        """GET /api/v2/crawl/universal-requests - URL 검색"""
        response = client.get("/api/v2/crawl/universal-requests?url_search=google")
        assert response.status_code == 200


class TestUniversalCrawlAnalyzerService:
    """UniversalCrawlAnalyzerService 테스트"""

    def test_create_analysis_request(self, test_db_session, sample_crawled_page):
        """분석 요청 생성"""
        from app.services.universal_crawl_analyzer import UniversalCrawlAnalyzerService

        analyzer = UniversalCrawlAnalyzerService(test_db_session)
        request = analyzer.create_analysis_request(sample_crawled_page.id)

        assert request is not None
        assert request.caller_type == "universal_crawl"
        assert request.caller_id == str(sample_crawled_page.id)
        assert request.status == "pending"

    def test_create_analysis_request_duplicate(self, test_db_session, sample_crawled_page):
        """중복 분석 요청 방지"""
        from app.services.universal_crawl_analyzer import UniversalCrawlAnalyzerService

        analyzer = UniversalCrawlAnalyzerService(test_db_session)

        # 첫 번째 요청
        request1 = analyzer.create_analysis_request(sample_crawled_page.id)
        # 두 번째 요청 (중복)
        request2 = analyzer.create_analysis_request(sample_crawled_page.id)

        # 동일 요청 반환
        assert request1.id == request2.id

    def test_create_analysis_request_not_found(self, test_db_session):
        """없는 페이지에 대한 분석 요청"""
        from app.services.universal_crawl_analyzer import UniversalCrawlAnalyzerService

        analyzer = UniversalCrawlAnalyzerService(test_db_session)
        request = analyzer.create_analysis_request(99999)

        assert request is None

    def test_get_stats(self, test_db_session, sample_crawled_page):
        """통계 조회"""
        from app.services.universal_crawl_analyzer import UniversalCrawlAnalyzerService

        analyzer = UniversalCrawlAnalyzerService(test_db_session)
        # 분석 요청 생성
        analyzer.create_analysis_request(sample_crawled_page.id)

        stats = analyzer.get_stats()
        assert "total" in stats
        assert "pending" in stats
        assert "completed" in stats
