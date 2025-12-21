"""
개별 게시물 재크롤링 기능 테스트

RIGHT-BICEP 원칙 적용:
- Right: 결과가 올바른가?
- Boundary: 경계값 테스트
- Inverse: 역관계 검증
- Cross-check: 교차 검증
- Error: 에러 조건 테스트
- Performance: 성능 테스트

CORRECT 조건 적용:
- Conformance: 형식 준수
- Ordering: 순서 보장
- Range: 범위 검증
- Reference: 참조 검증 (외래키, 연관 데이터)
- Existence: 존재 여부
- Cardinality: 개수 검증
- Time: 시간 관련 테스트

테스트 대상:
- InstagramCrawlRequest 모델 확장 (request_type, target_post_id)
- CrawlRequestService.create_single_post_request()
- CrawlService.recrawl_single_post()
- API 엔드포인트 POST /posts/{post_id}/recrawl
"""

import pytest
import sys
from pathlib import Path
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock, patch

# 프로젝트 루트 추가
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ============================================================
# 테스트 픽스처
# ============================================================

@pytest.fixture
def mock_db():
    """Mock 데이터베이스 세션"""
    return MagicMock()


@pytest.fixture
def mock_post():
    """Mock 게시물 객체"""
    post = MagicMock()
    post.id = 1
    post.post_id = "ABC123"
    post.account = "testuser"
    post.url = "https://www.instagram.com/p/ABC123/"
    post.caption = "Test caption"
    post.images = [{"src": "https://example.com/img.jpg", "alt": "Test"}]
    post.is_ad = False
    post.account_id = 1
    post.collected_at = datetime.now()
    return post


@pytest.fixture
def mock_account():
    """Mock 계정 객체"""
    account = MagicMock()
    account.id = 1
    account.name = "testaccount"
    account.is_logged_in = True
    return account


# ============================================================
# InstagramCrawlRequest 모델 테스트 - Right (결과 검증)
# ============================================================

class TestCrawlRequestModelExtension:
    """InstagramCrawlRequest 모델 확장 테스트"""

    def test_model_has_request_type_field(self):
        """request_type 필드 존재 확인"""
        from app.models.instagram_crawl_request import InstagramCrawlRequest

        assert hasattr(InstagramCrawlRequest, 'request_type')

    def test_model_has_target_post_id_field(self):
        """target_post_id 필드 존재 확인"""
        from app.models.instagram_crawl_request import InstagramCrawlRequest

        assert hasattr(InstagramCrawlRequest, 'target_post_id')

    def test_model_has_target_post_relationship(self):
        """target_post relationship 존재 확인"""
        from app.models.instagram_crawl_request import InstagramCrawlRequest

        assert hasattr(InstagramCrawlRequest, 'target_post')


# ============================================================
# CrawlRequestSchema 테스트 - Right (결과 검증)
# ============================================================

class TestCrawlRequestSchemaExtension:
    """CrawlRequestSchema 확장 테스트"""

    def test_schema_has_request_type_field(self):
        """스키마에 request_type 필드 존재"""
        from app.modules.instagram.models.schemas import CrawlRequestSchema

        fields = CrawlRequestSchema.model_fields
        assert 'request_type' in fields

    def test_schema_has_target_post_id_field(self):
        """스키마에 target_post_id 필드 존재"""
        from app.modules.instagram.models.schemas import CrawlRequestSchema

        fields = CrawlRequestSchema.model_fields
        assert 'target_post_id' in fields

    def test_schema_default_request_type(self):
        """request_type 기본값은 'feed'"""
        from app.modules.instagram.models.schemas import CrawlRequestSchema

        schema = CrawlRequestSchema(
            id=1,
            account_id=1,
            requested_at=datetime.now()
        )
        assert schema.request_type == "feed"

    def test_schema_default_target_post_id(self):
        """target_post_id 기본값은 None"""
        from app.modules.instagram.models.schemas import CrawlRequestSchema

        schema = CrawlRequestSchema(
            id=1,
            account_id=1,
            requested_at=datetime.now()
        )
        assert schema.target_post_id is None


# ============================================================
# CrawlRequestService 테스트 - Right (결과 검증)
# ============================================================

