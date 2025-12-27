"""
Google 검색 모델 테스트

RIGHT-BICEP 패턴:
- Right: 올바른 결과 반환
- Boundary: 경계 조건 테스트
- Inverse: 역관계 테스트
- Cross-check: 교차 검증
- Error: 에러 조건 테스트
- Performance: 성능 테스트 (필요시)
"""

import pytest
from datetime import datetime

from app.models.google_search import (
    GoogleSavedSearch,
    GoogleSearchHistory,
    GoogleSearchResult,
)


class TestGoogleSavedSearch:
    """저장된 검색 조건 모델 테스트"""

    def test_create_saved_search_right(self, test_db_session):
        """Right: 저장된 검색 생성"""
        saved = GoogleSavedSearch(
            name="Python 블로그 검색",
            query="python tutorial site:blog.example.com",
            date_filter="1w",
            max_pages=3,
            is_favorite=True,
        )
        test_db_session.add(saved)
        test_db_session.commit()
        test_db_session.refresh(saved)

        assert saved.id is not None
        assert saved.name == "Python 블로그 검색"
        assert saved.query == "python tutorial site:blog.example.com"
        assert saved.date_filter == "1w"
        assert saved.max_pages == 3
        assert saved.is_favorite is True
        assert saved.created_at is not None

    def test_create_saved_search_default_values(self, test_db_session):
        """Right: 기본값 확인"""
        saved = GoogleSavedSearch(
            name="간단 검색",
            query="hello world",
        )
        test_db_session.add(saved)
        test_db_session.commit()
        test_db_session.refresh(saved)

        assert saved.max_pages == 1
        assert saved.is_favorite is False
        assert saved.date_filter is None
        assert saved.service_account_id is None

    def test_update_saved_search(self, test_db_session):
        """Right: 저장된 검색 수정"""
        saved = GoogleSavedSearch(name="Test", query="test query")
        test_db_session.add(saved)
        test_db_session.commit()

        saved.name = "Updated Test"
        saved.is_favorite = True
        saved.updated_at = datetime.now()
        test_db_session.commit()
        test_db_session.refresh(saved)

        assert saved.name == "Updated Test"
        assert saved.is_favorite is True

    def test_delete_saved_search(self, test_db_session):
        """Right: 저장된 검색 삭제"""
        saved = GoogleSavedSearch(name="To Delete", query="delete me")
        test_db_session.add(saved)
        test_db_session.commit()
        saved_id = saved.id

        test_db_session.delete(saved)
        test_db_session.commit()

        result = test_db_session.query(GoogleSavedSearch).filter_by(id=saved_id).first()
        assert result is None

    def test_saved_search_boundary_empty_query(self, test_db_session):
        """Boundary: 빈 쿼리는 허용 (DB 레벨에서 제약 없음, 앱에서 검증)"""
        saved = GoogleSavedSearch(name="Empty Query", query="")
        test_db_session.add(saved)
        test_db_session.commit()

        assert saved.query == ""


class TestGoogleSearchHistory:
    """검색 히스토리 모델 테스트"""

    def test_create_history_right(self, test_db_session):
        """Right: 검색 히스토리 생성"""
        history = GoogleSearchHistory(
            search_id="test-uuid-12345",
            query="python flask",
            date_filter="24h",
            max_pages=2,
            status="completed",
            total_results=45,
            started_at=datetime.now(),
            completed_at=datetime.now(),
        )
        test_db_session.add(history)
        test_db_session.commit()
        test_db_session.refresh(history)

        assert history.id is not None
        assert history.search_id == "test-uuid-12345"
        assert history.status == "completed"
        assert history.total_results == 45

    def test_history_default_status(self, test_db_session):
        """Right: 기본 상태 확인"""
        history = GoogleSearchHistory(
            search_id="test-uuid-default",
            query="test",
        )
        test_db_session.add(history)
        test_db_session.commit()
        test_db_session.refresh(history)

        assert history.status == "pending"
        assert history.total_results == 0

    def test_history_with_error(self, test_db_session):
        """Error: 에러 상태 히스토리"""
        history = GoogleSearchHistory(
            search_id="test-uuid-error",
            query="error test",
            status="failed",
            error_message="CAPTCHA detected",
        )
        test_db_session.add(history)
        test_db_session.commit()
        test_db_session.refresh(history)

        assert history.status == "failed"
        assert history.error_message == "CAPTCHA detected"

    def test_history_unique_search_id(self, test_db_session):
        """Boundary: search_id 유니크 제약"""
        history1 = GoogleSearchHistory(
            search_id="unique-id-123",
            query="query1",
        )
        test_db_session.add(history1)
        test_db_session.commit()

        history2 = GoogleSearchHistory(
            search_id="unique-id-123",
            query="query2",
        )
        test_db_session.add(history2)

        with pytest.raises(Exception):
            test_db_session.commit()


