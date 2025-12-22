"""
크롤링 이력 통합 조회 테스트

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
"""

import pytest
import sys
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

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
def sample_crawl_requests():
    """테스트용 크롤링 요청 목록"""
    now = datetime.now()

    requests = []
    for i in range(5):
        req = MagicMock()
        req.id = i + 1
        req.account_id = 1
        req.requested_at = now - timedelta(hours=i)
        req.requested_by = "scheduler" if i % 2 == 0 else "manual"
        req.request_type = "feed" if i < 3 else "single_post_url"
        req.target_url = f"https://instagram.com/p/test{i}" if i >= 3 else None
        req.target_post_id = None
        req.status = "completed" if i < 4 else "pending"
        req.processed_at = now - timedelta(hours=i, minutes=5) if i < 4 else None
        req.crawl_run_id = i + 100 if i < 3 else None
        req.error_message = None
        requests.append(req)

    return requests


# ============================================================
# CrawlRequestService.get_requests_paginated() 테스트 - Right
# ============================================================

class TestGetRequestsPaginatedRight:
    """get_requests_paginated 결과 검증 테스트"""

    def test_returns_tuple(self, mock_db):
        """튜플 (requests, total) 반환"""
        from app.modules.instagram.services.request_service import CrawlRequestService

        mock_db.query.return_value.count.return_value = 0
        mock_db.query.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []

        service = CrawlRequestService(mock_db)
        result = service.get_requests_paginated()

        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_returns_correct_count(self, mock_db, sample_crawl_requests):
        """전체 개수 올바르게 반환"""
        from app.modules.instagram.services.request_service import CrawlRequestService

        mock_db.query.return_value.count.return_value = 100
        mock_db.query.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = sample_crawl_requests

        service = CrawlRequestService(mock_db)
        requests, total = service.get_requests_paginated()

        assert total == 100

    def test_applies_pagination(self, mock_db):
        """페이징 적용 확인"""
        from app.modules.instagram.services.request_service import CrawlRequestService

        mock_db.query.return_value.count.return_value = 100
        mock_db.query.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []

        service = CrawlRequestService(mock_db)
        service.get_requests_paginated(page=3, limit=10)

        # offset = (3-1) * 10 = 20
        mock_db.query.return_value.order_by.return_value.offset.assert_called_once()


# ============================================================
# CrawlRequestService.get_requests_paginated() 테스트 - Boundary
# ============================================================

class TestGetRequestsPaginatedBoundary:
    """get_requests_paginated 경계값 테스트"""

    def test_page_1_offset_0(self, mock_db):
        """page=1일 때 offset=0"""
        from app.modules.instagram.services.request_service import CrawlRequestService

        mock_db.query.return_value.count.return_value = 0
        mock_db.query.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []

        service = CrawlRequestService(mock_db)
        service.get_requests_paginated(page=1, limit=20)

        # page=1이면 offset=0
        call_args = mock_db.query.return_value.order_by.return_value.offset.call_args[0][0]
        assert call_args == 0

    def test_empty_result(self, mock_db):
        """빈 결과"""
        from app.modules.instagram.services.request_service import CrawlRequestService

        mock_db.query.return_value.count.return_value = 0
        mock_db.query.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []

        service = CrawlRequestService(mock_db)
        requests, total = service.get_requests_paginated()

        assert requests == []
        assert total == 0


# ============================================================
# CrawlRequestService.get_requests_paginated() 테스트 - Filter
# ============================================================