class TestCrawlRequestServiceSinglePost:
    """CrawlRequestService.create_single_post_request() 테스트"""

    def test_create_single_post_request_method_exists(self):
        """create_single_post_request 메서드 존재"""
        from app.modules.instagram.services.request_service import CrawlRequestService

        mock_db = MagicMock()
        service = CrawlRequestService(mock_db)

        assert hasattr(service, 'create_single_post_request')
        assert callable(service.create_single_post_request)

    def test_create_single_post_request_creates_request(self, mock_db):
        """새 single_post 요청 생성"""
        from app.modules.instagram.services.request_service import CrawlRequestService

        # 중복 없음
        mock_db.query.return_value.filter.return_value.first.return_value = None

        service = CrawlRequestService(mock_db)
        request = service.create_single_post_request(
            post_id=1,
            account_id=1,
            requested_by="manual"
        )

        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    def test_create_single_post_request_sets_request_type(self, mock_db):
        """request_type이 'single_post'로 설정됨"""
        from app.modules.instagram.services.request_service import CrawlRequestService

        mock_db.query.return_value.filter.return_value.first.return_value = None

        service = CrawlRequestService(mock_db)
        service.create_single_post_request(
            post_id=1,
            account_id=1,
            requested_by="manual"
        )

        # add 호출 시 전달된 객체 확인
        call_args = mock_db.add.call_args
        added_request = call_args[0][0]
        assert added_request.request_type == "single_post"

    def test_create_single_post_request_sets_target_post_id(self, mock_db):
        """target_post_id가 올바르게 설정됨"""
        from app.modules.instagram.services.request_service import CrawlRequestService

        mock_db.query.return_value.filter.return_value.first.return_value = None

        service = CrawlRequestService(mock_db)
        service.create_single_post_request(
            post_id=42,
            account_id=1,
            requested_by="manual"
        )

        call_args = mock_db.add.call_args
        added_request = call_args[0][0]
        assert added_request.target_post_id == 42

    def test_create_single_post_request_skips_duplicate(self, mock_db):
        """이미 대기 중인 동일 요청이 있으면 기존 요청 반환"""
        from app.modules.instagram.services.request_service import CrawlRequestService

        existing = MagicMock()
        existing.id = 99
        mock_db.query.return_value.filter.return_value.first.return_value = existing

        service = CrawlRequestService(mock_db)
        result = service.create_single_post_request(
            post_id=1,
            account_id=1,
            requested_by="manual"
        )

        assert result == existing
        mock_db.add.assert_not_called()


# ============================================================
# InstagramCrawler 테스트 - Right (결과 검증)
# ============================================================

class TestCrawlerSinglePost:
    """InstagramCrawler.crawl_single_post() 테스트"""

    def test_crawl_single_post_method_exists(self):
        """crawl_single_post 메서드 존재"""
        from app.modules.instagram.services.crawler import InstagramCrawler

        mock_page = MagicMock()
        crawler = InstagramCrawler(mock_page)

        assert hasattr(crawler, 'crawl_single_post')
        assert callable(crawler.crawl_single_post)


# ============================================================
# CrawlService 테스트 - Right (결과 검증)
# ============================================================

class TestCrawlServiceRecrawl:
    """CrawlService.recrawl_single_post() 테스트"""

    def test_recrawl_single_post_method_exists(self):
        """recrawl_single_post 메서드 존재"""
        from app.modules.instagram.services.crawl_service import CrawlService

        mock_db = MagicMock()
        service = CrawlService(mock_db)

        assert hasattr(service, 'recrawl_single_post')
        assert callable(service.recrawl_single_post)


# ============================================================
# 마이그레이션 테스트 - Existence (존재 여부)
# ============================================================

class TestMigration033:
    """033_add_single_post_recrawl 마이그레이션 테스트"""

    def test_migration_033_exists(self):
        """033_add_single_post_recrawl.sql 파일 존재"""
        migration_path = PROJECT_ROOT / "app" / "migrations" / "033_add_single_post_recrawl.sql"
        assert migration_path.exists(), "033_add_single_post_recrawl.sql should exist"

    def test_migration_033_contains_request_type(self):
        """마이그레이션에 request_type 컬럼 추가 포함"""
        migration_path = PROJECT_ROOT / "app" / "migrations" / "033_add_single_post_recrawl.sql"
        content = migration_path.read_text(encoding="utf-8")

        assert "request_type" in content

    def test_migration_033_contains_target_post_id(self):
        """마이그레이션에 target_post_id 컬럼 추가 포함"""
        migration_path = PROJECT_ROOT / "app" / "migrations" / "033_add_single_post_recrawl.sql"
        content = migration_path.read_text(encoding="utf-8")

        assert "target_post_id" in content


# ============================================================
# API 엔드포인트 테스트 - Conformance (형식 준수)
# ============================================================

class TestRecrawlAPIEndpoint:
    """POST /posts/{post_id}/recrawl API 엔드포인트 테스트"""

    def test_recrawl_endpoint_exists(self):
        """recrawl 엔드포인트가 라우터에 등록됨"""
        from app.modules.instagram.routes.instagram import router

        # 라우터의 routes 확인
        routes = [route.path for route in router.routes]
        assert "/posts/{post_id}/recrawl" in routes or any("/recrawl" in r for r in routes)