class TestGoogleSearchResult:
    """검색 결과 모델 테스트"""

    @pytest.fixture
    def sample_history(self, test_db_session):
        """테스트용 검색 히스토리"""
        import uuid
        history = GoogleSearchHistory(
            search_id=f"result-test-{uuid.uuid4().hex[:8]}",
            query="sample query",
            status="completed",
            total_results=10,
        )
        test_db_session.add(history)
        test_db_session.commit()
        return history

    def test_create_result_right(self, test_db_session, sample_history):
        """Right: 검색 결과 생성"""
        result = GoogleSearchResult(
            search_id=sample_history.search_id,
            query="sample query",
            rank=1,
            title="First Result Title",
            url="https://example.com/first",
            display_url="example.com › first",
            snippet="This is the first result snippet...",
            publish_date="2024년 12월 1일",
            date_filter="1w",
            page_number=1,
        )
        test_db_session.add(result)
        test_db_session.commit()
        test_db_session.refresh(result)

        assert result.id is not None
        assert result.rank == 1
        assert result.title == "First Result Title"
        assert result.url == "https://example.com/first"

    def test_result_relationship_to_history(self, test_db_session, sample_history):
        """Inverse: 히스토리와의 관계 테스트"""
        result = GoogleSearchResult(
            search_id=sample_history.search_id,
            query="sample query",
            rank=1,
            title="Test",
            url="https://test.com",
        )
        test_db_session.add(result)
        test_db_session.commit()
        test_db_session.refresh(result)

        # 관계 확인
        assert result.history is not None
        assert result.history.search_id == sample_history.search_id

    def test_multiple_results_for_history(self, test_db_session, sample_history):
        """Cross-check: 하나의 히스토리에 여러 결과"""
        for i in range(5):
            result = GoogleSearchResult(
                search_id=sample_history.search_id,
                query="sample query",
                rank=i + 1,
                title=f"Result {i + 1}",
                url=f"https://example.com/{i}",
            )
            test_db_session.add(result)

        test_db_session.commit()

        results = (
            test_db_session.query(GoogleSearchResult)
            .filter_by(search_id=sample_history.search_id)
            .order_by(GoogleSearchResult.rank)
            .all()
        )

        assert len(results) == 5
        assert results[0].rank == 1
        assert results[4].rank == 5

    def test_cascade_delete_on_history(self, test_db_session):
        """Inverse: 히스토리 삭제 시 결과도 삭제 (CASCADE)"""
        history = GoogleSearchHistory(
            search_id="cascade-test-uuid",
            query="cascade test",
        )
        test_db_session.add(history)
        test_db_session.commit()

        result = GoogleSearchResult(
            search_id=history.search_id,
            query="cascade test",
            rank=1,
            title="Will be deleted",
            url="https://delete.me",
        )
        test_db_session.add(result)
        test_db_session.commit()

        # 히스토리 삭제
        test_db_session.delete(history)
        test_db_session.commit()

        # 결과도 삭제되었는지 확인
        remaining = (
            test_db_session.query(GoogleSearchResult)
            .filter_by(search_id="cascade-test-uuid")
            .all()
        )
        assert len(remaining) == 0


class TestModelInteractions:
    """모델 간 상호작용 테스트"""

    def test_saved_search_with_last_run_info(self, test_db_session):
        """저장된 검색과 마지막 실행 정보 연동"""
        # 저장된 검색 생성
        saved = GoogleSavedSearch(
            name="Tracking Test",
            query="track me",
        )
        test_db_session.add(saved)
        test_db_session.commit()

        # 검색 실행 시뮬레이션
        history = GoogleSearchHistory(
            search_id="tracking-uuid",
            query="track me",
            status="completed",
            total_results=25,
        )
        test_db_session.add(history)
        test_db_session.commit()

        # 저장된 검색 업데이트
        saved.last_search_id = history.search_id
        saved.last_run_at = datetime.now()
        saved.last_result_count = history.total_results
        test_db_session.commit()
        test_db_session.refresh(saved)

        assert saved.last_search_id == "tracking-uuid"
        assert saved.last_result_count == 25
        assert saved.last_run_at is not None