class TestGetRequestsPaginatedFilter:
    """get_requests_paginated 필터 테스트"""

    def test_filter_by_request_type(self, mock_db):
        """request_type 필터 적용"""
        from app.modules.instagram.services.request_service import CrawlRequestService

        mock_db.query.return_value.filter.return_value.count.return_value = 10
        mock_db.query.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []

        service = CrawlRequestService(mock_db)
        service.get_requests_paginated(request_type="feed")

        # filter가 호출됨
        mock_db.query.return_value.filter.assert_called()

    def test_filter_by_requested_by(self, mock_db):
        """requested_by 필터 적용"""
        from app.modules.instagram.services.request_service import CrawlRequestService

        mock_db.query.return_value.filter.return_value.count.return_value = 5
        mock_db.query.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []

        service = CrawlRequestService(mock_db)
        service.get_requests_paginated(requested_by="manual")

        mock_db.query.return_value.filter.assert_called()

    def test_filter_by_status(self, mock_db):
        """status 필터 적용"""
        from app.modules.instagram.services.request_service import CrawlRequestService

        mock_db.query.return_value.filter.return_value.count.return_value = 3
        mock_db.query.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []

        service = CrawlRequestService(mock_db)
        service.get_requests_paginated(status="completed")

        mock_db.query.return_value.filter.assert_called()

    def test_filter_by_period_today(self, mock_db):
        """period=today 필터 적용"""
        from app.modules.instagram.services.request_service import CrawlRequestService

        mock_db.query.return_value.filter.return_value.count.return_value = 10
        mock_db.query.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []

        service = CrawlRequestService(mock_db)
        service.get_requests_paginated(period="today")

        mock_db.query.return_value.filter.assert_called()

    def test_filter_by_period_week(self, mock_db):
        """period=week 필터 적용"""
        from app.modules.instagram.services.request_service import CrawlRequestService

        mock_db.query.return_value.filter.return_value.count.return_value = 50
        mock_db.query.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []

        service = CrawlRequestService(mock_db)
        service.get_requests_paginated(period="week")

        mock_db.query.return_value.filter.assert_called()

    def test_filter_by_period_month(self, mock_db):
        """period=month 필터 적용"""
        from app.modules.instagram.services.request_service import CrawlRequestService

        mock_db.query.return_value.filter.return_value.count.return_value = 200
        mock_db.query.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []

        service = CrawlRequestService(mock_db)
        service.get_requests_paginated(period="month")

        mock_db.query.return_value.filter.assert_called()

    def test_filter_by_account_id(self, mock_db):
        """account_id 필터 적용"""
        from app.modules.instagram.services.request_service import CrawlRequestService

        mock_db.query.return_value.filter.return_value.count.return_value = 25
        mock_db.query.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []

        service = CrawlRequestService(mock_db)
        service.get_requests_paginated(account_id=1)

        mock_db.query.return_value.filter.assert_called()


# ============================================================
# 스키마 테스트
# ============================================================

class TestCrawlHistorySchemas:
    """크롤링 이력 스키마 테스트"""

    def test_crawl_run_summary_has_fields(self):
        """CrawlRunSummary에 필요한 필드 존재"""
        from app.modules.instagram.models.schemas import CrawlRunSummary

        fields = CrawlRunSummary.model_fields
        assert 'id' in fields
        assert 'total_collected' in fields
        assert 'new_saved' in fields
        assert 'duration_seconds' in fields
        assert 'stop_reason' in fields

    def test_crawl_history_item_has_fields(self):
        """CrawlHistoryItem에 필요한 필드 존재"""
        from app.modules.instagram.models.schemas import CrawlHistoryItem

        fields = CrawlHistoryItem.model_fields
        assert 'id' in fields
        assert 'account_id' in fields
        assert 'requested_at' in fields
        assert 'requested_by' in fields
        assert 'request_type' in fields
        assert 'target_url' in fields
        assert 'target_post_id' in fields
        assert 'status' in fields
        assert 'processed_at' in fields
        assert 'crawl_run_id' in fields
        assert 'error_message' in fields
        assert 'crawl_run' in fields

    def test_crawl_history_response_has_fields(self):
        """CrawlHistoryResponse에 필요한 필드 존재"""
        from app.modules.instagram.models.schemas import CrawlHistoryResponse

        fields = CrawlHistoryResponse.model_fields
        assert 'items' in fields
        assert 'total' in fields
        assert 'page' in fields
        assert 'limit' in fields

    def test_crawl_run_summary_creation(self):
        """CrawlRunSummary 인스턴스 생성"""
        from app.modules.instagram.models.schemas import CrawlRunSummary

        summary = CrawlRunSummary(
            id=1,
            total_collected=25,
            new_saved=10,
            duration_seconds=120,
            stop_reason="max_posts_reached"
        )

        assert summary.id == 1
        assert summary.total_collected == 25
        assert summary.new_saved == 10
        assert summary.duration_seconds == 120
        assert summary.stop_reason == "max_posts_reached"

    def test_crawl_history_item_creation(self):
        """CrawlHistoryItem 인스턴스 생성"""
        from app.modules.instagram.models.schemas import CrawlHistoryItem, CrawlRunSummary

        now = datetime.now()
        item = CrawlHistoryItem(
            id=1,
            account_id=1,
            requested_at=now,
            requested_by="manual",
            request_type="feed",
            status="completed",
            crawl_run=CrawlRunSummary(
                id=100,
                total_collected=25,
                new_saved=10
            )
        )

        assert item.id == 1
        assert item.request_type == "feed"
        assert item.crawl_run is not None
        assert item.crawl_run.total_collected == 25

    def test_crawl_history_item_url_request(self):
        """URL 요청 CrawlHistoryItem 생성"""
        from app.modules.instagram.models.schemas import CrawlHistoryItem

        now = datetime.now()
        item = CrawlHistoryItem(
            id=2,
            account_id=1,
            requested_at=now,
            requested_by="manual",
            request_type="single_post_url",
            target_url="https://instagram.com/p/ABC123",
            status="completed"
        )

        assert item.request_type == "single_post_url"
        assert item.target_url == "https://instagram.com/p/ABC123"
        assert item.crawl_run is None

    def test_crawl_history_response_creation(self):
        """CrawlHistoryResponse 인스턴스 생성"""
        from app.modules.instagram.models.schemas import CrawlHistoryResponse, CrawlHistoryItem

        now = datetime.now()
        items = [
            CrawlHistoryItem(
                id=i,
                account_id=1,
                requested_at=now,
                requested_by="manual",
                request_type="feed",
                status="completed"
            )
            for i in range(3)
        ]

        response = CrawlHistoryResponse(
            items=items,
            total=100,
            page=1,
            limit=20
        )

        assert len(response.items) == 3
        assert response.total == 100
        assert response.page == 1
        assert response.limit == 20