# ============================================================
# 워커 처리 테스트 - Right (결과 검증)
# ============================================================

class TestWorkerSinglePostProcessing:
    """워커 single_post 처리 테스트"""

    def test_worker_has_execute_single_post_recrawl_method(self):
        """워커에 _execute_single_post_recrawl 메서드 존재"""
        from app.worker.instagram_worker import InstagramWorker

        worker = InstagramWorker()
        assert hasattr(worker, '_execute_single_post_recrawl')
        assert callable(worker._execute_single_post_recrawl)

    def test_worker_has_execute_feed_crawl_method(self):
        """워커에 _execute_feed_crawl 메서드 존재 (기존 로직 분리)"""
        from app.worker.instagram_worker import InstagramWorker

        worker = InstagramWorker()
        assert hasattr(worker, '_execute_feed_crawl')
        assert callable(worker._execute_feed_crawl)


# ============================================================
# Error 조건 테스트
# ============================================================

class TestRecrawlErrorConditions:
    """재크롤링 에러 조건 테스트"""

    def test_recrawl_post_not_found(self, mock_db):
        """존재하지 않는 게시물 재크롤링 시 실패"""
        from app.modules.instagram.services.crawl_service import CrawlService

        mock_db.query.return_value.filter.return_value.first.return_value = None

        service = CrawlService(mock_db)

        # 비동기 테스트를 위한 설정
        import asyncio

        async def test():
            mock_crawler = MagicMock()
            result = await service.recrawl_single_post(mock_crawler, 999)
            assert result["success"] is False
            assert "not found" in result["message"].lower()

        asyncio.run(test())

    def test_recrawl_post_no_url(self, mock_db, mock_post):
        """URL이 없는 게시물 재크롤링 시 실패"""
        from app.modules.instagram.services.crawl_service import CrawlService

        mock_post.url = None
        mock_db.query.return_value.filter.return_value.first.return_value = mock_post

        service = CrawlService(mock_db)

        import asyncio

        async def test():
            mock_crawler = MagicMock()
            result = await service.recrawl_single_post(mock_crawler, 1)
            assert result["success"] is False
            assert "no url" in result["message"].lower()

        asyncio.run(test())


# ============================================================
# 기존 기능 호환성 테스트 (Cross-check)
# ============================================================

class TestBackwardCompatibility:
    """기존 feed 크롤링 기능 호환성 테스트"""

    def test_feed_request_still_works(self, mock_db):
        """기존 feed 요청 생성이 정상 동작"""
        from app.modules.instagram.services.request_service import CrawlRequestService

        mock_db.query.return_value.filter.return_value.first.return_value = None

        service = CrawlRequestService(mock_db)
        request = service.create_request(
            account_id=1,
            requested_by="manual"
        )

        mock_db.add.assert_called_once()

    def test_crawl_request_schema_backward_compatible(self):
        """기존 스키마 필드 유지"""
        from app.modules.instagram.models.schemas import CrawlRequestSchema

        fields = CrawlRequestSchema.model_fields

        # 기존 필드들 존재 확인
        assert 'id' in fields
        assert 'account_id' in fields
        assert 'requested_at' in fields
        assert 'requested_by' in fields
        assert 'status' in fields
        assert 'processed_at' in fields
        assert 'crawl_run_id' in fields
        assert 'error_message' in fields


# ============================================================
# Boundary 테스트
# ============================================================

class TestRecrawlBoundary:
    """재크롤링 경계값 테스트"""

    def test_request_type_values(self):
        """request_type 값 검증"""
        from app.modules.instagram.models.schemas import CrawlRequestSchema

        # feed 타입
        feed_schema = CrawlRequestSchema(
            id=1,
            account_id=1,
            requested_at=datetime.now(),
            request_type="feed"
        )
        assert feed_schema.request_type == "feed"

        # single_post 타입
        single_post_schema = CrawlRequestSchema(
            id=2,
            account_id=1,
            requested_at=datetime.now(),
            request_type="single_post",
            target_post_id=42
        )
        assert single_post_schema.request_type == "single_post"
        assert single_post_schema.target_post_id == 42


# ============================================================
# Reference 테스트 (외래키 관계)
# ============================================================

class TestRecrawlReferences:
    """재크롤링 참조 관계 테스트"""

    def test_target_post_id_references_instagram_posts(self):
        """target_post_id가 instagram_posts 테이블 참조"""
        migration_path = PROJECT_ROOT / "app" / "migrations" / "033_add_single_post_recrawl.sql"
        content = migration_path.read_text(encoding="utf-8")

        assert "instagram_posts" in content
        assert "REFERENCES" in content.upper() or "references" in content.lower()
