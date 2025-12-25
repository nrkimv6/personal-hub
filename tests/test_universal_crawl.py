"""
Universal Crawl 모델 및 API 테스트
"""

import pytest
import hashlib
from datetime import datetime
from fastapi.testclient import TestClient

from app.main import app
from app.database import get_db
from app.models.universal_crawl import UniversalCrawlRequest, CrawledPage
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
    request = UniversalCrawlRequest(
        url=f"https://docs.google.com/forms/d/e/{unique_id}",
        url_type="google_form",
        status="pending",
        requested_by="manual",
        auto_analyze=True,
        priority=0,
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


class TestUniversalCrawlRequestModel:
    """UniversalCrawlRequest 모델 테스트"""

    def test_create_request(self, test_db_session):
        """크롤링 요청 생성"""
        import uuid
        unique_id = uuid.uuid4().hex[:8]
        request = UniversalCrawlRequest(
            url=f"https://blog.naver.com/testuser/{unique_id}",
            url_type="naver_blog",
            status="pending",
            requested_by="pwa_share",
        )
        test_db_session.add(request)
        test_db_session.commit()

        # 조회 확인
        saved = test_db_session.query(UniversalCrawlRequest).filter_by(id=request.id).first()
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
        request = UniversalCrawlRequest(
            url=f"https://www.google.com/search?q=test_{unique_id}",
            url_type="generic",
            account_id=1,  # 로그인 필요한 경우
            status="pending",
        )
        test_db_session.add(request)
        test_db_session.commit()

        saved = test_db_session.query(UniversalCrawlRequest).filter_by(id=request.id).first()
        assert saved.account_id == 1

    def test_request_without_account_id(self, test_db_session):
        """account_id 없는 요청 (HTTP 전용 또는 기본 프로필)"""
        import uuid
        unique_id = uuid.uuid4().hex[:8]
        request = UniversalCrawlRequest(
            url=f"https://forms.gle/simple_{unique_id}",
            url_type="google_form",
            account_id=None,  # 브라우저 불필요
            status="pending",
        )
        test_db_session.add(request)
        test_db_session.commit()

        saved = test_db_session.query(UniversalCrawlRequest).filter_by(id=request.id).first()
        assert saved.account_id is None


class TestCrawlRequestRelationship:
    """요청-결과 관계 테스트"""

    def test_link_request_to_page(self, test_db_session, sample_crawled_page):
        """요청과 결과 페이지 연결"""
        request = UniversalCrawlRequest(
            url=sample_crawled_page.url,
            url_type=sample_crawled_page.url_type,
            status="completed",
            crawled_page_id=sample_crawled_page.id,
        )
        test_db_session.add(request)
        test_db_session.commit()

        # 관계 확인
        saved = test_db_session.query(UniversalCrawlRequest).filter_by(id=request.id).first()
        assert saved.crawled_page_id == sample_crawled_page.id
        assert saved.crawled_page is not None
        assert saved.crawled_page.title == "테스트 구글폼"