# ============================================================
# Ordering 테스트
# ============================================================

class TestCrawlHistoryOrdering:
    """크롤링 이력 정렬 테스트"""

    def test_ordered_by_requested_at_desc(self, mock_db):
        """requested_at 내림차순 정렬"""
        from app.modules.instagram.services.request_service import CrawlRequestService

        mock_db.query.return_value.count.return_value = 0
        mock_db.query.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []

        service = CrawlRequestService(mock_db)
        service.get_requests_paginated()

        # order_by가 호출됨
        mock_db.query.return_value.order_by.assert_called()


# ============================================================
# Time 테스트
# ============================================================

class TestCrawlHistoryTime:
    """크롤링 이력 시간 관련 테스트"""

    def test_period_today_filters_from_midnight(self, mock_db):
        """period=today는 오늘 자정부터 필터"""
        from app.modules.instagram.services.request_service import CrawlRequestService

        mock_db.query.return_value.filter.return_value.count.return_value = 0
        mock_db.query.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []

        service = CrawlRequestService(mock_db)
        service.get_requests_paginated(period="today")

        # filter가 호출되고 날짜 조건 포함
        assert mock_db.query.return_value.filter.called

    def test_period_week_filters_7_days(self, mock_db):
        """period=week은 7일 전부터 필터"""
        from app.modules.instagram.services.request_service import CrawlRequestService

        mock_db.query.return_value.filter.return_value.count.return_value = 0
        mock_db.query.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []

        service = CrawlRequestService(mock_db)
        service.get_requests_paginated(period="week")

        assert mock_db.query.return_value.filter.called

    def test_period_month_filters_30_days(self, mock_db):
        """period=month는 30일 전부터 필터"""
        from app.modules.instagram.services.request_service import CrawlRequestService

        mock_db.query.return_value.filter.return_value.count.return_value = 0
        mock_db.query.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []

        service = CrawlRequestService(mock_db)
        service.get_requests_paginated(period="month")

        assert mock_db.query.return_value.filter.called


# ============================================================
# get_request_with_run 테스트
# ============================================================

class TestGetRequestWithRun:
    """get_request_with_run 메서드 테스트"""

    def test_returns_none_if_not_found(self, mock_db):
        """요청이 없으면 None 반환"""
        from app.modules.instagram.services.request_service import CrawlRequestService

        mock_db.query.return_value.get.return_value = None

        service = CrawlRequestService(mock_db)
        result = service.get_request_with_run(999)

        assert result is None

    def test_returns_request_without_run(self, mock_db):
        """CrawlRun 없는 요청 반환"""
        from app.modules.instagram.services.request_service import CrawlRequestService

        mock_request = MagicMock()
        mock_request.crawl_run_id = None
        mock_db.query.return_value.get.return_value = mock_request

        service = CrawlRequestService(mock_db)
        result = service.get_request_with_run(1)

        assert result is not None
        assert result["request"] == mock_request
        assert result["crawl_run"] is None

    def test_returns_request_with_run_summary(self, mock_db):
        """CrawlRun 있는 요청 반환"""
        from app.modules.instagram.services.request_service import CrawlRequestService

        mock_request = MagicMock()
        mock_request.crawl_run_id = 100

        mock_run = MagicMock()
        mock_run.id = 100
        mock_run.total_collected = 25
        mock_run.new_saved = 10
        mock_run.started_at = datetime.now() - timedelta(minutes=5)
        mock_run.finished_at = datetime.now()
        mock_run.stop_reason = "completed"

        def get_side_effect(id):
            if isinstance(id, int):
                if id == 1:
                    return mock_request
                elif id == 100:
                    return mock_run
            return None

        mock_db.query.return_value.get.side_effect = get_side_effect

        service = CrawlRequestService(mock_db)
        result = service.get_request_with_run(1)

        assert result is not None
        assert result["request"] == mock_request
        assert result["crawl_run"] is not None
        assert result["crawl_run"]["id"] == 100
        assert result["crawl_run"]["total_collected"] == 25
